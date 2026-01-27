#!/usr/bin/env python3
import argparse
import subprocess
import sys
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 設定 ---
# 各レビュアー枠ごとのフォールバック設定
REVIEWER_SLOTS = [
    {
        "name": "Gemini",
        "cmds": [
            ["gemini", "-m", "gemini-3-pro-preview", "--yolo"],
            ["gemini", "-m", "gemini-2.5-pro", "--yolo"],
            ["gemini", "-m", "gemini-3-flash-preview", "--yolo"],
            ["gemini", "-m", "gemini-2.5-flash", "--yolo"]
        ]
    },
    {
        "name": "Copilot",
        "cmds": [
            ["copilot", "--allow-all-tools"]
        ]
    },
    {
        "name": "Codex",
        "cmds": [
            ["codex", "exec", "--full-auto"],
            ["codex", "exec", "--full-auto", "-m", "gpt-5.1-codex-mini"]
        ]
    }
]

# 重要とみなすファイルパスのキーワード（これらが含まれるファイルが変更されたらALLモード）
CRITICAL_PATH_KEYWORDS = [
    "core", "auth", "security", "config", "infra", "database", "model", "api", 
    "login", "guard", "project.toml", "package.json", "requirements.txt",
    "docker", "k8s", "terraform", "pipeline", "workflow"
]

def get_current_branch_issue_num():
    """現在のブランチ名からIssue番号らしき数字を抽出する"""
    try:
        res = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True, check=True)
        branch = res.stdout.strip()
        match = re.search(r'(\d+)', branch)
        return match.group(1) if match else None
    except subprocess.CalledProcessError:
        return None

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

def get_git_diff(target_branch):
    """指定されたブランチとの差分を賢く取得する"""
    print(f"[INFO] Getting smart git diff against '{target_branch}'...", file=sys.stderr)
    
    exclude_patterns = [
        "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock", "uv.lock",
        "*.min.js", "*.min.css", "*.map", "*.svg", "*.png", "*.jpg", "*.jpeg", "*.gif", "*.ico",
        "dist/*", "build/*", ".next/*", "node_modules/*", "__pycache__/*"
    ]
    
    try:
        stat_cmd = ["git", "diff", "--stat", target_branch, "--"] + [f":!{p}" for p in exclude_patterns]
        stat_res = subprocess.run(stat_cmd, capture_output=True, text=True)
        stat_output = stat_res.stdout
    except Exception:
        stat_output = "(Failed to get diff stats)"

    diff_cmd = ["git", "diff", target_branch, "--"] + [f":!{p}" for p in exclude_patterns]
    
    try:
        MAX_CHARS = 100000
        res = subprocess.run(diff_cmd, capture_output=True, text=True)
        diff_output = res.stdout
        
        if len(diff_output) > MAX_CHARS:
            print(f"[WARN] Diff is too large ({len(diff_output)} chars). Truncating...", file=sys.stderr)
            truncated_diff = diff_output[:MAX_CHARS]
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
        print(f"[ERROR] Failed to get git diff: {e}", file=sys.stderr)
        return stat_output

def is_rate_limit(text):
    """出力テキストからレートリミットエラーを検知する"""
    keywords = [
        "rate limit", "429", "too many requests", "quota exceeded", 
        "rate_limit", "usage_limit_reached", "usage limit", "hit your usage limit",
        "exhausted your capacity", "exhausted", "quota will reset"
    ]
    return any(kw in text.lower() for kw in keywords)

def run_reviewer(slot, prompt):
    """1つのレビュアー枠（Slot）に対して、フォールバックを含めて実行する"""
    name = slot["name"]
    cmds = slot["cmds"]
    last_res = None
    
    for i, cmd in enumerate(cmds):
        model_name = " ".join(cmd)
        try:
            # プロンプトを stdin から渡す
            res = subprocess.run(cmd, input=prompt, capture_output=True, text=True)
            full_output = res.stdout + res.stderr
            
            if res.returncode == 0:
                return {
                    "name": f"{name} ({model_name})" if len(cmds) > 1 else name,
                    "stdout": res.stdout,
                    "stderr": res.stderr,
                    "success": True
                }
            
            if is_rate_limit(full_output):
                print(f"[WARN] {name} ({model_name}) hit rate limit.", file=sys.stderr)
                last_res = {
                    "name": f"{name} ({model_name})",
                    "stdout": res.stdout,
                    "stderr": res.stderr,
                    "success": False
                }
                if i < len(cmds) - 1:
                    print(f"[INFO] Falling back to next model for {name}...", file=sys.stderr)
                    continue
                else:
                    break
            
            return {
                "name": f"{name} ({model_name})",
                "stdout": res.stdout,
                "stderr": res.stderr,
                "success": False
            }
            
        except Exception as e:
            last_res = {
                "name": name,
                "stdout": "",
                "stderr": str(e),
                "success": False
            }
            if i < len(cmds) - 1:
                continue
            break

    return last_res

def decide_reviewers(target_branch, mode_arg):
    """レビューモードに基づいて実行するレビュアーリストを決定する"""
    
    # "all" 指定
    if mode_arg.lower() == "all":
        return REVIEWER_SLOTS, "User forced ALL"

    # カンマ区切り指定 (例: "gemini,codex")
    if mode_arg.lower() not in ["auto", "single"]:
        targets = [t.strip().lower() for t in mode_arg.split(",")]
        selected = [s for s in REVIEWER_SLOTS if s["name"].lower() in targets]
        if selected:
            return selected, f"User selected: {mode_arg}"
    
    # Auto / Single モードの判定
    print(f"[INFO] Analyzing changes against '{target_branch}'...", file=sys.stderr)
    try:
        # ファイル名一覧のみ取得
        res = subprocess.run(
            ["git", "diff", "--name-only", target_branch],
            capture_output=True, text=True
        )
        files = [f.strip() for f in res.stdout.strip().splitlines() if f.strip()]
    except Exception:
        files = []

    reason = "Default (Single)"
    should_be_all = False
    
    # 判定1: 変更ファイル数が多い (>= 5)
    if len(files) >= 5:
        should_be_all = True
        reason = f"Large changeset ({len(files)} files)"
    
    # 判定2: 重要ファイルが含まれる
    if not should_be_all:
        for f in files:
            for kw in CRITICAL_PATH_KEYWORDS:
                if kw in f.lower():
                    should_be_all = True
                    reason = f"Critical file changed ({f})"
                    break
            if should_be_all:
                break
    
    # モード決定
    if mode_arg.lower() == "auto":
        if should_be_all:
            return REVIEWER_SLOTS, f"Auto: ALL ({reason})"
        else:
            # Codexのみ (デフォルトのSingleレビュアー)
            codex = next((s for s in REVIEWER_SLOTS if s["name"] == "Codex"), REVIEWER_SLOTS[0])
            return [codex], f"Auto: Single ({reason})"
            
    elif mode_arg.lower() == "single":
        # 条件に関わらずCodex (または先頭)
        codex = next((s for s in REVIEWER_SLOTS if s["name"] == "Codex"), REVIEWER_SLOTS[0])
        return [codex], "User forced Single"
        
    return REVIEWER_SLOTS, "Unknown mode, defaulting to ALL"

def main():
    parser = argparse.ArgumentParser(description="Multi-LLM Code Reviewer")
    parser.add_argument("spec", nargs="*", help="Additional specification text")
    parser.add_argument("-i", "--issue", help="Issue number")
    parser.add_argument("-b", "--base", default="main", help="Base branch for comparison")
    parser.add_argument("--reviewers", default="auto", help="Review mode: 'auto', 'all', 'single', or comma-separated names (e.g. 'gemini,codex')")
    
    args = parser.parse_args()

    issue_num = args.issue or get_current_branch_issue_num()
    issue_context = ""
    if issue_num:
        issue_body = fetch_issue(issue_num)
        if issue_body:
            issue_context = f"\n--------------------------------------------------\n【関連Issue情報 (Issue #{issue_num})】\n{issue_body}\n--------------------------------------------------\n"

    target_branch = args.base
    
    # レビュアー決定
    selected_slots, decision_log = decide_reviewers(target_branch, args.reviewers)
    print(f"[INFO] Review Mode: {decision_log}", file=sys.stderr)

    diff_text = get_git_diff(target_branch)
    diff_context = f"\n--------------------------------------------------\n【変更差分 (Diff)】\n{diff_text}\n--------------------------------------------------\n" if diff_text.strip() else "(No changes detected)"

    spec_text = " ".join(args.spec)
    prompt = f"""あなたは熟練のソフトウェアエンジニアでありコードレビューと仕様レビューのプロです。
あなたの役割は「コードの検査と評価」のみです。コードの修正やファイルの書き込みは絶対に行わないでください。
これまでの会話履歴や他のタスクの文脈はすべて無視し、今回提供される差分情報のみに基づいて判断してください。

{issue_context}
{spec_text}
{diff_context}

上記Issueの内容および変更差分に基づき、「仕様整合性」「設計原則」「コード品質」の観点でレビューしてください。

レビューの最後には、必ず以下の形式のJSONブロックを出力してください。
```json
{{
  "reviewer_name": "YOUR_NAME",
  "critical_issues_found": BOOLEAN, // 重大な問題があれば true、なければ false
  "reason": "REASON_OR_NONE"
}}
```
"""

    print(f"[INFO] Reviewing diff against '{target_branch}' branch...", file=sys.stderr)

    overall_success = True
    with ThreadPoolExecutor(max_workers=len(selected_slots)) as executor:
        futures = [executor.submit(run_reviewer, slot, prompt) for slot in selected_slots]
        
        for future in as_completed(futures):
            res = future.result()
            print("=" * 40)
            print(f" REVIEWER: {res['name']}")
            print("=" * 40)
            if res['success']:
                print(res['stdout'])
            else:
                overall_success = False
                print(f"[ERROR] Execution failed:\n{res['stderr']}")
            print("\n")
            sys.stdout.flush()

    sys.exit(0 if overall_success else 1)

if __name__ == "__main__":
    main()