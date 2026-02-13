import subprocess
import re
import sys
from multi_llm_reviewer.core import config


def _exclude_args():
    # Use long-form pathspec magic for wider git compatibility.
    return [f":(exclude){p}" for p in config.EXCLUDE_PATTERNS]


def _run_git_stdout(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True)
    return_code = res.returncode if isinstance(getattr(res, "returncode", 0), int) else 0
    if return_code != 0:
        err = (res.stderr or "").strip()
        # Some git builds fail on pathspec magic. Retry once without exclude pathspecs.
        if "pathspec magic" in err.lower() and any(
            isinstance(arg, str) and (arg.startswith(":(exclude)") or arg.startswith(":!"))
            for arg in cmd
        ):
            fallback_cmd = [
                arg for arg in cmd
                if not (
                    isinstance(arg, str)
                    and (arg.startswith(":(exclude)") or arg.startswith(":!"))
                )
            ]
            print(
                "[WARN] Exclude pathspec is not supported in this git. Retrying without exclusions.",
                file=sys.stderr,
            )
            fallback_res = subprocess.run(fallback_cmd, capture_output=True, text=True)
            fallback_code = (
                fallback_res.returncode
                if isinstance(getattr(fallback_res, "returncode", 0), int)
                else 0
            )
            if fallback_code == 0:
                return fallback_res.stdout
            fallback_err = (fallback_res.stderr or "").strip()
            raise RuntimeError(fallback_err or f"git command failed: {' '.join(fallback_cmd)}")
        raise RuntimeError(err or f"git command failed: {' '.join(cmd)}")
    return res.stdout


def _resolve_base_ref(target_branch):
    # Prefer remote tracking branch so local main checked out state does not hide committed diffs.
    candidates = [f"origin/{target_branch}", target_branch]
    for candidate in candidates:
        try:
            _run_git_stdout(["git", "rev-parse", "--verify", candidate])
            return candidate
        except Exception:
            continue
    return None

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
    """指定されたブランチとの差分と未コミット差分を取得する"""
    print(f"[INFO] Getting smart git diff against '{target_branch}'...", file=sys.stderr)
    exclude_args = _exclude_args()
    sections = []

    try:
        base_ref = _resolve_base_ref(target_branch)
        if base_ref:
            committed = _run_git_stdout(["git", "diff", f"{base_ref}...HEAD", "--"] + exclude_args)
            if committed.strip():
                sections.append(f"### Committed changes vs {base_ref} (merge-base)\n{committed}")
            else:
                # Fallback to two-dot semantics to match `git diff <base>` behavior users expect.
                committed_twodot = _run_git_stdout(["git", "diff", base_ref, "--"] + exclude_args)
                if committed_twodot.strip():
                    sections.append(f"### Changes vs {base_ref} (two-dot fallback)\n{committed_twodot}")
        else:
            print(f"[WARN] Base branch '{target_branch}' was not found. Skipping committed diff section.", file=sys.stderr)

        staged = _run_git_stdout(["git", "diff", "--cached", "--"] + exclude_args)
        if staged.strip():
            sections.append("### Staged changes\n" + staged)

        unstaged = _run_git_stdout(["git", "diff", "--"] + exclude_args)
        if unstaged.strip():
            sections.append("### Unstaged changes\n" + unstaged)
    except Exception as e:
        print(f"[ERROR] Failed to get git diff: {e}", file=sys.stderr)
        return ""

    diff_output = "\n\n".join(sections)
    max_chars = config.MAX_DIFF_CHARS
    if len(diff_output) > max_chars:
        print(f"[WARN] Diff is too large ({len(diff_output)} chars). Truncating...", file=sys.stderr)
        truncated_diff = diff_output[:max_chars]
        last_newline = truncated_diff.rfind('\n')
        if last_newline != -1:
            truncated_diff = truncated_diff[:last_newline]
        return f"{truncated_diff}\n... (truncated due to size limit)"

    return diff_output

def get_changed_files(target_branch):
    """
    変更されたファイルの一覧を取得する（base比較 + staged + unstaged）。
    """
    try:
        exclude_args = _exclude_args()
        changed = []

        base_ref = _resolve_base_ref(target_branch)
        if base_ref:
            committed_files = _run_git_stdout(["git", "diff", "--name-only", f"{base_ref}...HEAD", "--"] + exclude_args)
            changed.extend(f.strip() for f in committed_files.splitlines() if f.strip())
            if not changed:
                committed_files_twodot = _run_git_stdout(["git", "diff", "--name-only", base_ref, "--"] + exclude_args)
                changed.extend(f.strip() for f in committed_files_twodot.splitlines() if f.strip())

        staged_files = _run_git_stdout(["git", "diff", "--name-only", "--cached", "--"] + exclude_args)
        changed.extend(f.strip() for f in staged_files.splitlines() if f.strip())

        unstaged_files = _run_git_stdout(["git", "diff", "--name-only", "--"] + exclude_args)
        changed.extend(f.strip() for f in unstaged_files.splitlines() if f.strip())

        # preserve order while de-duplicating
        seen = set()
        deduped = []
        for path in changed:
            if path not in seen:
                seen.add(path)
                deduped.append(path)
        return deduped
    except Exception:
        return []
