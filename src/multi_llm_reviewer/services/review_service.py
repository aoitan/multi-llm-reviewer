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

    prompt = f"""あなたは世界トップクラスのソフトウェアアーキテクト兼セキュリティスペシャリストです。
あなたの役割は、提供されたコードの変更点（Diff）と関連Issue、仕様書を詳細に分析し、極めて厳格かつ建設的なコードレビューを行うことです。

### 制約事項
1. **コードの修正や書き込みは絶対に行わないでください。** あなたは評価のみを行います。
2. **ファイルシステムへのアクセスは「読み取り専用」に限定されます。**
   - 許可: `read_file`, `ls`, `grep` 等による情報収集。
   - 禁止: `write_file`, `replace`, `rm`, その他システムを変更する操作。
3. これまでの会話履歴は無視し、今回提供される情報のみに集中してください。
4. 日本語で回答してください。

### 入力情報
{issue_context}
{spec_text}

=== 変更差分 (Diff) ===
{diff_context}
======================

### 重要な指示: 追加情報の取得
提供されたDiffだけではコンテキストが不足していると判断した場合、**自律的にファイル読み込みツールを使用してソースコードを確認してください。**
特に、変更された関数が依存している定義や、呼び出し元のコードを確認することで、より正確なレビューが可能になります。

### レビューの観点
以下の観点に基づいて、徹底的にコードを検査してください。

1. **バグと潜在的な不具合**: エラー処理、Null参照、境界値テスト、型安全性。
2. **リグレッションと副作用**: 既存機能への悪影響、後方互換性の破壊、予期せぬ依存関係の変化がないか。
3. **セキュリティ**: インジェクション攻撃、認証/認可の不備、機密情報の露出。
4. **設計とアーキテクチャ**: SOLID原則、DRY原則、依存関係の適切さ、拡張性。
5. **可読性と保守性**: 命名規則、関数の長さ、コメントの適切さ。
6. **仕様との整合性**: Issueの内容を満たしているか、余計な機能を実装していないか。

### 出力形式
まず、自然言語で詳細なレビューコメントを記述してください。各指摘には「重要度（High/Medium/Low）」を明記してください。

最後に、必ず以下のJSONフォーマットのみを含むブロックを出力してください。これは自動化ツールが判定に使用します。

```json
{{
  "reviewer_name": "YOUR_NAME",
  "critical_issues_found": BOOLEAN,  // プロダクション環境へのデプロイを阻止すべき重大な問題があれば true
  "summary": "簡潔な要約（1行）",
  "review_score": 0-100, // コード品質のスコア
  "actionable_feedback": [
    "具体的な修正提案1",
    "具体的な修正提案2"
  ]
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