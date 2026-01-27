import subprocess
import re
import sys
from src.core import config

def get_current_branch_issue_num():
    """現在のブランチ名からIssue番号らしき数字を抽出する"""
    try:
        res = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True, check=True)
        branch = res.stdout.strip()
        match = re.search(r'(\d+)', branch)
        return match.group(1) if match else None
    except Exception:
        return None

def get_git_diff(target_branch):
    """指定されたブランチとの差分を賢く取得する"""
    print(f"[INFO] Getting smart git diff against '{target_branch}'...", file=sys.stderr)
    
    exclude_patterns = config.EXCLUDE_PATTERNS
    
    try:
        stat_cmd = ["git", "diff", "--stat", target_branch, "--"] + [f":!{p}" for p in exclude_patterns]
        stat_res = subprocess.run(stat_cmd, capture_output=True, text=True)
        stat_output = stat_res.stdout
    except Exception:
        stat_output = "(Failed to get diff stats)"

    diff_cmd = ["git", "diff", target_branch, "--"] + [f":!{p}" for p in exclude_patterns]
    
    try:
        max_chars = config.MAX_DIFF_CHARS
        res = subprocess.run(diff_cmd, capture_output=True, text=True)
        diff_output = res.stdout
        
        if len(diff_output) > max_chars:
            print(f"[WARN] Diff is too large ({len(diff_output)} chars). Truncating...", file=sys.stderr)
            truncated_diff = diff_output[:max_chars]
            last_newline = truncated_diff.rfind('\n')
            if last_newline != -1:
                truncated_diff = truncated_diff[:last_newline]
            
            return f"""
[NOTE] The diff is too large. Showing file statistics and truncated changes.

Please read specific files if you need more context.

--- Statistics ---
{stat_output}

--- Truncated Diff ---
{truncated_diff}
... (truncated due to size limit)
"""
        else:
            return diff_output

    except Exception as e:
        print(f"[ERROR] Failed to get git diff: {{e}}", file=sys.stderr)
        return stat_output

def get_changed_files(target_branch):
    """変更されたファイルの一覧を取得する"""
    try:
        res = subprocess.run(
            ["git", "diff", "--name-only", target_branch],
            capture_output=True, text=True
        )
        return [f.strip() for f in res.stdout.strip().splitlines() if f.strip()]
    except Exception:
        return []
