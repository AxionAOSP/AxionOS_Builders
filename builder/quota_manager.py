#!/usr/bin/env python3
import os, sys, json
from datetime import datetime, timezone
from github import Github, Auth

def main():
    if len(sys.argv) < 3: sys.exit(1)
    user_id, username = sys.argv[1], sys.argv[2]
    is_full_clean = sys.argv[3] if len(sys.argv) > 3 else "No"

    token = os.environ.get("GITHUB_TOKEN")
    repo_name = os.environ.get("GITHUB_REPO_NAME")
    branch = os.environ.get("GITHUB_BRANCH") or os.environ.get("GITHUB_REF_NAME") or "actions"
    if branch.startswith("refs/heads/"): branch = branch.replace("refs/heads/", "")

    try:
        g = Github(auth=Auth.Token(token))
        repo = g.get_repo(repo_name)
        file_content = repo.get_contents("database.json", ref=branch)
        db = json.loads(file_content.decoded_content.decode())

        if user_id not in db["users"]: sys.exit(0)
        user_data = db["users"][user_id]
        role = user_data.get("role", "user")

        if is_full_clean == "Yes" and role not in ["admin", "owner"]:
            print("⛔ Security Alert: Full Clean restricted to Admins.")
            sys.exit(1)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        count = user_data.get("daily_count", 0) if user_data.get("last_build_date") == today else 0
        limit = user_data.get("daily_limit", 3)

        if role not in ["admin", "owner"] and count >= limit:
            with open(".quota_exceeded", "w") as f: f.write("True")
            print(f"❌ Quota exceeded for {username}.")
            sys.exit(1)

        user_data.update({"daily_count": count + 1, "last_build_date": today, "username": username})
        
        bot_identity = {"name": "github-actions[bot]", "email": "41898282+github-actions[bot]@users.noreply.github.com"}
        
        repo.update_file(
            "database.json", 
            f"quota: Update build quota for {username}", 
            json.dumps(db, indent=2), 
            file_content.sha, 
            branch=branch,
            committer=bot_identity,
            author=bot_identity
        )
        print(f"✅ Quota updated for {username} ({count+1}/{limit})")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__": main()
