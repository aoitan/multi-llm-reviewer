import subprocess
import json
import sys

def fetch_issue(issue_num):
    """ghコマンドを使ってIssueのタイトルと本文を取得する"""
    print(f"[INFO] Fetching Issue #{issue_num}...", file=sys.stderr)
    try:
        res = subprocess.run(
            ["gh", "issue", "view", str(issue_num), "--json", "title,body"],
            capture_output=True, text=True, check=True
        )
        data = json.loads(res.stdout)
        title = data.get("title", "(No Title)")
        body = data.get("body", "(No Body)")
        return f"Title: {title}\n\nBody:\n{body}"
    except Exception:
        print(f"[WARN] Failed to fetch issue #{issue_num}.", file=sys.stderr)
        return None
