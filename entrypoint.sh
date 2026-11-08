#!/bin/bash
set -euo pipefail

echo "========================================"
echo "Starting the application"
echo "========================================"

# GitHub Actions passes action inputs as INPUT_* environment variables.
# Map them onto the names main.py reads. Do not take secrets from argv.
export OPENAI_API_KEY="${INPUT_OPENAI_API_KEY:-${OPENAI_API_KEY:-}}"
export GITHUB_TOKEN="${INPUT_GITHUB_TOKEN:-${GITHUB_TOKEN:-}}"
export REPO_OWNER="${INPUT_REPOSITORY_OWNER:-${REPO_OWNER:-}}"

raw_repo="${INPUT_REPOSITORY:-${REPO_NAME:-}}"
if [[ "$raw_repo" == */* ]]; then
  export REPO_NAME="${raw_repo##*/}"
else
  export REPO_NAME="$raw_repo"
fi

branch="${INPUT_BRANCH:-${REPO_BRANCH:-}}"
branch="${branch#refs/heads/}"
export REPO_BRANCH="$branch"
export REPO_HEAD="${INPUT_HEAD:-${REPO_HEAD:-}}"
export OPENAI_MODEL="${INPUT_OPENAI_MODEL:-${OPENAI_MODEL:-gpt-4o-mini}}"

git config --global user.name "${GITHUB_ACTOR:-${INPUT_NAME:-pr-creator}}"
git config --global user.email "${INPUT_EMAIL:-${GITHUB_ACTOR:-pr-creator}@localhost}"
git config --global --add safe.directory "/github/workspace"

echo "========================================"

exec python3 /app/main.py
