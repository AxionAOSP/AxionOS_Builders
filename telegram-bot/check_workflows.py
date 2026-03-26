import os
from github import Github, Auth
from dotenv import load_dotenv

# Load config
base_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(base_dir, 'private.env'))

token = os.environ.get("GITHUB_TOKEN")
repo_name = os.environ.get("GITHUB_REPO_NAME")

print(f"Checking Repo: {repo_name}")

auth = Auth.Token(token)
g = Github(auth=auth)

try:
    repo = g.get_repo(repo_name)
    print(f"Connected to: {repo.full_name}")
    
    print("\n--- Listing Workflows ---")
    workflows = repo.get_workflows()
    found = False
    for wf in workflows:
        print(f"ID: {wf.id} | Name: {wf.name} | Path: {wf.path} | State: {wf.state}")
        found = True
    
    if not found:
        print("No workflows found in this repository.")
        
except Exception as e:
    print(f"Error: {e}")
