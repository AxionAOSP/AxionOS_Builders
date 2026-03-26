import os
from github import Github, Auth
from dotenv import load_dotenv

# Load config
base_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(base_dir, 'private.env'))

token = os.environ.get("GITHUB_TOKEN")
repo_name = os.environ.get("GITHUB_REPO_NAME")

auth = Auth.Token(token)
g = Github(auth=auth)

try:
    repo = g.get_repo(repo_name)
    print(f"Checking failure for: {repo.full_name}")
    
    # Get the latest run
    runs = repo.get_workflow_runs()
    if runs.totalCount > 0:
        latest_run = runs[0]
        print(f"Run ID: {latest_run.id} | Status: {latest_run.status} | Conclusion: {latest_run.conclusion}")
        
        if latest_run.conclusion == "failure":
            print("\n--- Jobs in this run ---")
            jobs = latest_run.get_jobs()
            for job in jobs:
                print(f"Job: {job.name} | Conclusion: {job.conclusion}")
                if job.conclusion == "failure":
                    print("\n--- Job Steps ---")
                    for step in job.steps:
                        print(f"Step: {step.name} | Conclusion: {step.conclusion}")
    else:
        print("No runs found.")
        
except Exception as e:
    print(f"Error: {e}")
