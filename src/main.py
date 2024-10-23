import openai
import os
import subprocess
import requests

# Load environment variables
def load_env_vars():
    env_vars = {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
        "GITHUB_TOKEN": os.getenv("GITHUB_TOKEN"),
        "REPO_OWNER": os.getenv("GITHUB_REPOSITORY_OWNER"),
        "REPO_NAME": os.getenv("GITHUB_REPOSITORY"),
        "REPO_BRANCH": os.getenv("GITHUB_REPOSITORY_BRANCH"),
        "REPO_HEAD": os.getenv("GITHUB_REPOSITORY_HEAD")
    }

    missing_vars = [var for var, value in env_vars.items() if value is None]
    if missing_vars:
        raise ValueError(f"Missing environment variables: {', '.join(missing_vars)}")
    
    return env_vars

# GitHub API request headers
def github_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json"
    }

# Get the latest commit message
def get_latest_commit_message():
    try:
        commit_message = subprocess.run(
            ["git", "log", "-1", "--pretty=%B"],
            check=True,
            stdout=subprocess.PIPE
        )
        return commit_message.stdout.decode("utf-8").strip()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to retrieve commit message: {e}")

# Check if there is an existing PR for the current branch
def check_for_existing_pr(repo_owner, repo_name, branch_name, token):
    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/pulls?head={repo_owner}:{branch_name}"
    response = requests.get(url, headers=github_headers(token))

    if response.status_code != 200:
        raise RuntimeError(f"Failed to check for existing PRs: {response.status_code} {response.text}")

    return response.json()

# Verify the commit message using commitlint
def verify_commit_message(commit_message):
    with open("commit_message.txt", "w") as f:
        f.write(commit_message)
    
    result = subprocess.run(
        ["npx", "commitlint", "--edit", "commit_message.txt"],
        stdout=subprocess.PIPE
    )

    return result

# Get the commit history (last 10 commits)
def get_commit_history():
    try:
        commit_history = subprocess.run(
            ["git", "log", "-10", "--pretty=%B"],
            check=True,
            stdout=subprocess.PIPE
        )
        return commit_history.stdout.decode("utf-8").strip()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to retrieve commit history: {e}")

# Generate PR title using OpenAI
def generate_pr_title(commit_message):
    response = openai.Completion.create(
        engine="text-davinci-003",
        prompt=f"Generate a PR title for the following commit message: '{commit_message}'",
        max_tokens=60,
        temperature=0.5
    )
    return response.choices[0].text.strip()

# Generate PR description using OpenAI
def generate_pr_description(commit_message, commit_history, pr_title):
    response = openai.Completion.create(
        engine="text-davinci-003",
        prompt=(
            f"Generate a PR description for the following commit message: '{commit_message}'\n"
            f"Commit history:\n{commit_history}\nPR title: '{pr_title}'"
        ),
        max_tokens=500,
        temperature=0.5
    )
    return response.choices[0].text.strip()

# Create a new PR
def create_pr(repo_owner, repo_name, pr_title, pr_body, repo_head, repo_branch, token):
    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/pulls"
    data = {
        "title": pr_title,
        "body": pr_body,
        "head": repo_head,
        "base": repo_branch
    }
    response = requests.post(url, headers=github_headers(token), json=data)

    if response.status_code != 201:
        raise RuntimeError(f"Failed to create PR: {response.status_code} {response.text}")

    return response.json()

# Add a comment to an existing PR
def add_comment_to_pr(repo_owner, repo_name, pr_number, comment, token):
    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/issues/{pr_number}/comments"
    data = {"body": comment}
    
    response = requests.post(url, headers=github_headers(token), json=data)

    if response.status_code != 201:
        raise RuntimeError(f"Failed to add comment: {response.status_code} {response.text}")

    return response.json()

# Generate a PR comment using OpenAI
def generate_pr_comment(pr_title, pr_description):
    response = openai.Completion.create(
        engine="text-davinci-003",
        prompt=f"Generate a comment for the following PR title: '{pr_title}'\n\nPR description:\n{pr_description}",
        max_tokens=200,
        temperature=0.5
    )
    return response.choices[0].text.strip()

# Main function
def main():
    # Load and validate environment variables
    env = load_env_vars()
    openai.api_key = env["OPENAI_API_KEY"]

    # Get latest commit message and verify it
    commit_message = get_latest_commit_message()
    print(f"Latest commit message: {commit_message}")

    result = verify_commit_message(commit_message)
    if result.returncode != 0:
        print("Invalid commit message. Please follow conventional commit standards.")
        return

    # Get the commit history
    commit_history = get_commit_history()
    
    # Generate PR title and description
    pr_title = generate_pr_title(commit_message)
    pr_description = generate_pr_description(commit_message, commit_history, pr_title)

    # Check for existing PR
    existing_pr = check_for_existing_pr(env["REPO_OWNER"], env["REPO_NAME"], env["REPO_BRANCH"], env["GITHUB_TOKEN"])

    if existing_pr:
        print("An existing PR was found.")
        pr_number = existing_pr[0]["number"]
        pr_comment = generate_pr_comment(pr_title, pr_description)
        add_comment_to_pr(env["REPO_OWNER"], env["REPO_NAME"], pr_number, pr_comment, env["GITHUB_TOKEN"])
        print(f"Comment added to PR #{pr_number}")
    else:
        pr_response = create_pr(env["REPO_OWNER"], env["REPO_NAME"], pr_title, pr_description, env["REPO_HEAD"], env["REPO_BRANCH"], env["GITHUB_TOKEN"])
        print(f"PR created successfully: {pr_response['html_url']}")

if __name__ == "__main__":
    main()
