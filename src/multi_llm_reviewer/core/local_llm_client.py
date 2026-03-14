"""ローカルLLM用のCLI呼び出しラッパー。

ローカルLLM（Ollamaなど）のCLI呼び出しを、外部LLMと同じインターフェースで扱えるようにする。
"""

import subprocess
import sys
import os
from typing import Optional, List, Tuple, Dict, Any
from . import config


def is_rate_limit(text: str) -> bool:
    """出力テキストからレートリミットエラーを検知する。
    
    ローカルLLMでは通常発生しないが、Ollamaのエラーメッセージなどに対応するため。
    
    Args:
        text: LLMの出力
        
    Returns:
        レートリミットを検知した場合はTrue
    """
    if not text:
        return False
    keywords = [
        "rate limit", "429", "too many requests", "quota exceeded",
        "rate_limit", "usage_limit_reached", "usage limit", "hit your usage limit",
        "exhausted your capacity", "exhausted", "quota will reset"
    ]
    return any(kw in text.lower() for kw in keywords)


def execute_local_llm_cli(
    cmd: List[str],
    input_text: Optional[str] = None,
    stream_callback: Optional[callable] = None
) -> Tuple[str, str]:
    """
    ローカルLLMのCLIを同期実行する。
    
    Args:
        cmd: 実行コマンド（例: ["ollama", "run", "llama3", "--system", "プロンプト"]）
        input_text: stdinに入力するプロンプト
        stream_callback: 実行中に呼ばれるコールバック関数 (text) -> None
        
    Returns:
        tuple: (status, output)
        statusは "SUCCESS", "RATE_LIMIT", "ERROR" のいずれか
        output: コマンドの出力（すべての標準出力と標準エラー）
        
    注意:
        - ローカルLLMは exit code 0 以外をエラーとして扱う
        - stream_callback には1文字ずつではなく、行単位またはバッファ単位で渡すのが効率的
    """
    try:
        # stdin入力の有無によるプロセス作成
        if input_text is not None:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            try:
                process.stdin.write(input_text)
                process.stdin.close()
            except BrokenPipeError:
                pass
        else:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
        
        # 出力の読み取り
        output_parts = []
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            
            if line:
                if stream_callback:
                    stream_callback(line)
                output_parts.append(line)
        
        process.wait()
        full_output = "".join(output_parts)
        
        # ターミナルプロンプトなどを検出してクリーンアップ
        if "LocalLlama3" in full_output or "Ollama" in full_output:
            # Ollamaがプロンプトを表示する場合は削除
            lines = full_output.split("\n")
            cleaned_lines = [line for line in lines if not any(
                prompt in line for prompt in ["ollama", "model:", "ver: ", "run:", ">>"]
            )]
            full_output = "\n".join(cleaned_lines)
        
        if process.returncode != 0:
            if is_rate_limit(full_output):
                return "RATE_LIMIT", full_output
            return "ERROR", full_output
        
        return "SUCCESS", full_output
        
    except FileNotFoundError:
        # ollamaコマンドが見つからないエラー
        error_msg = "ollamaコマンドが見つかりません。https://ollama.ai/ からインストールしてください。"
        return "ERROR", error_msg
    except Exception as e:
        error_msg = f"ローカルLLMの実行中にエラーが発生しました: {str(e)}"
        if stream_callback:
            stream_callback(f"[INTERNAL ERROR] {str(e)}\n")
        return "ERROR", error_msg


def run_local_llm_reviewer(
    slot: Dict[str, Any],
    prompt: str
) -> Tuple[str, str, bool, Optional[str]]:
    """
    ローカルLLM用のレビュアーを実行する。
    
    Args:
        slot: config.LOCAL_LLM_REVIEWER_SLOT の形式
        prompt: LLMに渡すプロンプト
        
    Returns:
        tuple: (status, output, success, reason)
        status: "SUCCESS", "RATE_LIMIT", "ERROR" のいずれか
        output: コマンドの出力
        success: 成功フラグ
        reason: 失敗理由（成功時はNone）
    """
    name = slot.get("name", "LocalLLM")
    cmds = slot.get("cmds", [])
    last_res = None
    
    for i, cmd in enumerate(cmds):
        model_name = " ".join(cmd)
        status, output = execute_local_llm_cli(cmd, input_text=prompt)
        
        if status == "SUCCESS":
            return (status, output, True, None)
        
        if status == "RATE_LIMIT":
            print(f"[WARN] {name} ({model_name}) hit rate limit.", file=sys.stderr)
            last_res = (status, output, False, "RATE_LIMIT")
            if i < len(cmds) - 1:
                print(f"[INFO] Falling back to next model for {name}...", file=sys.stderr)
                continue
            else:
                break
        
        # General ERROR
        return (status, output, False, "ERROR")
    
    if last_res:
        return last_res
    return ("ERROR", "Unknown error", False, None)


def run_local_llm_fixer(fixer_name: str, prompt: str, stream_callback=None) -> Tuple[str, str, bool, Optional[str]]:
    """
    ローカルLLM用の修正エージェントを実行する。
    
    Args:
        fixer_name: エージェント名（config.LOCAL_LLM_FIXER_COMMANDSのキー）
        prompt: LLMに渡すプロンプト
        stream_callback: 可選のコールバック関数
        
    Returns:
        tuple: (status, output, success, reason)
    """
    command = config.LOCAL_LLM_FIXER_COMMANDS.get(fixer_name)
    
    if not command:
        return ("ERROR", f"エージェント '{fixer_name}' の実行コマンドが見つかりません。", False, "UNKNOWN_FIXER")
    
    status, output = execute_local_llm_cli(command, input_text=prompt, stream_callback=stream_callback)
    return status, output, (status == "SUCCESS"), None if status == "SUCCESS" else status


def is_ollama_available() -> bool:
    """Ollamaがインストールされ、実行可能であるかを確認します。"""
    try:
        subprocess.run(
            ["ollama", "--version"],
            capture_output=True,
            check=True,
            text=True,
            timeout=5
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


def run_local_llm_pre_check(diff_text: str) -> str:
    """Gate 2: ローカルLLMによる軽量コード品質チェックを実行する。

    命名規則・コードスメル・重複コード・docstring欠落・例外握り潰しなど、
    フロンティアLLMを消費せずに検出できる問題を列挙する。

    Args:
        diff_text: git diff テキスト

    Returns:
        ローカルLLMの分析結果（文字列）。Ollama利用不可または失敗時は空文字 ""。
    """
    if not is_ollama_available():
        return ""

    prompt = f"""あなたはコード品質チェックの専門家です。
以下のコード差分を分析し、以下の観点でのみ問題点を箇条書きで列挙してください。
問題がなければ「問題なし」とだけ答えてください。

【チェック観点】
- 命名規則の混在（snake_case/camelCase 等）
- コードスメル（関数が長すぎる、ネストが深い、引数が多すぎる）
- docstring・型ヒントの欠落（公開関数・クラス）
- 例外の握り潰し（except: pass 等）
- デバッグコードの混入（print文等）
- コメントとコードの矛盾

【制約】
- セキュリティ・バグ・設計の深い判断は不要。形式的な問題のみ指摘。
- 各指摘は「ファイル名または関数名: 問題の概要」の形式で。
- 日本語で回答。

=== Code Diff ===
{diff_text}
================
"""

    local_slot = getattr(config, "LOCAL_LLM_REVIEWER_SLOT", None)
    cmds = local_slot.get("cmds") if isinstance(local_slot, dict) else None
    cmd = cmds[0] if cmds else ["ollama", "run", "llama3"]

    status, output = execute_local_llm_cli(cmd, input_text=prompt)
    if status != "SUCCESS":
        print(
            f"[INFO] Gate 2 (Local LLM pre-check) failed: {status}. Skipping.",
            file=sys.stderr,
        )
        return ""
    return output.strip()
