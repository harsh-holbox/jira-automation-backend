# Jira, GitHub & AWS Bedrock Flask API

This Flask application provides APIs to interact with Jira tickets, GitHub repositories, and AWS Bedrock (Claude) for code generation.

## Features

- Fetch Jira tickets and ticket details
- Add commit comments to Jira issues (supports commit message and GitHub commit URL)
- List GitHub repositories of the authenticated user
- Create or update files in GitHub repositories
- Generate Python code from natural language descriptions using AWS Bedrock Claude model
- Health check endpoint

## Setup

1. Clone the repository.

2. Create a `.env` file in the root directory with the following variables:

```

JIRA\_URL=[https://your-domain.atlassian.net](https://your-domain.atlassian.net)
JIRA\_EMAIL=[your-email@example.com](mailto:your-email@example.com)
JIRA\_API\_TOKEN=your-jira-api-token
JIRA\_PROJECT\_KEY=YOURPROJECTKEY
AWS\_ACCESS\_KEY\_ID=your-aws-access-key-id
AWS\_SECRET\_ACCESS\_KEY=your-aws-secret-access-key
AWS\_REGION=your-aws-region
GITHUB\_TOKEN=your-github-personal-access-token

````

3. Install dependencies:

```bash
pip install -r requirements.txt
````

4. Run the Flask app:

   ```bash
   python app.py
   ```

   The server will start on `http://0.0.0.0:5007`

## API Endpoints

### Jira

* `GET /api/tickets` - Get all Jira tickets for the configured project
* `GET /api/tickets/<ticket_id>` - Get details for a specific Jira ticket
* `POST /add-commit-comment` - Add a commit comment to a Jira ticket
  **Request JSON:**

  ```json
  {
    "jira_ticket": "PROJ-123",
    "commit_message": "Fixed bug in authentication",
    "commit_url": "https://github.com/yourorg/yourrepo/commit/abc123"  // optional
  }
  ```

### GitHub

* `GET /repos` - List all GitHub repositories for the authenticated user
* `POST /push-file` - Create or update a file in a GitHub repository
  **Form Data:**

  * `repo` (string): GitHub repo name
  * `file_path` (string): Path in repo (e.g. `src/app.py`)
  * `commit_message` (string, optional): Commit message
  * `file` (file): The file to upload

### AWS Bedrock (Claude)

* `POST /api/generate_code` - Generate Python code from a natural language description
  **Request JSON:**

  ```json
  {
    "description": "Write a function that sums two numbers"
  }
  ```

### Health Check

* `GET /api/health` - Check if API is running

## Notes

* Ensure all environment variables are properly set in your `.env` file.
* The GitHub token must have repo permissions to list repos and push files.
* AWS credentials should have access to Bedrock services.
