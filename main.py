import os
import re
import subprocess
import sys
import tempfile
import time

import requests
from openai import OpenAI, RateLimitError

GITHUB_API = "https://api.github.com"
DEFAULT_MODEL = "gpt-4o-mini"
_GITHUB_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,99}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,249}$")


def load_env_vars():
    required_vars = [
        "OPENAI_API_KEY",
        "GITHUB_TOKEN",
        "REPO_OWNER",
        "REPO_NAME",
        "REPO_BRANCH",
        "REPO_HEAD",
    ]

    env_vars = {var: os.getenv(var) for var in required_vars}
    missing_vars = [
        var
        for var, value in env_vars.items()
        if value is None or not str(value).strip()
    ]
    if missing_vars:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing_vars)}"
        )

    return env_vars


def require_github_name(value, label):
    if not isinstance(value, str) or not _GITHUB_NAME.fullmatch(value) or ".." in value:
        raise ValueError(f"Invalid {label}")
    return value


def normalize_ref(value, label):
    if not isinstance(value, str):
        raise ValueError(f"Invalid {label}")
    if value.startswith("refs/heads/"):
        value = value[len("refs/heads/") :]
    if not _REF.fullmatch(value) or ".." in value:
        raise ValueError(f"Invalid {label}")
    return value


def github_session(token):
    session = requests.Session()
    # Never consult netrc or proxy environment variables. The action always
    # sends an explicit bearer token.
    session.trust_env = False
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )
    return session


def retry_request(func):
    def wrapper(*args, **kwargs):
        max_retries = 5
        for i in range(max_retries):
            try:
                return func(*args, **kwargs)
            except (requests.exceptions.RequestException, RateLimitError) as e:
                if i < max_retries - 1:
                    time.sleep(2**i)
                    print(f"Retrying due to error: {e}")
                else:
                    raise

    return wrapper


def get_latest_commit_message():
    try:
        commit_message = subprocess.run(
            ["git", "log", "-1", "--pretty=%B"],
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        return commit_message.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to retrieve commit message: {e}") from e


def verify_commit_message(commit_message):
    """Lint with the Python commitlint package declared in requirements.txt."""
    fd, path = tempfile.mkstemp(prefix="commit-msg-", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(commit_message)
            if not commit_message.endswith("\n"):
                handle.write("\n")
        return subprocess.run(
            ["commitlint", "--file", path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def get_commit_history(limit=10):
    try:
        commit_history = subprocess.run(
            ["git", "log", f"-{int(limit)}", "--pretty=%B"],
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        return commit_history.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to retrieve commit history: {e}") from e


def build_openai_client(api_key):
    return OpenAI(api_key=api_key)


def _completion_text(response):
    content = response.choices[0].message.content
    if content is None or not content.strip():
        raise RuntimeError("OpenAI returned an empty completion")
    return content.strip()


def _chat(client, prompt, temperature, max_tokens):
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return _completion_text(response)


@retry_request
def generate_pr_title(client, commit_message, temperature=0.5, max_tokens=60):
    if not commit_message:
        raise ValueError("Commit message cannot be empty.")
    return _chat(
        client,
        "Generate a pull request title for the following commit message. "
        f"Reply with the title only.\n\n{commit_message}",
        temperature,
        max_tokens,
    )


@retry_request
def generate_pr_description(
    client, commit_message, commit_history, pr_title, temperature=0.5, max_tokens=500
):
    if not commit_message or not pr_title:
        raise ValueError(
            "Commit message and PR title are required to generate a PR description."
        )
    return _chat(
        client,
        "Generate a pull request description for the following commit message.\n"
        f"Commit message: {commit_message}\n"
        f"Commit history:\n{commit_history}\n"
        f"PR title: {pr_title}",
        temperature,
        max_tokens,
    )


@retry_request
def check_for_existing_pr(
    repo_owner, repo_name, branch_name, token, session=None, api_base=GITHUB_API
):
    repo_owner = require_github_name(repo_owner, "repository owner")
    repo_name = require_github_name(repo_name, "repository name")
    branch_name = normalize_ref(branch_name, "branch name")
    session = session or github_session(token)
    response = session.get(
        f"{api_base}/repos/{repo_owner}/{repo_name}/pulls",
        params={"head": f"{repo_owner}:{branch_name}"},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to check for existing PRs: {response.status_code} {response.text}"
        )
    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError("GitHub pulls response was not a list")
    return payload


@retry_request
def create_pr(
    repo_owner,
    repo_name,
    pr_title,
    pr_body,
    repo_head,
    repo_branch,
    token,
    session=None,
    api_base=GITHUB_API,
):
    if not all([repo_owner, repo_name, pr_title, pr_body, repo_head, repo_branch]):
        raise ValueError(
            "All fields (repo_owner, repo_name, pr_title, pr_body, repo_head, repo_branch) are required to create a PR."
        )
    repo_owner = require_github_name(repo_owner, "repository owner")
    repo_name = require_github_name(repo_name, "repository name")
    repo_head = normalize_ref(repo_head, "head ref")
    repo_branch = normalize_ref(repo_branch, "base branch")
    session = session or github_session(token)
    response = session.post(
        f"{api_base}/repos/{repo_owner}/{repo_name}/pulls",
        json={
            "title": pr_title,
            "body": pr_body,
            "head": repo_head,
            "base": repo_branch,
        },
        timeout=30,
    )
    if response.status_code != 201:
        raise RuntimeError(f"Failed to create PR: {response.status_code} {response.text}")
    return response.json()


@retry_request
def add_comment_to_pr(
    repo_owner,
    repo_name,
    pr_number,
    comment,
    token,
    session=None,
    api_base=GITHUB_API,
):
    if not comment:
        raise ValueError("Comment text cannot be empty when adding a comment to a PR.")
    repo_owner = require_github_name(repo_owner, "repository owner")
    repo_name = require_github_name(repo_name, "repository name")
    session = session or github_session(token)
    response = session.post(
        f"{api_base}/repos/{repo_owner}/{repo_name}/issues/{int(pr_number)}/comments",
        json={"body": comment},
        timeout=30,
    )
    if response.status_code != 201:
        raise RuntimeError(
            f"Failed to add comment: {response.status_code} {response.text}"
        )
    return response.json()


@retry_request
def generate_pr_comment(client, pr_title, pr_description, temperature=0.5, max_tokens=200):
    if not pr_title or not pr_description:
        raise ValueError("PR title and description are required to generate a comment.")
    return _chat(
        client,
        "Generate a pull request comment for the following PR title and description. "
        f"Reply with the comment only.\n\nTitle: {pr_title}\n\nDescription:\n{pr_description}",
        temperature,
        max_tokens,
    )


def main():
    try:
        env = load_env_vars()

        commit_message = get_latest_commit_message()
        print(f"Latest commit message: {commit_message}")

        result = verify_commit_message(commit_message)
        if result.returncode != 0:
            print("Invalid commit message. Please follow conventional commit standards.")
            detail = (result.stderr or result.stdout or "").strip()
            if detail:
                print(detail)
            return 1

        client = build_openai_client(env["OPENAI_API_KEY"])
        commit_history = get_commit_history(limit=10)
        pr_title = generate_pr_title(client, commit_message, temperature=0.5, max_tokens=60)
        pr_description = generate_pr_description(
            client,
            commit_message,
            commit_history,
            pr_title,
            temperature=0.5,
            max_tokens=500,
        )

        session = github_session(env["GITHUB_TOKEN"])
        existing_pr = check_for_existing_pr(
            env["REPO_OWNER"],
            env["REPO_NAME"],
            env["REPO_BRANCH"],
            env["GITHUB_TOKEN"],
            session=session,
        )

        if existing_pr:
            print("An existing PR was found.")
            pr_number = existing_pr[0]["number"]
            pr_comment = generate_pr_comment(
                client, pr_title, pr_description, temperature=0.5, max_tokens=200
            )
            add_comment_to_pr(
                env["REPO_OWNER"],
                env["REPO_NAME"],
                pr_number,
                pr_comment,
                env["GITHUB_TOKEN"],
                session=session,
            )
            print(f"Comment added to PR #{pr_number}")
        else:
            pr_response = create_pr(
                env["REPO_OWNER"],
                env["REPO_NAME"],
                pr_title,
                pr_description,
                env["REPO_HEAD"],
                env["REPO_BRANCH"],
                env["GITHUB_TOKEN"],
                session=session,
            )
            print(f"PR created successfully: {pr_response['html_url']}")
        return 0
    except ValueError as ve:
        print(f"Input validation error: {ve}")
        return 1
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
