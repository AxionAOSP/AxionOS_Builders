#!/usr/bin/env python3
import os, sys, json
from datetime import datetime, timezone
from github import Github, Auth, InputGitAuthor, GithubException

def main():
    if len(sys.argv) < 3:
        print("Usage: quota_manager.py <user_id> <username> [is_full_clean]")
        sys.exit(1)
        
    user_id, username = str(sys.argv[1]), sys.argv[2]
    is_full_clean = sys.argv[3] if len(sys.argv) > 3 else "No"

    token = os.environ.get("GITHUB_TOKEN")
    repo_name = os.environ.get("GITHUB_REPO_NAME")
    branch = os.environ.get("GITHUB_BRANCH") or os.environ.get("GITHUB_REF_NAME") or "actions"
    
    if not token:
        print("Error: GITHUB_TOKEN is not set.")
        sys.exit(1)
    if not repo_name:
        print("Error: GITHUB_REPO_NAME is not set.")
        sys.exit(1)

    if branch.startswith("refs/heads/"):
        branch = branch.replace("refs/heads/", "")

    try:
        print(f"Connecting to GitHub: {repo_name} (Branch: {branch})")
        g = Github(auth=Auth.Token(token))
        repo = g.get_repo(repo_name)
        
        print(f"Fetching database.json from {branch}...")
        try:
            file_content = repo.get_contents("database.json", ref=branch)
        except GithubException as e:
            if e.status == 404:
                print(f"Error: database.json not found on branch {branch}.")
            raise

        db = json.loads(file_content.decoded_content.decode())
        
        if user_id not in db.get("users", {}):
            print(f"User {user_id} not in database. Skipping quota check.")
            sys.exit(0)
            
        user_data = db["users"][user_id]
        role = user_data.get("role", "user")
        
        print(f"User: {username} (ID: {user_id}, Role: {role})")

        if is_full_clean == "Yes" and role not in ["admin", "owner"]:
            print("⛔ Security Alert: Full Clean restricted to Admins.")
            sys.exit(1)

        # Quota resets at 7:00 AM IST (01:30 UTC).
        # We subtract 1h 30m from UTC time so that the "quota day" 
        # changes at exactly 01:30 UTC.
        from datetime import timedelta
        ist_reset_offset = timedelta(hours=1, minutes=30)
        quota_now = datetime.now(timezone.utc) - ist_reset_offset
        today = quota_now.strftime("%Y-%m-%d")
        
        last_date = user_data.get("last_build_date", "")
        
        if last_date == today:
            count = user_data.get("daily_count", 0)
        else:
            count = 0
            
        limit = user_data.get("daily_limit", 3)

        if role not in ["admin", "owner"] and count >= limit:
            with open(".quota_exceeded", "w") as f:
                f.write("True")
            print(f"❌ Quota exceeded for {username} ({count}/{limit}).")
            sys.exit(1)

        # Update data
        user_data["daily_count"] = count + 1
        user_data["last_build_date"] = today
        user_data["username"] = username
        
        print(f"Updating quota: {count+1}/{limit}")
        
        author = InputGitAuthor(
            "github-actions[bot]", 
            "41898282+github-actions[bot]@users.noreply.github.com"
        )
        
        repo.update_file(
            "database.json", 
            f"quota: Update build quota for {username}", 
            json.dumps(db, indent=2), 
            file_content.sha, 
            branch=branch,
            committer=author,
            author=author
        )
        print(f"✅ Quota updated for {username} ({count+1}/{limit})")

    except GithubException as e:
        print(f"GitHub Error ({e.status}): {e.data}")
        sys.exit(1)
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
