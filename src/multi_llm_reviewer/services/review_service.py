import sys
from concurrent.futures import ThreadPoolExecutor
from multi_llm_reviewer.core import config, git_utils, github_utils, llm_client
from multi_llm_reviewer.core.stream_manager import StreamManager

def decide_reviewers(target_branch, mode_arg):
    """レビューモードに基づいて実行するレビュアーリストを決定する"""
    
    # "all" 指定
    if mode_arg.lower() == "all":
        return config.REVIEWER_SLOTS, "User forced ALL"

    # カンマ区切り指定 (例: "gemini,codex")
    if mode_arg.lower() not in ["auto", "single"]:
        targets = [t.strip().lower() for t in mode_arg.split(",")]
        selected = [s for s in config.REVIEWER_SLOTS if s["name"].lower() in targets]
        if selected:
            return selected, f"User selected: {mode_arg}"
    
    # Auto / Single モードの判定
    files = git_utils.get_changed_files(target_branch)

    reason = "Default (Single)"
    should_be_all = False
    
    # 判定1: 変更ファイル数が多い (>= 5)
    if len(files) >= 5:
        should_be_all = True
        reason = f"Large changeset ({len(files)} files)"
    
    # 判定2: 重要ファイルが含まれる
    if not should_be_all:
        for f in files:
            for kw in config.CRITICAL_PATH_KEYWORDS:
                if kw in f.lower():
                    should_be_all = True
                    reason = f"Critical file changed ({f})"
                    break
            if should_be_all:
                break
    
    # モード決定
    if mode_arg.lower() == "auto":
        if should_be_all:
            return config.REVIEWER_SLOTS, f"Auto: ALL ({reason})"
        else:
            # Codexのみ (デフォルトのSingleレビュアー)
            codex = next((s for s in config.REVIEWER_SLOTS if s["name"] == "Codex"), config.REVIEWER_SLOTS[0])
            return [codex], f"Auto: Single ({reason})"
            
    elif mode_arg.lower() == "single":
        # 条件に関わらずCodex (または先頭)
        codex = next((s for s in config.REVIEWER_SLOTS if s["name"] == "Codex"), config.REVIEWER_SLOTS[0])
        return [codex], "User forced Single"
        
    return config.REVIEWER_SLOTS, "Unknown mode, defaulting to ALL"

def _run_single_reviewer_stream(slot, prompt, stream_manager):
    """1つのレビュアーを実行し、出力をStreamManagerに流す"""
    name = slot["name"]
    cmds = slot["cmds"]
    last_res = None
    
    # ヘッダーを出力 (StreamManager経由)
    header = f"\n{'='*40}\n REVIEWER: {name}\n{'='*40}\n"
    stream_manager.write(name, header)

    for i, cmd in enumerate(cmds):
        model_name = " ".join(cmd)
        
        # コールバック関数: 受け取ったテキストをStreamManagerに渡す
        def callback(text):
            stream_manager.write(name, text)
            
        status, output = llm_client.execute_command_async(cmd, input_text=prompt, stream_callback=callback)
        
        if status == "SUCCESS":
            stream_manager.finish(name)
            return {
                "name": f"{name} ({model_name})" if len(cmds) > 1 else name,
                "output": stream_manager.get_full_output(name), # ヘッダー込みの全出力
                "success": True
            }
        
        if status == "RATE_LIMIT":
            err_msg = f"\n[WARN] {name} ({model_name}) hit rate limit.\n"
            stream_manager.write(name, err_msg)
            
            last_res = {
                "name": f"{name} ({model_name})",
                "output": output,
                "success": False,
                "reason": "RATE_LIMIT"
            }
            if i < len(cmds) - 1:
                stream_manager.write(name, f"[INFO] Falling back to next model for {name}...\n")
                continue
            else:
                break
        
        # General ERROR
        err_msg = f"\n[ERROR] Execution failed: {status}\n"
        stream_manager.write(name, err_msg)
        
        stream_manager.finish(name)
        return {
            "name": f"{name} ({model_name})",
            "output": output,
            "success": False,
            "reason": "ERROR"
        }

    stream_manager.finish(name)
    return last_res


def run_multi_llm_review(target_branch="main", issue_num=None, mode="auto", spec_text=""):
    """
    複数のLLMによるレビューを実行する（ストリーミング対応）。
    """
    issue_context = ""
    actual_issue_num = issue_num or git_utils.get_current_branch_issue_num()
    if actual_issue_num:
        issue_body = github_utils.fetch_issue(actual_issue_num)
        if issue_body:
            issue_context = f"\n--------------------------------------------------\n【関連Issue情報 (Issue #{actual_issue_num})】\n{issue_body}\n--------------------------------------------------\n"

    # レビュアー決定
    selected_slots, decision_log = decide_reviewers(target_branch, mode)
    print(f"[INFO] Review Mode: {decision_log}", file=sys.stderr)

    diff_text = git_utils.get_git_diff(target_branch)
    diff_context = f"\n--------------------------------------------------\n【変更差分 (Diff)】\n{diff_text}\n--------------------------------------------------\n" if diff_text.strip() else "(No changes detected)"

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

    # StreamManagerの初期化
    priority_order = [s["name"] for s in selected_slots]
    stream_manager = StreamManager(priority_order)
    
    results = []
    
    # 並列実行
    with ThreadPoolExecutor(max_workers=len(selected_slots)) as executor:
        # StreamManagerを渡して実行
        futures = [
            executor.submit(_run_single_reviewer_stream, slot, prompt, stream_manager) 
            for slot in selected_slots
        ]
        
        # 完了待ち (出力はStreamManagerが制御するため、ここでは結果集計のみ)
        for future in futures:
            try:
                res = future.result()
                if res:
                    results.append(res)
            except Exception as e:
                print(f"[INTERNAL ERROR] Thread failed: {e}", file=sys.stderr)

    return results