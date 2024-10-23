import openai
import os
import subprocess
import requests
import time

# Load and validate environment variables
def load_env_vars():
    required_vars = [
        "OPENAI_API_KEY",
        "GITHUB_TOKEN",
        "REPO_OWNER",
        "REPO_NAME",
        "REPO_BRANCH",
        "REPO_HEAD"
    ]
    
    env_vars = {var: os.getenv(var) for var in required_vars}

    # Validate that all required environment variables are set
    missing_vars = [var for var, value in env_vars.items() if value is None]
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

    return env_vars

# GitHub API request headers
def github_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json"
    }

# Retry decorator to handle rate limits
def retry_request(func):
    def wrapper(*args, **kwargs):
        max_retries = 5
        for i in range(max_retries):
            try:
                return func(*args, **kwargs)
            except (requests.exceptions.RequestException, openai.error.RateLimitError) as e:
                if i < max_retries - 1:
                    time.sleep(2 ** i)  # Exponential backoff
                    print(f"Retrying due to error: {e}")
                else:
                    raise
    return wrapper

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
@retry_request
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

# Get the commit history with configurable limit
def get_commit_history(limit=10):
    try:
        commit_history = subprocess.run(
            ["git", "log", f"-{limit}", "--pretty=%B"],
            check=True,
            stdout=subprocess.PIPE
        )
        return commit_history.stdout.decode("utf-8").strip()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to retrieve commit history: {e}")

# Generate PR title using OpenAI with customizable options
@retry_request
def generate_pr_title(commit_message, temperature=0.5, max_tokens=60):
    if not commit_message:
        raise ValueError("Commit message cannot be empty.")
    
    response = openai.Completion.create(
        engine="text-davinci-003",
        prompt=f"Generate a PR title for the following commit message: '{commit_message}'",
        max_tokens=max_tokens,
        temperature=temperature
    )
    return response.choices[0].text.strip()

# Generate PR description using OpenAI with customizable options
@retry_request
def generate_pr_description(commit_message, commit_history, pr_title, temperature=0.5, max_tokens=500):
    if not commit_message or not pr_title:
        raise ValueError("Commit message and PR title are required to generate a PR description.")
    
    response = openai.Completion.create(
        engine="text-davinci-003",
        prompt=(
            f"Generate a PR description for the following commit message: '{commit_message}'\n"
            f"Commit history:\n{commit_history}\nPR title: '{pr_title}'"
        ),
        max_tokens=max_tokens,
        temperature=temperature
    )
    return response.choices[0].text.strip()

# Create a new PR
@retry_request
def create_pr(repo_owner, repo_name, pr_title, pr_body, repo_head, repo_branch, token):
    if not all([repo_owner, repo_name, pr_title, pr_body, repo_head, repo_branch]):
        raise ValueError("All fields (repo_owner, repo_name, pr_title, pr_body, repo_head, repo_branch) are required to create a PR.")
    
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
@retry_request
def add_comment_to_pr(repo_owner, repo_name, pr_number, comment, token):
    if not comment:
        raise ValueError("Comment text cannot be empty when adding a comment to a PR.")
    
    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/issues/{pr_number}/comments"
    data = {"body": comment}
    
    response = requests.post(url, headers=github_headers(token), json=data)

    if response.status_code != 201:
        raise RuntimeError(f"Failed to add comment: {response.status_code} {response.text}")

    return response.json()

# Generate a PR comment using OpenAI
@retry_request
def generate_pr_comment(pr_title, pr_description, temperature=0.5, max_tokens=200):
    if not pr_title or not pr_description:
        raise ValueError("PR title and description are required to generate a comment.")
    
    response = openai.Completion.create(
        engine="text-davinci-003",
        prompt=f"Generate a comment for the following PR title: '{pr_title}'\n\nPR description:\n{pr_description}",
        max_tokens=max_tokens,
        temperature=temperature
    )
    return response.choices[0].text.strip()

# Main function
def main():
    try:
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

        # Get the commit history with an optional limit
        commit_history = get_commit_history(limit=10)  # Adjust the limit as needed
        
        # Generate PR title and description with customizable OpenAI options
        pr_title = generate_pr_title(commit_message, temperature=0.5, max_tokens=60)
        pr_description = generate_pr_description(commit_message, commit_history, pr_title, temperature=0.5, max_tokens=500)

        # Check for existing PR
        existing_pr = check_for_existing_pr(env["REPO_OWNER"], env["REPO_NAME"], env["REPO_BRANCH"], env["GITHUB_TOKEN"])

        if existing_pr:
            print("An existing PR was found.")
            pr_number = existing_pr[0]["number"]
            pr_comment = generate_pr_comment(pr_title, pr_description, temperature=0.5, max_tokens=200)
            add_comment_to_pr(env["REPO_OWNER"], env["REPO_NAME"], pr_number, pr_comment, env["GITHUB_TOKEN"])
            print(f"Comment added to PR #{pr_number}")
        else:
            pr_response = create_pr(env["REPO_OWNER"], env["REPO_NAME"], pr_title, pr_description, env["REPO_HEAD"], env["REPO_BRANCH"], env["GITHUB_TOKEN"])
            print(f"PR created successfully: {pr_response['html_url']}")
    
    except ValueError as ve:
        print(f"Input validation error: {ve}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    main()
