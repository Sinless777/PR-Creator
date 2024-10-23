#!/bin/bash

echo "========================================"
echo "Starting the application"
echo "========================================"

git config --global user.name "${GITHUB_ACTOR}"
git config --global user.email "${INPUT_EMAIL}"
git config --global --add safe.directory "/github/workspace"

echo "========================================"

python3 /app/main.py