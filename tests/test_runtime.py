import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import requests
from openai import RateLimitError

import main

ROOT = Path(__file__).resolve().parents[1]
os.environ["PATH"] = str(Path(sys.executable).resolve().parent) + os.pathsep + os.environ.get("PATH", "")


class Completion:
    def __init__(self, text):
        self.choices = [type("Choice", (), {"message": type("Msg", (), {"content": text})()})()]


class ScriptedCompletions:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return Completion(result)


class ScriptedClient:
    def __init__(self, results):
        self.chat = type("Chat", (), {})()
        self.chat.completions = ScriptedCompletions(results)


class LocalGitHub(BaseHTTPRequestHandler):
    routes = {}

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        return json.loads(raw.decode() or "null")

    def _send(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        status, payload = self.routes["GET"](self.path, self.headers)
        self._send(status, payload)

    def do_POST(self):
        status, payload = self.routes["POST"](self.path, self.headers, self._read_json())
        self._send(status, payload)

    def log_message(self, fmt, *args):
        return


class RuntimeTests(unittest.TestCase):
    def test_requirements_match_reviewed_bumps(self):
        pins = dict(
            line.split("==", 1)
            for line in (ROOT / "requirements.txt").read_text().splitlines()
            if "==" in line
        )
        self.assertEqual(pins["requests"], "2.34.2")
        self.assertEqual(pins["openai"], "3.46.0")
        self.assertEqual(pins["commitlint"], "2.0.0")
        self.assertGreaterEqual(tuple(int(p) for p in requests.__version__.split(".")[:3]), (2, 34, 2))

    def test_legacy_openai_and_npx_are_gone(self):
        source = (ROOT / "main.py").read_text()
        self.assertNotIn("openai.Completion", source)
        self.assertNotIn("openai.error", source)
        self.assertNotIn("npx", source)
        self.assertNotIn("text-davinci-003", source)

    def test_action_does_not_pass_secrets_as_args(self):
        action = (ROOT / "action.yaml").read_text()
        self.assertNotIn("args:", action)
        self.assertNotIn("inputs.openai_api_key", action)
        self.assertNotIn("inputs.github_token", action)
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("FROM ubuntu:26.04", dockerfile)
        self.assertNotIn("python3.12 \\", dockerfile)
        self.assertIn("python3-venv", dockerfile)

    def test_missing_and_blank_env(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                main.load_env_vars()
        env = {
            "OPENAI_API_KEY": " ",
            "GITHUB_TOKEN": "t",
            "REPO_OWNER": "octo",
            "REPO_NAME": "repo",
            "REPO_BRANCH": "feature",
            "REPO_HEAD": "feature",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ValueError) as caught:
                main.load_env_vars()
        self.assertIn("OPENAI_API_KEY", str(caught.exception))

    def test_rejects_repository_names_that_change_the_request(self):
        for owner in ["evil.com?x", "octo/../other", "..", ".hidden", "a b", ""]:
            with self.assertRaises(ValueError):
                main.require_github_name(owner, "repository owner")
        self.assertEqual(main.normalize_ref("refs/heads/feature", "branch name"), "feature")
        with self.assertRaises(ValueError):
            main.normalize_ref("refs/heads/../../etc", "branch name")

    def test_github_calls_ignore_proxy_env_and_stay_on_the_local_server(self):
        seen = {}

        def get(path, headers):
            seen["get"] = (path, headers.get("Authorization"))
            return 200, []

        def post(path, headers, payload):
            seen["post"] = (path, headers.get("Authorization"), payload)
            if path.endswith("/comments"):
                return 201, {"id": 9}
            return 201, {"html_url": "http://example.test/pull/1", "number": 1}

        server = ThreadingHTTPServer(("127.0.0.1", 0), LocalGitHub)
        LocalGitHub.routes = {"GET": get, "POST": post}
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        base = f"http://127.0.0.1:{server.server_address[1]}"
        session = main.github_session("test-token")
        self.assertFalse(session.trust_env)
        with mock.patch.dict(
            os.environ,
            {"HTTP_PROXY": "http://127.0.0.1:1", "http_proxy": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1"},
        ):
            pulls = main.check_for_existing_pr(
                "octo", "repo", "refs/heads/feature", "test-token", session=session, api_base=base
            )
            created = main.create_pr(
                "octo",
                "repo",
                "feat: add thing",
                "body",
                "feature",
                "master",
                "test-token",
                session=session,
                api_base=base,
            )
        self.assertEqual(pulls, [])
        self.assertEqual(created["number"], 1)
        self.assertIn("/repos/octo/repo/pulls", seen["get"][0])
        self.assertTrue(
            "head=octo:feature" in seen["get"][0] or "head=octo%3Afeature" in seen["get"][0]
        )
        self.assertEqual(seen["get"][1], "Bearer test-token")
        self.assertEqual(seen["post"][2]["base"], "master")
        self.assertNotIn("127.0.0.1:1", seen["post"][0])

    def test_chat_completions_retry_on_rate_limit(self):
        response = type(
            "Resp",
            (),
            {"request": object(), "status_code": 429, "headers": {}},
        )()
        client = ScriptedClient(
            [RateLimitError("slow down", response=response, body=None), "feat: generated title"]
        )
        with mock.patch("main.time.sleep") as sleep:
            title = main.generate_pr_title(client, "feat: add tests")
        self.assertEqual(title, "feat: generated title")
        sleep.assert_called_once()
        self.assertEqual(client.chat.completions.calls[0]["model"], main.DEFAULT_MODEL)
        self.assertIn("feat: add tests", client.chat.completions.calls[0]["messages"][0]["content"])

    def test_empty_completion_is_rejected(self):
        client = ScriptedClient(["   "])
        with self.assertRaises(RuntimeError):
            main.generate_pr_comment(client, "title", "description")

    def test_commitlint_cli_accepts_conventional_and_rejects_freeform(self):
        good = main.verify_commit_message("feat: wire commitlint cli")
        bad = main.verify_commit_message("Update stuff")
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertNotEqual(bad.returncode, 0)
        self.assertFalse(list(Path.cwd().glob("commit_message.txt")))

    def test_git_history_and_main_create_path(self):
        repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, repo)
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "dev@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True)
        (Path(repo) / "note.txt").write_text("hello\n")
        subprocess.run(["git", "add", "note.txt"], cwd=repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", "feat: record a note"],
            cwd=repo,
            check=True,
            capture_output=True,
        )

        with mock.patch.dict(os.environ, {}, clear=False):
            os.chdir(repo)
            try:
                self.assertEqual(main.get_latest_commit_message(), "feat: record a note")
                self.assertIn("feat: record a note", main.get_commit_history(limit=5))
            finally:
                os.chdir(ROOT)

        created = {}

        def fake_check(*args, **kwargs):
            return []

        def fake_create(*args, **kwargs):
            created["args"] = args
            return {"html_url": "http://example.test/pull/4"}

        env = {
            "OPENAI_API_KEY": "test-key",
            "GITHUB_TOKEN": "test-token",
            "REPO_OWNER": "octo",
            "REPO_NAME": "repo",
            "REPO_BRANCH": "master",
            "REPO_HEAD": "feature",
        }
        client = ScriptedClient(["feat: record a note", "A description of the note."])
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(
            main, "build_openai_client", return_value=client
        ), mock.patch.object(main, "get_latest_commit_message", return_value="feat: record a note"), mock.patch.object(
            main, "get_commit_history", return_value="feat: record a note"
        ), mock.patch.object(
            main, "check_for_existing_pr", side_effect=fake_check
        ), mock.patch.object(
            main, "create_pr", side_effect=fake_create
        ), mock.patch.object(
            main, "verify_commit_message", return_value=subprocess.CompletedProcess(["commitlint"], 0, "", "")
        ):
            code = main.main()
        self.assertEqual(code, 0)
        self.assertEqual(created["args"][2], "feat: record a note")
        self.assertEqual(created["args"][4], "feature")
        self.assertEqual(created["args"][5], "master")

    def test_main_stops_on_invalid_commit_without_calling_openai(self):
        env = {
            "OPENAI_API_KEY": "test-key",
            "GITHUB_TOKEN": "test-token",
            "REPO_OWNER": "octo",
            "REPO_NAME": "repo",
            "REPO_BRANCH": "master",
            "REPO_HEAD": "feature",
        }
        called = mock.Mock()
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(
            main, "get_latest_commit_message", return_value="Update stuff"
        ), mock.patch.object(
            main,
            "verify_commit_message",
            return_value=subprocess.CompletedProcess(["commitlint"], 1, "", "subject must use conventional commits"),
        ), mock.patch.object(main, "build_openai_client", called):
            code = main.main()
        self.assertEqual(code, 1)
        called.assert_not_called()

    def test_entrypoint_maps_action_inputs(self):
        bindir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, bindir)
        recorded = Path(bindir) / "captured.json"
        python_stub = Path(bindir) / "python3"
        real_python = shutil.which("python3")
        python_stub.write_text(
            "#!/bin/sh\n"
            f"{real_python} - <<'PY'\n"
            "import json, os\n"
            f"open({str(recorded)!r}, 'w').write(json.dumps({{k: os.environ.get(k) for k in ['OPENAI_API_KEY','GITHUB_TOKEN','REPO_OWNER','REPO_NAME','REPO_BRANCH','REPO_HEAD','OPENAI_MODEL']}}))\n"
            "PY\n"
        )
        python_stub.chmod(0o755)
        git_stub = Path(bindir) / "git"
        git_stub.write_text("#!/bin/sh\nexit 0\n")
        git_stub.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = f"{bindir}:{env['PATH']}"
        env["INPUT_OPENAI_API_KEY"] = "sk-test"
        env["INPUT_GITHUB_TOKEN"] = "gh-test"
        env["INPUT_REPOSITORY_OWNER"] = "Sinless777"
        env["INPUT_REPOSITORY"] = "Sinless777/PR-Creator"
        env["INPUT_BRANCH"] = "refs/heads/feature/widget"
        env["INPUT_HEAD"] = "abc123def"
        env["INPUT_OPENAI_MODEL"] = "gpt-4o-mini"
        env["INPUT_EMAIL"] = "dev@example.com"
        env["GITHUB_ACTOR"] = "tester"
        for key in ["OPENAI_API_KEY", "GITHUB_TOKEN", "REPO_OWNER", "REPO_NAME", "REPO_BRANCH", "REPO_HEAD", "OPENAI_MODEL"]:
            env.pop(key, None)
        subprocess.run(["bash", str(ROOT / "entrypoint.sh")], cwd=ROOT, env=env, check=True, capture_output=True, text=True)
        captured = json.loads(recorded.read_text())
        self.assertEqual(captured["OPENAI_API_KEY"], "sk-test")
        self.assertEqual(captured["GITHUB_TOKEN"], "gh-test")
        self.assertEqual(captured["REPO_OWNER"], "Sinless777")
        self.assertEqual(captured["REPO_NAME"], "PR-Creator")
        self.assertEqual(captured["REPO_BRANCH"], "feature/widget")
        self.assertEqual(captured["REPO_HEAD"], "abc123def")
        self.assertEqual(captured["OPENAI_MODEL"], "gpt-4o-mini")


if __name__ == "__main__":
    unittest.main()
