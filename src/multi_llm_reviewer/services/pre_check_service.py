"""Gate 1: ルールベース事前チェックサービス。

LLMレビューの前に機械的・決定論的に検出できる問題を検査し、
フロンティアLLMへのリクエストを削減する。
"""
import fnmatch
import ast
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from multi_llm_reviewer.core import config

# (issues: List[str], warnings: List[str], passed: List[str])
CheckResult = Tuple[List[str], List[str], List[str]]

_SECRETS_PATTERN = re.compile(
    r'(?i)(api[_-]?key|secret|password|token|aws_access_key)[_a-z]*\s*[=:]\s*["\'][^"\']{8,}["\']'
)
_CONFLICT_MARKER_PREFIXES = ("<<<<<<< ", ">>>>>>> ")
_CONFLICT_MARKER_EXACT = "======="  # 単独行のみ（================== のような区切り線と区別）
_MARKER_ANNOTATION = ("TODO", "FIXME", "HACK", "XXX")
_SKIP_DECORATORS = ("@pytest.mark.skip", "@unittest.skip")


@dataclass
class PreCheckResult:
    """ルールベース事前チェックの結果。"""
    blocking_issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    passed_checks: List[str] = field(default_factory=list)

    @property
    def has_blocking(self) -> bool:
        return len(self.blocking_issues) > 0

    @property
    def summary(self) -> str:
        if not self.blocking_issues and not self.warnings and not self.passed_checks:
            return ""
        lines = []
        for issue in self.blocking_issues:
            lines.append(f"- ❌ [BLOCK] {issue}")
        for warn in self.warnings:
            lines.append(f"- ⚠️ [WARN] {warn}")
        for passed in self.passed_checks:
            lines.append(f"- ✅ [PASS] {passed}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Individual check functions
# Each returns (blocking_issues, warnings, passed_checks)
# ---------------------------------------------------------------------------

def check_empty_diff(diff_text: str) -> CheckResult:
    """差分がゼロまたは空の場合を検出する。"""
    stripped = diff_text.strip()
    if not stripped or stripped == "(No changes detected)":
        return ["変更がありません。レビュー対象の差分が存在しません。"], [], []
    return [], [], []


def check_conflict_markers(diff_text: str) -> CheckResult:
    """マージコンフリクトマーカーの残存を検出する（追加行のみ対象）。

    `=======` は単独行（それだけ）の場合のみ検出し、
    `================` などの区切り線との誤検知を防ぐ。
    """
    for line in diff_text.splitlines():
        if not line.startswith("+"):
            continue
        content = line[1:]
        if any(content.startswith(m) for m in _CONFLICT_MARKER_PREFIXES):
            return ["マージコンフリクトマーカーが残っています。解消してから再実行してください。"], [], []
        if content.rstrip() == _CONFLICT_MARKER_EXACT:
            return ["マージコンフリクトマーカーが残っています。解消してから再実行してください。"], [], []
    return [], [], []


def check_only_excluded_files(changed_files: List[str]) -> CheckResult:
    """変更ファイルが全て除外パターン（ロックファイル・バイナリ等）のみの場合を検出する。"""
    if not changed_files:
        return [], [], []
    exclude_patterns = getattr(config, "EXCLUDE_PATTERNS", [])
    for filepath in changed_files:
        filename = Path(filepath).name
        path_str = filepath.replace("\\", "/")
        matched = any(
            fnmatch.fnmatch(filename, pat) or fnmatch.fnmatch(path_str, pat)
            for pat in exclude_patterns
        )
        if not matched:
            return [], [], []
    return ["レビュー対象のソースコードがありません（ロックファイル・バイナリのみの変更）。"], [], []


def _is_test_file_path(filepath: str) -> bool:
    """テストファイルのパスかどうかを判定する。"""
    parts = Path(filepath).parts
    name = Path(filepath).name
    return name.startswith("test_") or "tests" in parts or "test" in parts


def check_secrets(diff_text: str) -> CheckResult:
    """ハードコードされたシークレット・クレデンシャルの混入を検出する（追加行のみ）。

    テストファイルはテストデータを含むため除外する。
    """
    current_file: Optional[str] = None
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split(" ")
            current_file = parts[-1][2:] if len(parts) >= 4 else None
            continue
        if not line.startswith("+"):
            continue
        if current_file and _is_test_file_path(current_file):
            continue
        if _SECRETS_PATTERN.search(line[1:]):
            return ["機密情報の可能性があるハードコードが検出されました。コミット前に確認してください。"], [], []
    return [], [], []


def check_large_single_file_change(diff_text: str, threshold: int = 500) -> CheckResult:
    """単一ファイルの追加行数が閾値を超える場合に警告する。"""
    warnings: List[str] = []
    current_file: Optional[str] = None
    added_count = 0

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            if current_file and added_count > threshold:
                warnings.append(
                    f"`{current_file}` の変更が大きすぎます（+{added_count}行）。"
                    "コミットを分割するか `--reviewers all` で実行してください。"
                )
            # parse filename from "diff --git a/path b/path"
            parts = line.split(" ")
            current_file = parts[-1][2:] if len(parts) >= 4 else None
            added_count = 0
        elif line.startswith("+") and not line.startswith("+++"):
            added_count += 1

    if current_file and added_count > threshold:
        warnings.append(
            f"`{current_file}` の変更が大きすぎます（+{added_count}行）。"
            "コミットを分割するか `--reviewers all` で実行してください。"
        )
    return [], warnings, []


def check_todo_fixme(diff_text: str) -> CheckResult:
    """追加行への TODO/FIXME/HACK/XXX コメントの混入を検出する。"""
    found: List[str] = []
    for line in diff_text.splitlines():
        if not line.startswith("+"):
            continue
        for marker in _MARKER_ANNOTATION:
            if re.search(r'\b' + marker + r'\b', line, re.IGNORECASE):
                found.append(marker)
                break
    if found:
        markers_str = ", ".join(sorted(set(found)))
        return [], [f"未解決の {markers_str} コメントが追加されています。意図的なものか確認してください。"], []
    return [], [], []


def check_python_syntax(changed_files: List[str]) -> CheckResult:
    """変更された .py ファイルの構文を py_compile で検査する。"""
    import py_compile
    issues: List[str] = []
    for filepath in changed_files:
        if not filepath.endswith(".py"):
            continue
        if not Path(filepath).exists():
            continue
        try:
            py_compile.compile(filepath, doraise=True)
        except py_compile.PyCompileError as e:
            issues.append(f"Python構文エラー: {filepath} — {e}")
    return issues, [], []


def _find_tsc() -> Optional[str]:
    """tsc コマンドの場所を探す（グローバル → npx 順）。"""
    if shutil.which("tsc"):
        return "tsc"
    # node_modules/.bin/tsc (プロジェクトローカル)
    local = Path("node_modules/.bin/tsc")
    if local.exists():
        return str(local)
    return None


def check_typescript_syntax(changed_files: List[str]) -> CheckResult:
    """変更された .ts / .tsx ファイルの構文を tsc --noEmit で検査する。"""
    # まず .ts/.tsx ファイルがあるか確認（存在チェック前）
    ts_candidates = [f for f in changed_files if f.endswith((".ts", ".tsx"))]
    if not ts_candidates:
        return [], [], []

    tsc = _find_tsc()
    if tsc is None:
        return [], [
            "TypeScriptファイルが含まれていますが `tsc` が見つかりません。"
            "構文チェックをスキップします。（`npm install typescript` または `npm install -g typescript` で解決できます）"
        ], []

    # 実際に存在するファイルのみを構文チェック対象にする
    ts_files = [f for f in ts_candidates if Path(f).exists()]
    if not ts_files:
        return [], [], []

    try:
        result = subprocess.run(
            [tsc, "--noEmit", "--skipLibCheck"] + ts_files,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            output = (result.stdout or result.stderr or "").strip()
            # TS1xxx = parse/syntax errors (blocking); TS2xxx+ = type/semantic errors (warn only)
            syntax_errors = [line for line in output.splitlines() if re.search(r'error TS1\d{3}:', line)]
            if syntax_errors:
                return [
                    "TypeScript構文エラーが検出されました。LLMレビュー前に修正してください。\n"
                    + "\n".join(syntax_errors)
                ], [], []
            return [], [f"TypeScript型エラーが検出されました（構文は正常）。確認してください。\n{output}"], []
    except subprocess.TimeoutExpired:
        return [], ["tsc の実行がタイムアウトしました（120秒）。TypeScript構文チェックをスキップします。"], []
    except Exception as e:
        return [], [f"tsc の実行に失敗しました: {e}"], []

    return [], [], []


def check_missing_tests(changed_files: List[str]) -> CheckResult:
    """src/*.py が変更されているのに対応するテストが変更されていない場合に警告する。"""
    warnings: List[str] = []
    src_py = [f for f in changed_files if re.search(r"\bsrc\b.*\.py$", f)]
    test_files = {Path(f).stem for f in changed_files if re.search(r"\btests?\b", f)}

    for src in src_py:
        stem = Path(src).stem
        expected_test_name = f"test_{stem}"
        if expected_test_name not in test_files:
            warnings.append(
                f"`{src}` が変更されていますが、対応するテスト (`{expected_test_name}.py`) "
                "が変更されていません。テストの更新を検討してください。"
            )
    return [], warnings, []


def _has_assertion_in_func(node: ast.FunctionDef) -> bool:
    """AST関数ノード内に assert 文または pytest.raises 呼び出しがあるか確認する。"""
    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            return True
        if isinstance(child, ast.Call):
            func = child.func
            # pytest.raises(...)
            if isinstance(func, ast.Attribute) and func.attr == "raises":
                return True
    return False


def check_assert_less_tests(changed_files: List[str]) -> CheckResult:
    """テストファイル内でアサーションのない test_ 関数を検出する（AST解析）。"""
    import ast
    warnings: List[str] = []
    test_files = [
        f for f in changed_files
        if Path(f).name.startswith("test_") and f.endswith(".py") and Path(f).exists()
    ]
    for filepath in test_files:
        source = Path(filepath).read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue  # 構文エラーは check_python_syntax で検出済み
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                if not _has_assertion_in_func(node):
                    warnings.append(
                        f"`{filepath}`: `{node.name}` にアサーションがありません（偽陽性テストの疑い）。"
                    )
    return [], warnings, []


def _is_skip_decorator(decorator: ast.expr) -> bool:
    """デコレータノードが @pytest.mark.skip / @unittest.skip かどうか判定する。"""
    # @pytest.mark.skip または @pytest.mark.skip(reason=...)
    if isinstance(decorator, ast.Attribute) and decorator.attr == "skip":
        return True
    if isinstance(decorator, ast.Call):
        return _is_skip_decorator(decorator.func)
    return False


def check_skipped_tests(changed_files: List[str], threshold: int = 3) -> CheckResult:
    """変更ファイル内の @pytest.mark.skip / @unittest.skip の合計数が閾値を超えたら警告する（AST解析）。"""
    import ast
    total_skips = 0
    test_files = [
        f for f in changed_files
        if Path(f).name.startswith("test_") and f.endswith(".py") and Path(f).exists()
    ]
    for filepath in test_files:
        source = Path(filepath).read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    if _is_skip_decorator(decorator):
                        total_skips += 1

    if total_skips >= threshold:
        return [], [
            f"スキップされているテストが {total_skips} 件あります（閾値: {threshold}）。"
            "意図的なものか確認してください。"
        ], []
    return [], [], []


# ---------------------------------------------------------------------------
# Gate 1: 設定ベースの lint / test / coverage チェック
# ---------------------------------------------------------------------------

def _get_pre_check_cmd(key: str) -> Optional[List[str]]:
    """PRE_CHECK_COMMANDS から指定キーのコマンドを取得する。未設定/None は None を返す。"""
    cmds = getattr(config, "PRE_CHECK_COMMANDS", {})
    if not isinstance(cmds, dict):
        return None
    val = cmds.get(key)
    return val if isinstance(val, list) and val else None


def check_lint(changed_files: List[str]) -> CheckResult:
    """lint コマンドを実行し、失敗した場合 WARN を返す。
    PRE_CHECK_COMMANDS["lint"] が None の場合はスキップ。
    """
    cmd = _get_pre_check_cmd("lint")
    if cmd is None:
        return [], [], []
    if not changed_files:
        return [], [], []

    try:
        result = subprocess.run(
            cmd + ["--"] + changed_files,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            output = (result.stdout or result.stderr or "").strip()
            return [], [f"lint チェックで問題が検出されました。LLMレビュー前に確認してください。\n{output}"], []
    except subprocess.TimeoutExpired:
        return [], ["lint コマンドがタイムアウトしました（120秒）。スキップします。"], []
    except Exception as e:
        return [], [f"lint コマンドの実行に失敗しました: {e}"], []

    return [], [], ["lint: 問題なし"]


def check_tests_pass() -> CheckResult:
    """テストコマンドを実行し、失敗した場合 BLOCK を返す。
    PRE_CHECK_COMMANDS["test"] が None の場合はスキップ。
    """
    cmd = _get_pre_check_cmd("test")
    if cmd is None:
        return [], [], []

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            output = (result.stdout or result.stderr or "").strip()
            return [f"テストが失敗しています。LLMレビュー前に修正してください。\n{output}"], [], []
    except subprocess.TimeoutExpired:
        return [], ["テストコマンドがタイムアウトしました（300秒）。スキップします。"], []
    except Exception as e:
        return [], [f"テストコマンドの実行に失敗しました: {e}"], []

    return [], [], ["test: 全テスト通過"]


def check_coverage() -> CheckResult:
    """coverage コマンドを実行し、閾値を下回った場合 WARN を返す。
    PRE_CHECK_COMMANDS["coverage"] が None の場合はスキップ。
    出力の最終 TOTAL 行から "XX%" を parse する。
    """
    cmd = _get_pre_check_cmd("coverage")
    if cmd is None:
        return [], [], []

    threshold = float(getattr(config, "COVERAGE_THRESHOLD", 80.0))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            output = (result.stdout or result.stderr or "").strip()
            return [], [f"coverage コマンドが非ゼロで終了しました。出力を確認してください。\n{output}"], []
        output = (result.stdout or result.stderr or "").strip()

        # "TOTAL ... XX.X%" 形式の行を探す（小数点以下も考慮）
        coverage_pct: Optional[float] = None
        for line in reversed(output.splitlines()):
            m = re.search(r'\bTOTAL\b.*?(\d+(?:\.\d+)?)%', line)
            if m:
                coverage_pct = float(m.group(1))
                break

        if coverage_pct is None:
            return [], [f"coverage の計測結果を parse できませんでした。出力を確認してください。\n{output}"], []

        if coverage_pct < threshold:
            return [], [
                f"テストカバレッジが {coverage_pct:.1f}% で閾値 {threshold:.1f}% を下回っています。"
                "カバレッジの向上を検討してください。"
            ], []
    except subprocess.TimeoutExpired:
        return [], ["coverage コマンドがタイムアウトしました（300秒）。スキップします。"], []
    except Exception as e:
        return [], [f"coverage コマンドの実行に失敗しました: {e}"], []

    return [], [], [f"coverage: {coverage_pct:.1f}%（閾値 {threshold:.1f}% 以上）"]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_all_checks(diff_text: str, changed_files: List[str]) -> PreCheckResult:
    """全ルールベースチェックを実行して結果を返す。"""
    all_issues: List[str] = []
    all_warnings: List[str] = []
    all_passed: List[str] = []

    checks = [
        lambda: check_empty_diff(diff_text),
        lambda: check_conflict_markers(diff_text),
        lambda: check_only_excluded_files(changed_files),
        lambda: check_secrets(diff_text),
        lambda: check_large_single_file_change(diff_text),
        lambda: check_todo_fixme(diff_text),
        lambda: check_python_syntax(changed_files),
        lambda: check_typescript_syntax(changed_files),
        lambda: check_missing_tests(changed_files),
        lambda: check_assert_less_tests(changed_files),
        lambda: check_skipped_tests(changed_files),
        lambda: check_lint(changed_files),
        lambda: check_tests_pass(),
        lambda: check_coverage(),
    ]

    for check_fn in checks:
        try:
            issues, warnings, passed = check_fn()
            all_issues.extend(issues)
            all_warnings.extend(warnings)
            all_passed.extend(passed)
            if all_issues:
                # BLOCK条件が検出されたら残りのチェックをスキップ
                break
        except Exception as e:
            print(f"[WARN] pre_check_service: チェック中にエラーが発生しました: {e}", file=sys.stderr)

    return PreCheckResult(blocking_issues=all_issues, warnings=all_warnings, passed_checks=all_passed)
