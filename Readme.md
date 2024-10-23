# PR Creator with OpenAI

Automatically create a Pull Request (PR) with OpenAI-generated content when code is pushed to a branch without an existing PR. This GitHub Action uses Python and Bash to automate the PR creation process, including generating PR titles, descriptions, and comments using OpenAI's GPT-3 language model.

## Table of Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Usage](#usage)
  - [Inputs](#inputs)
  - [Example Workflow](#example-workflow)
- [Setup Instructions](#setup-instructions)
  - [OpenAI API Key](#openai-api-key)
  - [GitHub Token](#github-token)
- [Customization](#customization)
- [Error Handling](#error-handling)
- [Development](#development)
  - [Local Testing](#local-testing)
  - [Building the Docker Image](#building-the-docker-image)
- [Contributing](#contributing)
- [License](#license)
- [Acknowledgements](#acknowledgements)

## Features

- **Automatic PR Creation**: Creates a PR when code is pushed to a branch without an existing PR.
- **OpenAI Integration**: Generates PR titles, descriptions, and comments using GPT-3.
- **Commit Message Validation**: Validates commit messages against conventional commit standards using `commitlint`.
- **Rate Limit Handling**: Implements retries with exponential backoff to handle API rate limits gracefully.
- **Customizable Parameters**: Allows customization of OpenAI parameters and commit history length.
- **Robust Error Handling**: Provides detailed input validation and error messages.

## Prerequisites

- A GitHub repository where the action will be used.
- An OpenAI API Key.
- A GitHub Token with appropriate permissions (usually `${{ secrets.GITHUB_TOKEN }}` is sufficient).

## Usage

### Inputs

- `openai_api_key` (required): Your OpenAI API key for generating PR information.
- `github_token` (required): GitHub token for accessing the repository and making API calls.
- `repository_owner` (required): GitHub repository owner (username or organization).
- `repository` (required): GitHub repository name.
- `branch` (required): Branch name to create the PR for.
- `head` (required): Commit SHA for the head of the branch.

### Example Workflow

Create a workflow file (e.g., `.github/workflows/pr-creator.yml`) in your repository:

```yaml
name: PR Creator

on:
  push:
    branches:
      - '**'

jobs:
  create_pr:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: PR Creator with OpenAI
        uses: Sinless777/PR-Creator@v1
        with:
          openai_api_key: ${{ secrets.OPENAI_API_KEY }}
          github_token: ${{ secrets.GITHUB_TOKEN }}
          repository_owner: ${{ github.repository_owner }}
          repository: ${{ github.event.repository.name }}
          branch: ${{ github.ref_name }}
          head: ${{ github.sha }}
```

## Setup Instructions

### OpenAI API Key

1. Sign up at [OpenAI](https://beta.openai.com/signup/).
2. Navigate to the [API Keys](https://platform.openai.com/account/api-keys) section.
3. Create a new API key.
4. Add the API key to your repository's secrets:
   - Go to **Settings** > **Secrets and variables** > **Actions**.
   - Click **New repository secret**.
   - Name it `OPENAI_API_KEY` and paste your API key.

### GitHub Token

- The `${{ secrets.GITHUB_TOKEN }}` is automatically provided by GitHub Actions.
- No additional setup is required unless custom permissions are needed.

## Customization

You can customize the behavior by adjusting parameters in `main.py` or via action inputs:

- **OpenAI Parameters**:
  - `temperature`: Controls randomness (range 0 to 1). Lower values make output more deterministic.
  - `max_tokens`: Maximum number of tokens to generate.
- **Commit History Length**:
  - Adjust the `limit` parameter in the `get_commit_history(limit=10)` function.

## Error Handling

The script includes robust error handling:

- **Input Validation**: Checks for missing environment variables and required inputs.
- **API Rate Limits**: Implements retries with exponential backoff for API calls.
- **Exception Handling**: Catches and logs exceptions without exposing sensitive information.

## Development

### Local Testing

1. **Clone the Repository**:

   ```bash
   git clone https://github.com/Sinless777/PR-Creator.git
   cd PR-Creator
   ```

2. **Install Dependencies**:

   ```bash
   pip install -r requirements.txt
   ```

3. **Set Environment Variables**:

   ```bash
   export OPENAI_API_KEY=your_openai_api_key
   export GITHUB_TOKEN=your_github_token
   export REPO_OWNER=your_repo_owner
   export REPO_NAME=your_repo_name
   export REPO_BRANCH=your_branch_name
   export REPO_HEAD=your_commit_sha
   ```

4. **Run the Script**:

   ```bash
   python main.py
   ```

### Building the Docker Image

If you need to build the Docker image locally:

```bash
docker build -t pr-creator .
```

### Running the Docker Container

```bash
docker run --rm \
  -e OPENAI_API_KEY=your_openai_api_key \
  -e GITHUB_TOKEN=your_github_token \
  -e REPO_OWNER=your_repo_owner \
  -e REPO_NAME=your_repo_name \
  -e REPO_BRANCH=your_branch_name \
  -e REPO_HEAD=your_commit_sha \
  pr-creator
```

## Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository.
2. Create a new branch (`git checkout -b feature/your-feature`).
3. Commit your changes (`git commit -m 'Add your feature'`).
4. Push to the branch (`git push origin feature/your-feature`).
5. Open a Pull Request.

## License

This project is licensed under the [MIT License](LICENSE).

## Acknowledgements

- [OpenAI](https://openai.com/) for the GPT-3 language model.
- [GitHub Actions](https://github.com/features/actions) for automation.
- [commitlint](https://commitlint.js.org/) for commit message linting.
- [Requests](https://requests.readthedocs.io/en/latest/) library for HTTP requests.