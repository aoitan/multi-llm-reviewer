import subprocess
import sys
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

        full_output_parts = []
        
        # 1文字ずつではなく、行またはバッファ単位で読む
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            
            if line:
                if stream_callback:
                    stream_callback(line)
                full_output_parts.append(line)
        
        process.wait()
        full_output = "".join(full_output_parts)
        
        if process.returncode != 0:
            if is_rate_limit(full_output):
                return "RATE_LIMIT", full_output
            return "ERROR", full_output
            
        return "SUCCESS", full_output
        
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
    name = slot["name"]
    cmds = slot["cmds"]
    last_res = None
    
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
        return {
            "name": f"{name} ({model_name})",
            "output": output,
            "success": False,
            "reason": "ERROR"
        }

    return last_res
