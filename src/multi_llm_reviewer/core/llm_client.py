import subprocess
import sys
import os
import select
import time

from multi_llm_reviewer.core import config

def is_rate_limit(text):
    """出力テキストからレートリミットエラーを検知する"""
    if not text:
        return False
    keywords = [
        "rate limit", "429", "too many requests", "quota exceeded", 
        "rate_limit", "usage_limit_reached", "usage limit", "hit your usage limit",
        "exhausted your capacity", "exhausted", "quota will reset"
    ]
    return any(kw in text.lower() for kw in keywords)


def _get_review_command_timeout_seconds():
    return int(getattr(config, "REVIEW_COMMAND_TIMEOUT_SECONDS", 180))


def _read_process_output(process, stream_callback=None, echo_stdout=False):
    timeout_seconds = _get_review_command_timeout_seconds()
    start_time = time.monotonic()
    full_output_parts = []
    stdout_fd = process.stdout.fileno()
    encoding = process.stdout.encoding or "utf-8"

    while True:
        if time.monotonic() - start_time >= timeout_seconds:
            process.kill()
            process.wait()
            timeout_msg = (
                f"[ERROR] Command timed out after {timeout_seconds} seconds: {' '.join(process.args)}\n"
            )
            if stream_callback:
                stream_callback(timeout_msg)
            if echo_stdout:
                sys.stdout.write(timeout_msg)
                sys.stdout.flush()
            full_output_parts.append(timeout_msg)
            return "ERROR", "".join(full_output_parts)

        ready, _, _ = select.select([process.stdout], [], [], 0.2)
        if not ready:
            if process.poll() is not None:
                break
            continue

        chunk = os.read(stdout_fd, 4096)
        if not chunk:
            if process.poll() is not None:
                break
            continue

        line = chunk.decode(encoding, errors="replace")
        if stream_callback:
            stream_callback(line)
        if echo_stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
        full_output_parts.append(line)

    process.wait()
    full_output = "".join(full_output_parts)
    if process.returncode != 0:
        if is_rate_limit(full_output):
            return "RATE_LIMIT", full_output
        return "ERROR", full_output
    return "SUCCESS", full_output

def execute_command(cmd, input_text=None):
    """
    外部コマンドを実行する。
    
    Args:
        cmd: 実行するコマンドのリスト
        input_text: stdinに渡す文字列
        
    Returns:
        tuple: (status, stdout_stderr_combined)
        statusは "SUCCESS", "RATE_LIMIT", "ERROR" のいずれか
    """
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE if input_text is not None else None,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        if input_text is not None:
            try:
                process.stdin.write(input_text)
                process.stdin.close()
            except BrokenPipeError:
                pass
        return _read_process_output(process, echo_stdout=True)
    except Exception as e:
        return "ERROR", str(e)

def execute_command_async(cmd, input_text=None, stream_callback=None):
    """
    外部コマンドを非同期実行し、出力をリアルタイムでコールバックに渡す。
    
    Args:
        cmd: 実行コマンド
        input_text: stdin入力
        stream_callback: func(text) -> None
        
    Returns:
        tuple: (status, full_output)
    """
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, # stderrもstdoutにマージ
            stdin=subprocess.PIPE if input_text is not None else None,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        if input_text is not None:
            try:
                process.stdin.write(input_text)
                process.stdin.close()
            except BrokenPipeError:
                pass

        return _read_process_output(process, stream_callback=stream_callback)
        
    except Exception as e:
        err_msg = str(e)
        if stream_callback:
            stream_callback(f"[INTERNAL ERROR] {err_msg}\n")
        return "ERROR", err_msg

def run_reviewer_with_fallback(slot, prompt):
    """
    1つのレビュアー枠（Slot）に対して、フォールバックを含めて実行する。
    
    Args:
        slot: config.REVIEWER_SLOTS 内の1つの要素
        prompt: LLMに渡すプロンプト
        
    Returns:
        dict: 結果情報
    """
    from . import local_llm_client

    # 1. ローカルLLM強制モードのチェック
    if os.getenv("LOCAL_LLM_ONLY") == "1":
        # slotをローカルLLM用に差し替えるか、local_llm_clientを直接呼ぶ
        status, output, success, reason = local_llm_client.run_local_llm_reviewer(slot, prompt)
        return {
            "name": slot["name"] + " (Local)",
            "output": output,
            "success": success,
            "reason": reason
        }

    name = slot["name"]
    cmds = slot["cmds"]
    last_res = None
    
    # 2. フロンティアLLMの実行試行
    for i, cmd in enumerate(cmds):
        model_name = " ".join(cmd)
        status, output = execute_command(cmd, input_text=prompt)
        
        if status == "SUCCESS":
            return {
                "name": f"{name} ({model_name})" if len(cmds) > 1 else name,
                "output": output,
                "success": True
            }
        
        if status == "RATE_LIMIT":
            print(f"[WARN] {name} ({model_name}) hit rate limit.", file=sys.stderr)
            last_res = {
                "name": f"{name} ({model_name})",
                "output": output,
                "success": False,
                "reason": "RATE_LIMIT"
            }
            if i < len(cmds) - 1:
                print(f"[INFO] Falling back to next model for {name}...", file=sys.stderr)
                continue
            else:
                break
        
        # General ERROR
        last_res = {
            "name": f"{name} ({model_name})",
            "output": output,
            "success": False,
            "reason": "ERROR"
        }

    # 3. 最終防衛ライン: ローカルLLMへのフォールバック
    # フロンティアLLMが全滅し、かつOllamaが利用可能な場合
    if local_llm_client.is_ollama_available():
        print(f"[WARN] All Frontier models failed for {name}. Falling back to Local LLM (Ollama)...", file=sys.stderr)
        
        # ローカルLLM用のスロット定義を取得（なければデフォルトのLlama3）
        local_slot = getattr(config, "LOCAL_LLM_REVIEWER_SLOT", {"name": "LocalFallback", "cmds": [["ollama", "run", "llama3"]]})
        
        status, output, success, reason = local_llm_client.run_local_llm_reviewer(local_slot, prompt)
        
        return {
            "name": f"{name} (Fallback to Local)",
            "output": output,
            "success": success,
            "reason": reason or last_res.get("reason")
        }

    # ローカルも使えない場合は最後のフロンティアエラーを返す
    return last_res
