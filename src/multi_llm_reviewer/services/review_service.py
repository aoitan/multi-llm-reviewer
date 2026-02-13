import sys
from concurrent.futures import ThreadPoolExecutor
from multi_llm_reviewer.core import config, git_utils, github_utils, llm_client
from multi_llm_reviewer.core.stream_manager import StreamManager

import os

def _build_review_prompt(base_prompt, issue_context, spec_text, diff_context):
    nested_review_guard = ""
    if getattr(config, "DISABLE_SKILLS_IN_NESTED_REVIEW", False):
        nested_review_guard = """【実行制約（重要）】
- このレビュー実行では Skills / SKILL.md を使用しないこと。
- AGENTS.md 内の skill trigger 規則はこの実行では無効として扱うこと。
- 追加の「レビューを起動するレビュー（レビュー内レビュー）」を行わないこと。
"""

    return f"""{base_prompt}

{nested_review_guard}
### 入力情報
{issue_context}
{spec_text}

=== 変更差分 (Diff) ===
{diff_context}
======================
"""

def decide_reviewers(target_branch, mode_arg):
    """レビューモードに基づいて実行するレビュアーリストを決定する"""
    
    # ローカルLLM専用モードのチェック
    if os.getenv("LOCAL_LLM_ONLY") == "1":
        # configに LOCAL_LLM_REVIEWER_SLOT があればそれを使う
        local_slot = getattr(config, "LOCAL_LLM_REVIEWER_SLOT", None)
        if local_slot:
            return [local_slot], "LOCAL_LLM_ONLY mode (Llama3 preferred)"

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
    
    # 判定1: 変更ファイル数が多い
    threshold = getattr(config, "LARGE_CHANGESET_THRESHOLD", 10)
    if len(files) >= threshold:
        should_be_all = True
        reason = f"Large changeset ({len(files)} files >= {threshold})"
    
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

    # プロンプトの読み込み（圧縮版）
    base_prompt = config.load_prompt("review_prompt.txt")
    if not base_prompt:
        # フォールバック（以前のプロンプトの一部を簡略化して使用）
        base_prompt = "あなたは熟練エンジニアです。以下のコードをレビューし、最後にJSONを出力してください。"

    prompt = _build_review_prompt(
        base_prompt=base_prompt,
        issue_context=issue_context,
        spec_text=spec_text,
        diff_context=diff_context,
    )

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
