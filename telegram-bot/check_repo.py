import os
from github import Github, Auth
from dotenv import load_dotenv

base_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(base_dir, 'private.env'))

token = os.environ.get("GITHUB_TOKEN")
repo_name = os.environ.get("GITHUB_REPO_NAME")

auth = Auth.Token(token)
g = Github(auth=auth)

try:
    repo = g.get_repo(repo_name)
    print(f"Repo: {repo.full_name}")
    print(f"Default Branch: {repo.default_branch}")
    
    print("\n--- Files in .github/workflows ---")
    try:
        contents = repo.get_contents(".github/workflows", ref="actions")
        for content_file in contents:
            print(f"- {content_file.path}")
    except Exception as e:
        print(f"Error accessing path: {e}")
        
except Exception as e:
    print(f"Error: {e}")
