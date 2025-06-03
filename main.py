from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from requests.auth import HTTPBasicAuth
import json
import os
import base64
from dotenv import load_dotenv
import boto3

load_dotenv()  # Load environment variables from .env

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# --- Jira Config ---
JIRA_URL = os.getenv('JIRA_URL')
JIRA_EMAIL = os.getenv('JIRA_EMAIL')
JIRA_API_TOKEN = os.getenv('JIRA_API_TOKEN')
JIRA_PROJECT_KEY = os.getenv('JIRA_PROJECT_KEY')

auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
jira_headers = {
    "Accept": "application/json",
    "Content-Type": "application/json"
}

# --- AWS Bedrock (Claude) Config ---
aws_key = os.getenv('AWS_ACCESS_KEY_ID')
aws_secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')
aws_region = os.getenv('AWS_REGION')

bedrock = boto3.client(
    'bedrock-runtime',
    aws_access_key_id=aws_key,
    aws_secret_access_key=aws_secret_key,
    region_name=aws_region
)

# --- GitHub Config ---
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')

# Helper to extract full Jira description text from ADF format
def extract_full_description(adf):
    texts = []
    def recurse_content(nodes):
        for node in nodes:
            if node.get('type') == 'text':
                texts.append(node.get('text', ''))
            if 'content' in node:
                recurse_content(node['content'])
    if adf and isinstance(adf, dict) and adf.get('type') == 'doc' and 'content' in adf:
        recurse_content(adf['content'])
    return ' '.join(texts)

def get_all_issues():
    url = f"{JIRA_URL}/rest/api/3/search"
    headers = {"Accept": "application/json"}
    query = {
        'jql': f'project={JIRA_PROJECT_KEY}',
        'maxResults': 100,
        'fields': 'summary,status,assignee,priority,issuetype,description,labels'
    }
    try:
        response = requests.get(url, headers=headers, params=query, auth=auth)
        if response.status_code != 200:
            print(f"Failed to fetch issues: {response.status_code} {response.text}")
            return []
        data = response.json()
        issues = data.get('issues', [])
        transformed_issues = []
        for issue in issues:
            fields = issue['fields']
            priority = fields.get('priority', {}).get('name', 'Medium') if fields.get('priority') else 'Medium'
            assignee = fields.get('assignee', {}).get('displayName', 'Unassigned') if fields.get('assignee') else 'Unassigned'
            description_adf = fields.get('description')
            description = extract_full_description(description_adf) if isinstance(description_adf, dict) else (description_adf or "")
            labels = fields.get('labels', [])
            transformed_issues.append({
                'id': issue['key'],
                'title': fields['summary'],
                'assignee': assignee,
                'status': fields['status']['name'],
                'priority': priority,
                'type': fields['issuetype']['name'],
                'description': description,
                'labels': labels
            })
        return transformed_issues
    except Exception as e:
        print(f"Error fetching issues: {str(e)}")
        return []

# --- Jira Endpoints ---

@app.route('/api/tickets', methods=['GET'])
def get_tickets():
    try:
        tickets = get_all_issues()
        return jsonify({'success': True, 'data': tickets, 'count': len(tickets)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'data': []}), 500

@app.route('/api/tickets/<ticket_id>', methods=['GET'])
def get_ticket_by_id(ticket_id):
    try:
        tickets = get_all_issues()
        ticket = next((t for t in tickets if t['id'] == ticket_id), None)
        if ticket:
            return jsonify({'success': True, 'data': ticket})
        else:
            return jsonify({'success': False, 'error': f'Ticket {ticket_id} not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'message': 'Flask Jira API is running'})

# --- Add Commit Comment to Jira Issue ---

def get_issue(issue_key):
    url = f"{JIRA_URL}/rest/api/3/issue/{issue_key}"
    response = requests.get(url, auth=auth, headers=jira_headers)
    if response.status_code == 200:
        return response.json()
    else:
        return None

def add_comment(issue_key, commit_message, commit_url=None):
    url = f"{JIRA_URL}/rest/api/3/issue/{issue_key}/comment"
    content = [
        {"type": "paragraph", "content": [{"type": "text", "text": "Commit Message:"}]},
        {"type": "paragraph", "content": [{"type": "text", "text": commit_message}]}
    ]
    if commit_url:
        content.append({
            "type": "paragraph",
            "content": [{
                "type": "text",
                "text": "View Commit in GitHub",
                "marks": [{"type": "link", "attrs": {"href": commit_url}}]
            }]
        })
    payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": content
        }
    }
    response = requests.post(url, auth=auth, headers=jira_headers, data=json.dumps(payload))
    response.raise_for_status()
    return response.json()

@app.route('/add-commit-comment', methods=['POST'])
def add_commit_comment():
    data = request.get_json()
    jira_ticket = data.get('jira_ticket')
    commit_message = data.get('commit_message')
    commit_url = data.get('commit_url', None)

    if not jira_ticket or not commit_message:
        return jsonify({
            "success": False,
            "error": "Missing required fields: jira_ticket and commit_message"
        }), 400

    issue = get_issue(jira_ticket)
    if not issue:
        return jsonify({
            "success": False,
            "error": f"Jira ticket {jira_ticket} not found"
        }), 404

    try:
        comment_response = add_comment(jira_ticket, commit_message, commit_url)
        return jsonify({"success": True, "comment": comment_response})
    except requests.HTTPError as e:
        return jsonify({"success": False, "error": f"Failed to add comment: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# --- Claude Code Generation Endpoint ---

@app.route("/generate_code", methods=["POST"])
def generate_code():
    data = request.json
    description = data.get("description")
    if not description:
        return jsonify({"error": "Missing 'description' in request body"}), 400

    prompt = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1000,
        "top_k": 250,
        "stop_sequences": ["\n\nHuman:"],
        "temperature": 0.0,
        "top_p": 0.999,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "\n\nHuman: Write clean, well-commented Javascript code **only**. "
                            "Do **not** include any explanations, descriptions, greetings, or text outside the code. "
                            "Return only the Python code, nothing else. "
                            f"Here is the description:\n{description}\n\nAssistant:"
                        ),
                    }
                ],
            }
        ],
    }


    try:
        response = bedrock.invoke_model(
            modelId="us.anthropic.claude-3-5-sonnet-20240620-v1:0",
            contentType="application/json",
            accept="application/json",
            body=json.dumps(prompt),
        )
        response_body = json.loads(response["body"].read().decode("utf-8"))
        content = response_body.get("content", [])
        generated_code = ""
        for item in content:
            if item.get("type") == "text":
                generated_code += item.get("text", "")
        generated_code = generated_code.strip()
        return jsonify({"code": generated_code})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- GitHub Integration ---

class GitHubClient:
    def __init__(self, token):
        self.token = token
        self.api_url = "https://api.github.com"
        self.headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json"
        }

    def list_repos(self):
        repos = []
        page = 1
        while True:
            url = f"{self.api_url}/user/repos?per_page=100&page={page}"
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            if not data:
                break
            repos.extend(data)
            page += 1
        return repos

    def get_user(self):
        url = f"{self.api_url}/user"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def get_file_sha(self, owner, repo, path):
        url = f"{self.api_url}/repos/{owner}/{repo}/contents/{path}"
        response = requests.get(url, headers=self.headers)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()['sha']

    def create_or_update_file(self, repo, path, content, message, branch="main"):
        user = self.get_user()
        owner = user['login']
        sha = self.get_file_sha(owner, repo, path)
        data = {
            "message": message,
            "content": base64.b64encode(content).decode(),
            "branch": branch
        }
        if sha:
            data['sha'] = sha

        url = f"{self.api_url}/repos/{owner}/{repo}/contents/{path}"
        response = requests.put(url, headers=self.headers, data=json.dumps(data))
        response.raise_for_status()
        return response.json()

client = GitHubClient(GITHUB_TOKEN)

@app.route('/repos', methods=['GET'])
def get_repos():
    try:
        repos = client.list_repos()
        repo_names = [repo['name'] for repo in repos]
        return jsonify({"success": True, "repos": repo_names, "count": len(repo_names)})
    except requests.HTTPError as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/push-file', methods=['POST'])
def push_file():
    try:
        repo = request.form.get('repo')
        file_path = request.form.get('file_path')
        commit_message = request.form.get('commit_message', f"Add/update {file_path}")
        file = request.files.get('file')

        if not all([repo, file_path, file]):
            return jsonify({"success": False, "error": "Missing repo, file_path or file"}), 400

        file_content = file.read()
        result = client.create_or_update_file(repo, file_path, file_content, commit_message)
        return jsonify({"success": True, "result": result})

    except requests.HTTPError as e:
        return jsonify({"success": False, "error": str(e)}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    
    
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5007))
    print("Starting Flask server...")
    print("Available endpoints:")
    print("- GET /api/tickets - Fetch all Jira tickets")
    print("- GET /api/tickets/<ticket_id> - Fetch ticket by ID")
    print("- GET /api/health - Health check")
    print("- POST /api/generate_code - Generate Python code from description")
    print("- GET /repos - List GitHub repositories")
    print("- POST /push-file - Create or update a file in GitHub repo")
    print("- POST /add-commit-comment - Add commit comment to Jira issue")
    app.run(debug=True, host='0.0.0.0', port=port)
