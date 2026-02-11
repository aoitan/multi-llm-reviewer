import json
import re
import sys
from multi_llm_reviewer.core import config, llm_client
from multi_llm_reviewer.services import review_service

import os

def has_critical_issues(review_text):
    """
    レビュー結果のテキストを解析し、重大な問題が含まれているか判定する。
    """
    critical_found = False
    reasons = []

    json_matches = re.findall(r'```json\s*(\{.*?\})\s*```', review_text, re.DOTALL)
    json_parsed_successfully = False

    if json_matches:
        for json_str in json_matches:
            try:
                data = json.loads(json_str)
                # テンプレートやプレースホルダはスキップ
                if data.get("reviewer_name") == "YOUR_NAME" or isinstance(data.get("critical_issues_found"), str):
                    continue

                json_parsed_successfully = True
                if data.get("critical_issues_found") is True:
                    critical_found = True
                    reviewer = data.get("reviewer_name", "Unknown")
                    # reason がなければ summary を使い、それもなければデフォルト値を出す
                    reason = data.get("reason") or data.get("summary") or "No reason provided"
                    reasons.append(f"[{reviewer}] {reason}")
            except json.JSONDecodeError:
                continue
        
        if critical_found:
            return True, f"Critical issues detected in JSON:\n" + "\n".join(reasons)
        elif json_parsed_successfully:
            return False, "No critical issues found (verified via JSON output)."

    print("[INFO] JSON output not found or incomplete. Falling back to text analysis.")
    gemini_match = re.search(r'#### 重大な問題点\s*\n(.+?)(?:\n####|\n===|$)', review_text, re.DOTALL)
    if gemini_match:
        content = gemini_match.group(1).strip()
        if "なし" not in content and content != "":
            return True, "Gemini detected critical issues (text analysis)."

    if "重大な問題: あり" in review_text or "判定: ❌" in review_text:
        return True, "Copilot detected critical issues (text analysis)."

    if "重大指摘" in review_text and "重大指摘: なし" not in review_text:
        return True, "Codex detected critical issues (text analysis)."

    return False, "No critical issues found (text analysis)."

def get_role_instructions(loop_count):
    """ループ回数に応じた役割と指示を返す"""
    if loop_count <= 2:
        return {
            "role": "Efficiency Engineer (実装担当)",
            "goal": "最小のパッチでレビュー指摘を正確に解決してください。既存の規約とスタイルを尊重しつつ、効率的に修正してください。"
        }
    elif loop_count == 3:
        return {
            "role": "Investigative Debugger (デバッガ)",
            "goal": "修正を急がず、原因の切り分けと特定に専念してください。必要に応じて調査用のログ（print等）を挿入し、何が起きているかを正確に把握してください。"
        }
    elif loop_count == 4:
        return {
            "role": "Precision Surgeon (サージャン)",
            "goal": "デバッガが特定した原因に対し、ピンポイントで最小かつ確実な外科手術的修正を行ってください。副作用を最小限に抑えてください。"
        }
    else:
        return {
            "role": "Strategic Architect (アーキテクト)",
            "goal": "これまでの修正が難航している理由を俯瞰し、設計の前提や境界条件を見直してください。必要であれば方針の根本的な変更を提案し、現在の実装を止める判断も行ってください。"
        }

def run_fix_attempt(review_text, fixer_name, loop_count):
    """特定のFixerで設計と実装の二段階で修正を試みる"""
    
    # 0. コンテキスト分析 (オフロード判定用)
    # 現在の変更規模を推測するために git_utils を使用
    # 本来は review_args を受け取るべきだが、簡易的に再取得
    base_branch = config.DEFAULT_BASE_BRANCH
    changed_files = git_utils.get_changed_files(base_branch)
    threshold = getattr(config, "LARGE_CHANGESET_THRESHOLD", 10)
    
    is_large_changeset = len(changed_files) >= threshold
    is_critical_path = any(kw in f.lower() for f in changed_files for kw in config.CRITICAL_PATH_KEYWORDS)
    
    can_offload_design = (
        not is_large_changeset 
        and not is_critical_path 
        and llm_client.is_ollama_available()
    )

    # 1. Design Phase の担当エージェント決定
    design_fixer = fixer_name # デフォルトは指定されたFixer (フロンティア)
    design_cmd = None
    
    if os.getenv("LOCAL_LLM_ONLY") == "1":
        # 強制ローカルモード
        design_fixer = "llama3-fix"
        design_cmd = config.LOCAL_LLM_FIXER_COMMANDS.get("llama3-fix")
    elif can_offload_design:
        # 条件付きオフロード: ローカルLLMに任せる
        print(f"\n[INFO] Offloading Design Phase to Local LLM (Small changeset, Non-critical)...")
        design_fixer = "llama3-fix (Offloaded)"
        design_cmd = config.LOCAL_LLM_FIXER_COMMANDS.get("llama3-fix")
    
    if design_cmd is None:
        design_cmd = config.FIXER_COMMANDS.get(fixer_name, config.FIXER_COMMANDS["gemini3pro"])


    # 2. Implementation Phase の担当エージェント決定
    impl_fixer = fixer_name
    impl_cmd = None
    
    if os.getenv("LOCAL_LLM_ONLY") == "1":
        impl_fixer = "llama3-fix"
        impl_cmd = config.LOCAL_LLM_FIXER_COMMANDS.get("llama3-fix")
    else:
        # 実装は常にフロンティアLLM (指定されたFixer)
        impl_cmd = config.FIXER_COMMANDS.get(fixer_name, config.FIXER_COMMANDS["gemini3pro"])
        
    role_info = get_role_instructions(loop_count)
    
    # --- STEP 1: DESIGN PHASE ---
    print(f"\n>>> [PHASE 1: DESIGN] Role: {role_info['role']} using {design_fixer}...")
    design_base = config.load_prompt("fix_design_prompt.txt")
    design_prompt = f"""{design_base}

あなたは今、**{role_info['role']}** として行動してください。
目標: {role_info['goal']}

--- Review Result ---
{review_text}
"""
    
    # execute_command は内部で local_llm_client への振り分けを持っていないため
    # コマンド自体を正しく選択して渡す必要がある。
    # llm_client.execute_command は汎用的なので、cmdリストを渡せば動くはずだが
    # local_llm_client のラッパーを経由させる必要があるかどうか
    
    if "ollama" in design_cmd[0]:
        from multi_llm_reviewer.core import local_llm_client
        status, design_output = local_llm_client.execute_local_llm_cli(design_cmd, input_text=design_prompt)
    else:
        status, design_output = llm_client.execute_command(design_cmd, design_prompt)

    if status != "SUCCESS":
        return status, design_output

    # --- STEP 2: IMPLEMENTATION PHASE ---
    print(f"\n>>> [PHASE 2: IMPLEMENTATION] Role: {role_info['role']} using {impl_fixer}...")
    impl_base = config.load_prompt("fix_implementation_prompt.txt")
    implementation_prompt = f"""{impl_base}

あなたは **{role_info['role']}** です。
目標: {role_info['goal']}

--- Review Result ---
{review_text}

--- Fix Design (Follow this!) ---
{design_output}
"""
    
    if "ollama" in impl_cmd[0]:
        from multi_llm_reviewer.core import local_llm_client
        return local_llm_client.execute_local_llm_cli(impl_cmd, input_text=implementation_prompt)
    else:
        return llm_client.execute_command(impl_cmd, implementation_prompt)

def run_fix_with_fallback(review_text, primary_fixer, loop_count):
    """レートリミット時にフォールバックしつつ修正を実行する"""
    fixers_to_try = [primary_fixer] + [f for f in config.FIXER_ORDER if f != primary_fixer]
    
    for fixer in fixers_to_try:
        status, output = run_fix_attempt(review_text, fixer, loop_count)
        
        if status == "SUCCESS":
            print(f"\n>>> Fix process completed with {fixer}.")
            return True
        elif status == "RATE_LIMIT":
            print(f"\n[WARN] Rate limit reached for {fixer}. Trying fallback...")
            continue
        else:
            print(f"\n[ERROR] Fix failed with {fixer}. (Not a rate limit, stopping fallback)")
            return False
            
    print("\n[ERROR] All available fixers failed or reached rate limits.")
    return False

def run_auto_fix_loop(fixer_name="gemini3pro", max_loops=None, review_args=None):
    """
    自動修正ループを実行する。
    """
    max_loops = max_loops or config.MAX_LOOPS
    review_args = review_args or {}
    
    loop_count = 0
    while loop_count < max_loops:
        loop_count += 1
        print(f"\n" + "="*60)
        print(f" Loop {loop_count}/{max_loops}")
        print("="*60)
        
        # 1. レビュー実行 (review_service を直接呼ぶ)
        # 難航時はレビュアーを増やす
        current_mode = review_args.get("mode", "auto")
        if loop_count >= 3:
            current_mode = "all"
            
        results = review_service.run_multi_llm_review(
            target_branch=review_args.get("base", "main"),
            issue_num=review_args.get("issue"),
            mode=current_mode,
            spec_text=review_args.get("spec", "")
        )
        
        # 結果を結合して判定
        combined_review_text = "\n\n".join([r['output'] for r in results if r['success']])
        
        # 2. 判定
        is_critical, reason = has_critical_issues(combined_review_text)
        
        if is_critical:
            print(f"\n[!] {reason}")
            # 3. 修正実行
            success = run_fix_with_fallback(combined_review_text, fixer_name, loop_count)
            if not success:
                print("[ERROR] Failed to fix issues. Breaking loop.")
                break
        else:
            print(f"\n[OK] {reason}")
            print("All clear! No critical issues found.")
            break
            
    if loop_count >= max_loops:
        print(f"\n[WARN] Max loops ({max_loops}) reached. Manual check required.")
