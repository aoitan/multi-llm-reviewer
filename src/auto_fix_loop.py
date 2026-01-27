#!/usr/bin/env python3
import subprocess
import sys
import re
import json
import os
import argparse
import time

# --- 設定 ---
MAX_LOOPS = 5
FIXER_ORDER = [
    "gemini3pro",
    "gemini2.5pro",
    "copilot",
    "codex",
    "gemini3flash",
    "codex-mini"
]

# スクリプトのディレクトリを取得
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REVIEW_SCRIPT_PATH = os.path.join(SCRIPT_DIR, "review_all.py")

def get_fix_command(fixer_name):
    if fixer_name == "gemini3pro":
        return ["gemini", "-m", "gemini-3-pro-preview", "--yolo"]
    elif fixer_name == "gemini2.5pro":
        return ["gemini", "-m", "gemini-2.5-pro", "--yolo"]
    elif fixer_name == "gemini3flash":
        return ["gemini", "-m", "gemini-3-flash-preview", "--yolo"]
    elif fixer_name == "copilot":
        return ["copilot", "--allow-all-tools"]
    elif fixer_name == "codex":
        return ["codex", "exec", "--full-auto"]
    elif fixer_name == "codex-mini":
        return ["codex", "exec", "--full-auto", "-m", "gpt-5.1-codex-mini"]
    else:
        return ["gemini", "-m", "gemini-3-pro-preview", "--yolo"]

def is_rate_limit(text):
    """出力テキストからレートリミットエラーを検知する"""
    keywords = [
        "rate limit", 
        "429", 
        "too many requests", 
        "quota exceeded", 
        "rate_limit",
        "usage_limit_reached",
        "usage limit",
        "hit your usage limit",
        "exhausted your capacity",
        "exhausted",
        "quota will reset"
    ]
    return any(kw in text.lower() for kw in keywords)

def run_review(review_script_args, loop_count=1):
    """review_all.py を実行し、出力をストリーミング表示しながらキャプチャして返す"""
    print("\n>>> Running review_all.py ...")
    if not os.path.exists(REVIEW_SCRIPT_PATH):
        print(f"[ERROR] review_all.py not found at {REVIEW_SCRIPT_PATH}")
        sys.exit(1)

    try:
        cmd = ["python3", REVIEW_SCRIPT_PATH] + review_script_args
        
        # ユーザーが明示的にレビュアーを指定していない場合、ループ回数に基づいて制御
        if not any(arg.startswith("--reviewers") for arg in review_script_args):
            if loop_count >= 3:
                cmd += ["--reviewers", "all"] # 難航時は総力戦
            else:
                cmd += ["--reviewers", "auto"] # 初期は自動判定（軽微ならSingle）

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        output_lines = []
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            output_lines.append(line)
        
        process.wait()
        full_output = "".join(output_lines)
        return full_output
    except Exception as e:
        print(f"[ERROR] Failed to run review_all.py: {e}")
        sys.exit(1)

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
                    reason = data.get("reason", "No reason provided")
                    reasons.append(f"[{reviewer}] {reason}")
            except json.JSONDecodeError:
                continue
        
        if critical_found:
            return True, f"Critical issues detected in JSON:\n" + "\n".join(reasons)
        elif json_parsed_successfully:
            return False, "No critical issues found (verified via JSON output)."

    print("[INFO] JSON output not found or incomplete. Falling back to text analysis.")
    gemini_match = re.search(r'#### 重大な問題点\s*\n(.+?)(\n####|\n===|$)', review_text, re.DOTALL)
    if gemini_match:
        content = gemini_match.group(1).strip()
        if "なし" not in content and content != "":
            return True, "Gemini detected critical issues (text analysis)."

    if "重大な問題: あり" in review_text or "判定: ❌" in review_text:
        return True, "Copilot detected critical issues (text analysis)."

    if "重大指摘" in review_text and "重大指摘: なし" not in review_text:
        return True, "Codex detected critical issues (text analysis)."

    return False, "No critical issues found (text analysis)."

def _execute_fix_cmd(cmd_base, prompt):
    """コマンドを実際に実行し、結果を返す内部関数"""
    # プロンプトは引数に含めず、stdinから渡す
    cmd = cmd_base
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,  # stdinをパイプに接続
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        # stdinにプロンプトを書き込んで閉じる
        # Popen.communicate() を使うと簡単だが、ストリーミング表示したいので
        # 別スレッドで書き込むか、書き込み後に読み込む必要がある。
        # ただし、入力がバッファに収まるなら先に書き込んでしまえば良い。
        # 巨大な場合ブロックする恐れがあるが、ここではシンプルに write して close する。
        try:
            process.stdin.write(prompt)
            process.stdin.close()
        except BrokenPipeError:
            pass # プロセスが既になくなっている場合など

        output_lines = []
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            output_lines.append(line)
        
        process.wait()
        full_output = "".join(output_lines)
        
        if process.returncode != 0:
            if is_rate_limit(full_output):
                return "RATE_LIMIT", full_output
            return "ERROR", full_output
        
        return "SUCCESS", full_output
    except Exception as e:
        return "ERROR", str(e)

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
    fix_cmd = get_fix_command(fixer_name)
    role_info = get_role_instructions(loop_count)
    
    # --- STEP 1: DESIGN PHASE ---
    print(f"\n>>> [PHASE 1: DESIGN] Role: {role_info['role']} using {fixer_name}...")
    design_prompt = f"""
あなたは今、**{role_info['role']}** として行動してください。
目標: {role_info['goal']}

以下のコードレビュー結果を分析し、詳細な「修正設計書」を作成してください。
このフェーズでは、**ソースコードの編集（書き換えツールの使用）は一切禁止**です。
ファイルの内容を読み取って状況を把握し、論理的な修正手順を検討してください。

出力には以下の内容を含めてください：
1. 現状の根本原因の分析（{role_info['role']}の視点で）
2. 修正すべきファイルと箇所の特定
3. 具体的な修正方針

--- Review Result ---
{review_text}
"""
    
    status, design_output = _execute_fix_cmd(fix_cmd, design_prompt)
    if status != "SUCCESS":
        return status, design_output

    # --- STEP 2: IMPLEMENTATION PHASE ---
    print(f"\n>>> [PHASE 2: IMPLEMENTATION] Role: {role_info['role']} using {fixer_name}...")
    implementation_prompt = f"""
あなたは **{role_info['role']}** です。
目標: {role_info['goal']}

先ほど作成した「修正設計書」に従って、コードを修正してください。
レビュー指摘事項が解決され、テストがパスするように実装してください。

--- Review Result ---
{review_text}

--- Fix Design (Follow this!) ---
{design_output}
"""
    
    return _execute_fix_cmd(fix_cmd, implementation_prompt)

def run_fix_with_fallback(review_text, primary_fixer, loop_count):
    """レートリミット時にフォールバックしつつ修正を実行する"""
    fixers_to_try = [primary_fixer] + [f for f in FIXER_ORDER if f != primary_fixer]
    
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

def main():
    parser = argparse.ArgumentParser(description="Auto Fix Loop with Fallback & Role Strategy", add_help=False)
    parser.add_argument("--fixer", choices=FIXER_ORDER, default="gemini3pro", help="Primary fixer agent")
    parser.add_argument("--help", action="store_true", help="Show help")
    
    args, unknown_args = parser.parse_known_args()
    
    if args.help:
        parser.print_help()
        print("\n--- Options for review_all.py ---")
        print("Any other arguments will be passed to review_all.py (e.g. -i 73 -b develop)")
        sys.exit(0)

    loop_count = 0
    while loop_count < MAX_LOOPS:
        loop_count += 1
        print(f"\n" + "="*60)
        print(f" Loop {loop_count}/{MAX_LOOPS}")
        print(f"="*60)
        
        # 1. レビュー実行
        review_output = run_review(unknown_args, loop_count)

        # 2. 判定
        is_critical, reason = has_critical_issues(review_output)
        
        if is_critical:
            print(f"\n[!] {reason}")
            # 3. 修正実行 (ループ回数を渡す)
            success = run_fix_with_fallback(review_output, args.fixer, loop_count)
            if not success:
                print("[ERROR] Failed to fix issues. Breaking loop.")
                break
        else:
            print(f"\n[OK] {reason}")
            print("All clear! No critical issues found.")
            break
            
    if loop_count >= MAX_LOOPS:
        print(f"\n[WARN] Max loops ({MAX_LOOPS}) reached. Manual check required.")

if __name__ == "__main__":
    main()