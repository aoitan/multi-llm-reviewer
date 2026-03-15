"""pre_check_service のユニットテスト"""
import textwrap
from unittest.mock import patch, MagicMock
import pytest
from multi_llm_reviewer.services import pre_check_service
from multi_llm_reviewer.services.pre_check_service import PreCheckResult


# ---------------------------------------------------------------------------
# PreCheckResult
# ---------------------------------------------------------------------------

class TestPreCheckResult:
    def test_has_blocking_true_when_blocking_issues_present(self):
        result = PreCheckResult(blocking_issues=["error"], warnings=[])
        assert result.has_blocking is True

    def test_has_blocking_false_when_no_blocking_issues(self):
        result = PreCheckResult(blocking_issues=[], warnings=["warn"])
        assert result.has_blocking is False

    def test_summary_includes_blocking_and_warnings(self):
        result = PreCheckResult(blocking_issues=["BLOCK1"], warnings=["WARN1"])
        assert "BLOCK1" in result.summary
        assert "WARN1" in result.summary

    def test_summary_empty_when_no_issues(self):
        result = PreCheckResult(blocking_issues=[], warnings=[])
        assert result.summary == ""

    def test_summary_includes_passed_checks(self):
        """passed_checks が summary に ✅ で含まれること。"""
        result = PreCheckResult(blocking_issues=[], warnings=[], passed_checks=["lint: 問題なし"])
        assert "lint: 問題なし" in result.summary
        assert "✅" in result.summary

    def test_summary_nonempty_when_only_passed_checks(self):
        """blocking/warnings がなく passed_checks だけでも summary が返ること。"""
        result = PreCheckResult(blocking_issues=[], warnings=[], passed_checks=["test: 全テスト通過"])
        assert result.summary != ""

    def test_summary_ordering_block_warn_pass(self):
        """summary の順序: BLOCK → WARN → PASS。"""
        result = PreCheckResult(
            blocking_issues=["B"],
            warnings=["W"],
            passed_checks=["P"],
        )
        s = result.summary
        assert s.index("B") < s.index("W") < s.index("P")


# ---------------------------------------------------------------------------
# check_empty_diff
# ---------------------------------------------------------------------------

class TestCheckEmptyDiff:
    def test_blocks_on_empty_string(self):
        issues, warnings, _ = pre_check_service.check_empty_diff("")
        assert len(issues) == 1
        assert len(warnings) == 0

    def test_blocks_on_whitespace_only(self):
        issues, warnings, _ = pre_check_service.check_empty_diff("   \n\n  ")
        assert len(issues) == 1

    def test_blocks_on_no_changes_detected_sentinel(self):
        issues, warnings, _ = pre_check_service.check_empty_diff("(No changes detected)")
        assert len(issues) == 1

    def test_passes_on_real_diff(self):
        diff = "+def hello():\n+    pass\n"
        issues, warnings, _ = pre_check_service.check_empty_diff(diff)
        assert len(issues) == 0


# ---------------------------------------------------------------------------
# check_conflict_markers
# ---------------------------------------------------------------------------

class TestCheckConflictMarkers:
    def test_blocks_on_head_marker(self):
        diff = "+<<<<<<< HEAD\n+some code\n+=======\n"
        issues, warnings, _ = pre_check_service.check_conflict_markers(diff)
        assert len(issues) == 1

    def test_blocks_on_end_marker(self):
        diff = "+>>>>>>> feature-branch\n"
        issues, warnings, _ = pre_check_service.check_conflict_markers(diff)
        assert len(issues) == 1

    def test_passes_on_clean_diff(self):
        diff = "+def foo():\n+    return 1\n"
        issues, warnings, _ = pre_check_service.check_conflict_markers(diff)
        assert len(issues) == 0

    def test_passes_when_marker_in_minus_line(self):
        # 削除行はコンフリクトマーカーとして扱わない
        diff = "-<<<<<<< HEAD\n"
        issues, warnings, _ = pre_check_service.check_conflict_markers(diff)
        assert len(issues) == 0

    def test_passes_on_divider_line_not_conflict(self):
        # ================== のような区切り線はコンフリクトマーカーではない
        diff = "+==================\n"
        issues, warnings, _ = pre_check_service.check_conflict_markers(diff)
        assert len(issues) == 0

    def test_blocks_on_exact_equals_separator(self):
        # 正確に7つの = だけの行はコンフリクトマーカー
        diff = "+=======\n"
        issues, warnings, _ = pre_check_service.check_conflict_markers(diff)
        assert len(issues) == 1


# ---------------------------------------------------------------------------
# check_only_excluded_files
# ---------------------------------------------------------------------------

class TestCheckOnlyExcludedFiles:
    def test_blocks_when_only_lockfiles(self):
        files = ["package-lock.json", "yarn.lock"]
        issues, warnings, _ = pre_check_service.check_only_excluded_files(files)
        assert len(issues) == 1

    def test_blocks_when_only_binaries(self):
        files = ["assets/logo.png", "icons/icon.svg"]
        issues, warnings, _ = pre_check_service.check_only_excluded_files(files)
        assert len(issues) == 1

    def test_passes_when_source_file_present(self):
        files = ["package-lock.json", "src/main.py"]
        issues, warnings, _ = pre_check_service.check_only_excluded_files(files)
        assert len(issues) == 0

    def test_passes_on_empty_list(self):
        # ファイルなし = 差分ゼロチェックで捕捉されるべきなのでここはスルー
        issues, warnings, _ = pre_check_service.check_only_excluded_files([])
        assert len(issues) == 0


# ---------------------------------------------------------------------------
# check_secrets
# ---------------------------------------------------------------------------

class TestCheckSecrets:
    def test_blocks_on_api_key(self):
        diff = '+API_KEY = "sk-abcdefghijklmnop"\n'
        issues, warnings, _ = pre_check_service.check_secrets(diff)
        assert len(issues) == 1

    def test_blocks_on_password(self):
        diff = '+password = "supersecret123"\n'
        issues, warnings, _ = pre_check_service.check_secrets(diff)
        assert len(issues) == 1

    def test_blocks_on_aws_access_key(self):
        diff = '+aws_access_key_id = "AKIAIOSFODNN7EXAMPLE"\n'
        issues, warnings, _ = pre_check_service.check_secrets(diff)
        assert len(issues) == 1

    def test_passes_on_clean_diff(self):
        diff = '+def get_user(user_id: int):\n+    return db.get(user_id)\n'
        issues, warnings, _ = pre_check_service.check_secrets(diff)
        assert len(issues) == 0

    def test_passes_on_placeholder_value(self):
        # 短い値（8文字未満）はスキップ
        diff = '+API_KEY = "test"\n'
        issues, warnings, _ = pre_check_service.check_secrets(diff)
        assert len(issues) == 0

    def test_passes_on_minus_line(self):
        # 削除行は無視
        diff = '-API_KEY = "sk-abcdefghijklmnop"\n'
        issues, warnings, _ = pre_check_service.check_secrets(diff)
        assert len(issues) == 0

    def test_passes_on_test_file(self):
        # テストファイルのテストデータは無視
        diff = 'diff --git a/tests/test_foo.py b/tests/test_foo.py\n'
        diff += '+        diff = \'+API_KEY = "sk-abcdefghijklmnop"\\n\'\n'
        issues, warnings, _ = pre_check_service.check_secrets(diff)
        assert len(issues) == 0


# ---------------------------------------------------------------------------
# check_large_single_file_change
# ---------------------------------------------------------------------------

class TestCheckLargeSingleFileChange:
    def _make_diff(self, filename: str, added_lines: int) -> str:
        header = f"diff --git a/{filename} b/{filename}\n--- a/{filename}\n+++ b/{filename}\n"
        lines = "".join(f"+line{i}\n" for i in range(added_lines))
        return header + lines

    def test_warns_when_file_exceeds_500_lines(self):
        diff = self._make_diff("src/big.py", 501)
        issues, warnings, _ = pre_check_service.check_large_single_file_change(diff)
        assert len(warnings) == 1
        assert len(issues) == 0

    def test_passes_when_file_under_500_lines(self):
        diff = self._make_diff("src/small.py", 100)
        issues, warnings, _ = pre_check_service.check_large_single_file_change(diff)
        assert len(warnings) == 0

    def test_warns_only_for_large_file_in_multi_file_diff(self):
        diff = self._make_diff("src/big.py", 600) + self._make_diff("src/small.py", 10)
        issues, warnings, _ = pre_check_service.check_large_single_file_change(diff)
        assert len(warnings) == 1


# ---------------------------------------------------------------------------
# check_todo_fixme
# ---------------------------------------------------------------------------

class TestCheckTodoFixme:
    def test_warns_on_todo_in_added_line(self):
        diff = "+# TODO: implement this later\n"
        issues, warnings, _ = pre_check_service.check_todo_fixme(diff)
        assert len(warnings) == 1

    def test_warns_on_fixme_in_added_line(self):
        diff = "+# FIXME: broken logic\n"
        issues, warnings, _ = pre_check_service.check_todo_fixme(diff)
        assert len(warnings) == 1

    def test_warns_on_hack_in_added_line(self):
        diff = "+# HACK: dirty workaround\n"
        issues, warnings, _ = pre_check_service.check_todo_fixme(diff)
        assert len(warnings) == 1

    def test_passes_on_todo_in_removed_line(self):
        diff = "-# TODO: old todo\n"
        issues, warnings, _ = pre_check_service.check_todo_fixme(diff)
        assert len(warnings) == 0

    def test_passes_on_clean_diff(self):
        diff = "+def process():\n+    return True\n"
        issues, warnings, _ = pre_check_service.check_todo_fixme(diff)
        assert len(warnings) == 0

    def test_passes_on_todo_in_variable_name(self):
        """TODO_LIST などの変数名での誤検知がないこと（単語境界チェック）。"""
        diff = "+TODO_LIST = []\n+todoable_method = True\n"
        issues, warnings, _ = pre_check_service.check_todo_fixme(diff)
        assert len(warnings) == 0


# ---------------------------------------------------------------------------
# check_python_syntax
# ---------------------------------------------------------------------------

class TestCheckPythonSyntax:
    def test_blocks_on_syntax_error(self, tmp_path):
        bad_file = tmp_path / "bad.py"
        bad_file.write_text("def foo(\n    pass\n")
        issues, warnings, _ = pre_check_service.check_python_syntax([str(bad_file)])
        assert len(issues) == 1

    def test_passes_on_valid_python(self, tmp_path):
        good_file = tmp_path / "good.py"
        good_file.write_text("def foo():\n    pass\n")
        issues, warnings, _ = pre_check_service.check_python_syntax([str(good_file)])
        assert len(issues) == 0

    def test_ignores_non_python_files(self, tmp_path):
        ts_file = tmp_path / "app.ts"
        ts_file.write_text("const x: number = 1;\n")
        issues, warnings, _ = pre_check_service.check_python_syntax([str(ts_file)])
        assert len(issues) == 0

    def test_passes_when_file_not_found(self):
        # 存在しないファイルは無視（削除されたファイルの可能性）
        issues, warnings, _ = pre_check_service.check_python_syntax(["/nonexistent/path/file.py"])
        assert len(issues) == 0


# ---------------------------------------------------------------------------
# check_typescript_syntax
# ---------------------------------------------------------------------------

class TestCheckTypescriptSyntax:
    def test_skips_when_no_ts_files(self):
        issues, warnings, _ = pre_check_service.check_typescript_syntax(["src/main.py"])
        assert len(issues) == 0
        assert len(warnings) == 0

    def test_warns_when_ts_files_present_but_tsc_not_found(self):
        with patch("shutil.which", return_value=None), \
             patch("multi_llm_reviewer.services.pre_check_service._find_tsc", return_value=None):
            issues, warnings, _ = pre_check_service.check_typescript_syntax(["src/app.ts"])
        assert len(issues) == 0
        assert len(warnings) == 1  # tsc が見つからない警告

    def test_blocks_on_ts_syntax_error(self, tmp_path):
        ts_file = tmp_path / "bad.ts"
        ts_file.write_text("const x = ;\n")
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "bad.ts(1,11): error TS1005: ';' expected."
        mock_result.stderr = ""
        with patch("multi_llm_reviewer.services.pre_check_service._find_tsc", return_value="tsc"), \
             patch("subprocess.run", return_value=mock_result):
            issues, warnings, _ = pre_check_service.check_typescript_syntax([str(ts_file)])
        assert len(issues) == 1  # TS1xxx → BLOCK
        assert len(warnings) == 0

    def test_warns_on_ts_type_error_not_blocks(self, tmp_path):
        """TS2xxx（型エラー）はBLOCKではなくWARNになること。"""
        ts_file = tmp_path / "typed.ts"
        ts_file.write_text("const x: number = 'hello';\n")
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "typed.ts(1,7): error TS2322: Type 'string' is not assignable to type 'number'."
        mock_result.stderr = ""
        with patch("multi_llm_reviewer.services.pre_check_service._find_tsc", return_value="tsc"), \
             patch("subprocess.run", return_value=mock_result):
            issues, warnings, _ = pre_check_service.check_typescript_syntax([str(ts_file)])
        assert len(issues) == 0  # TS2xxx → not BLOCK
        assert len(warnings) == 1  # → WARN

    def test_warns_on_tsc_timeout(self, tmp_path):
        """tsc タイムアウト時はWARNになること。"""
        import subprocess as sp
        ts_file = tmp_path / "slow.ts"
        ts_file.write_text("const x = 1;\n")
        with patch("multi_llm_reviewer.services.pre_check_service._find_tsc", return_value="tsc"), \
             patch("subprocess.run", side_effect=sp.TimeoutExpired("tsc", 120)):
            issues, warnings, _ = pre_check_service.check_typescript_syntax([str(ts_file)])
        assert len(issues) == 0
        assert len(warnings) == 1

    def test_passes_on_valid_ts(self, tmp_path):
        ts_file = tmp_path / "good.ts"
        ts_file.write_text("const x: number = 1;\n")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        with patch("multi_llm_reviewer.services.pre_check_service._find_tsc", return_value="tsc"), \
             patch("subprocess.run", return_value=mock_result):
            issues, warnings, _ = pre_check_service.check_typescript_syntax([str(ts_file)])
        assert len(issues) == 0
        assert len(warnings) == 0


# ---------------------------------------------------------------------------
# check_missing_tests
# ---------------------------------------------------------------------------

class TestCheckMissingTests:
    def test_warns_when_src_changed_without_test(self):
        changed = ["src/multi_llm_reviewer/services/foo_service.py"]
        issues, warnings, _ = pre_check_service.check_missing_tests(changed)
        assert len(warnings) == 1

    def test_passes_when_both_src_and_test_changed(self):
        changed = [
            "src/multi_llm_reviewer/services/foo_service.py",
            "tests/test_services/test_foo_service.py",
        ]
        issues, warnings, _ = pre_check_service.check_missing_tests(changed)
        assert len(warnings) == 0

    def test_passes_when_only_test_changed(self):
        changed = ["tests/test_services/test_foo.py"]
        issues, warnings, _ = pre_check_service.check_missing_tests(changed)
        assert len(warnings) == 0

    def test_passes_when_only_non_python_changed(self):
        changed = ["src/app.ts", "src/components/Button.tsx"]
        issues, warnings, _ = pre_check_service.check_missing_tests(changed)
        assert len(warnings) == 0


# ---------------------------------------------------------------------------
# check_assert_less_tests
# ---------------------------------------------------------------------------

class TestCheckAssertLessTests:
    def test_warns_on_test_func_without_assert(self, tmp_path):
        test_file = tmp_path / "test_example.py"
        test_file.write_text(textwrap.dedent("""\
            def test_something():
                x = 1 + 1
        """))
        issues, warnings, _ = pre_check_service.check_assert_less_tests([str(test_file)])
        assert len(warnings) == 1

    def test_passes_on_test_func_with_assert(self, tmp_path):
        test_file = tmp_path / "test_example.py"
        test_file.write_text(textwrap.dedent("""\
            def test_something():
                assert 1 + 1 == 2
        """))
        issues, warnings, _ = pre_check_service.check_assert_less_tests([str(test_file)])
        assert len(warnings) == 0

    def test_passes_on_test_func_with_pytest_raises(self, tmp_path):
        test_file = tmp_path / "test_example.py"
        test_file.write_text(textwrap.dedent("""\
            import pytest
            def test_raises():
                with pytest.raises(ValueError):
                    raise ValueError()
        """))
        issues, warnings, _ = pre_check_service.check_assert_less_tests([str(test_file)])
        assert len(warnings) == 0

    def test_ignores_non_test_files(self, tmp_path):
        src_file = tmp_path / "service.py"
        src_file.write_text("def do_something():\n    x = 1\n")
        issues, warnings, _ = pre_check_service.check_assert_less_tests([str(src_file)])
        assert len(warnings) == 0

    def test_warns_on_class_method_without_assert(self, tmp_path):
        """クラスベースのテストメソッドでアサーションなしを検出できること。"""
        test_file = tmp_path / "test_example.py"
        test_file.write_text(textwrap.dedent("""\
            class TestFoo:
                def test_bar(self):
                    x = 1
        """))
        issues, warnings, _ = pre_check_service.check_assert_less_tests([str(test_file)])
        assert len(warnings) == 1

    def test_passes_on_class_method_with_assert(self, tmp_path):
        """クラスベースのテストメソッドでアサーションありは警告しないこと。"""
        test_file = tmp_path / "test_example.py"
        test_file.write_text(textwrap.dedent("""\
            class TestFoo:
                def test_bar(self):
                    assert 1 + 1 == 2
        """))
        issues, warnings, _ = pre_check_service.check_assert_less_tests([str(test_file)])
        assert len(warnings) == 0

    def test_no_false_positive_on_def_test_in_string_literal(self, tmp_path):
        """文字列リテラル内の def test_ は誤検知しないこと（AST解析）。"""
        test_file = tmp_path / "test_example.py"
        test_file.write_text(textwrap.dedent("""\
            import textwrap
            def test_writes_test_file(tmp_path):
                content = textwrap.dedent(\"\"\"
                    def test_something():
                        x = 1
                \"\"\")
                (tmp_path / "t.py").write_text(content)
                assert (tmp_path / "t.py").exists()
        """))
        issues, warnings, _ = pre_check_service.check_assert_less_tests([str(test_file)])
        assert len(warnings) == 0  # 文字列内の def test_ は無視される


# ---------------------------------------------------------------------------
# check_skipped_tests
# ---------------------------------------------------------------------------

class TestCheckSkippedTests:
    def test_warns_when_too_many_skips(self, tmp_path):
        test_file = tmp_path / "test_example.py"
        test_file.write_text(textwrap.dedent("""\
            import pytest
            @pytest.mark.skip
            def test_a(): assert True
            @pytest.mark.skip
            def test_b(): assert True
            @pytest.mark.skip
            def test_c(): assert True
            @pytest.mark.skip
            def test_d(): assert True
        """))
        issues, warnings, _ = pre_check_service.check_skipped_tests([str(test_file)], threshold=3)
        assert len(warnings) == 1

    def test_passes_when_skips_under_threshold(self, tmp_path):
        test_file = tmp_path / "test_example.py"
        test_file.write_text(textwrap.dedent("""\
            import pytest
            @pytest.mark.skip
            def test_a(): assert True
        """))
        issues, warnings, _ = pre_check_service.check_skipped_tests([str(test_file)], threshold=3)
        assert len(warnings) == 0

    def test_ignores_non_test_files(self, tmp_path):
        src_file = tmp_path / "service.py"
        src_file.write_text("@some_decorator\ndef foo(): pass\n")
        issues, warnings, _ = pre_check_service.check_skipped_tests([str(src_file)], threshold=3)
        assert len(warnings) == 0

    def test_no_false_positive_on_skip_in_string_literal(self, tmp_path):
        """文字列リテラル内の @pytest.mark.skip は誤検知しないこと（AST解析）。"""
        test_file = tmp_path / "test_example.py"
        test_file.write_text(textwrap.dedent("""\
            def test_generates_skip_code(tmp_path):
                code = '@pytest.mark.skip\\ndef test_x(): pass'
                (tmp_path / "t.py").write_text(code)
                assert (tmp_path / "t.py").exists()
        """))
        issues, warnings, _ = pre_check_service.check_skipped_tests([str(test_file)], threshold=1)
        assert len(warnings) == 0  # 文字列内の @skip は無視される


# ---------------------------------------------------------------------------
# run_all_checks
# ---------------------------------------------------------------------------

class TestRunAllChecks:
    def test_returns_pre_check_result(self):
        result = pre_check_service.run_all_checks("+ some diff", ["src/foo.py"])
        assert isinstance(result, PreCheckResult)

    def test_blocking_on_empty_diff(self):
        result = pre_check_service.run_all_checks("", [])
        assert result.has_blocking is True

    def test_blocking_on_conflict_markers(self):
        diff = "+<<<<<<< HEAD\n+code\n+=======\n+other\n+>>>>>>> branch\n"
        result = pre_check_service.run_all_checks(diff, ["src/foo.py"])
        assert result.has_blocking is True

    def test_no_issues_on_clean_diff(self, tmp_path):
        good_py = tmp_path / "good.py"
        good_py.write_text("def foo():\n    pass\n")
        diff = "+def foo():\n+    pass\n"
        result = pre_check_service.run_all_checks(diff, [str(good_py)])
        assert result.has_blocking is False


# ---------------------------------------------------------------------------
# check_lint
# ---------------------------------------------------------------------------

class TestCheckLint:
    def test_skips_when_command_not_configured(self):
        """PRE_CHECK_COMMANDS['lint'] が None の場合はスキップ（issues/warnings 空）。"""
        from multi_llm_reviewer.core import config as cfg
        original = getattr(cfg, "PRE_CHECK_COMMANDS", None)
        cfg.PRE_CHECK_COMMANDS = {"lint": None, "test": None, "coverage": None}
        try:
            issues, warnings, passed = pre_check_service.check_lint(["src/foo.py"])
            assert issues == []
            assert warnings == []
        finally:
            cfg.PRE_CHECK_COMMANDS = original

    def test_warns_on_lint_failure(self):
        """lint コマンドが exit code 1 を返した場合 WARN が返ること。"""
        from multi_llm_reviewer.core import config as cfg
        original = getattr(cfg, "PRE_CHECK_COMMANDS", None)
        cfg.PRE_CHECK_COMMANDS = {"lint": ["ruff", "check"], "test": None, "coverage": None}
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "src/foo.py:1:1: E302 expected 2 blank lines"
        mock_result.stderr = ""
        try:
            with patch("subprocess.run", return_value=mock_result):
                issues, warnings, passed = pre_check_service.check_lint(["src/foo.py"])
            assert issues == []
            assert len(warnings) == 1
        finally:
            cfg.PRE_CHECK_COMMANDS = original

    def test_passes_on_lint_success(self):
        """lint コマンドが exit code 0 を返した場合は passed_checks が返ること。"""
        from multi_llm_reviewer.core import config as cfg
        original = getattr(cfg, "PRE_CHECK_COMMANDS", None)
        cfg.PRE_CHECK_COMMANDS = {"lint": ["ruff", "check"], "test": None, "coverage": None}
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        try:
            with patch("subprocess.run", return_value=mock_result):
                issues, warnings, passed = pre_check_service.check_lint(["src/foo.py"])
            assert issues == []
            assert warnings == []
            assert len(passed) == 1
            assert "lint" in passed[0]
        finally:
            cfg.PRE_CHECK_COMMANDS = original

    def test_passes_separator_before_files(self):
        """変更ファイルのパスが -- の後に渡されること（オプション誤認防止）。"""
        from multi_llm_reviewer.core import config as cfg
        original = getattr(cfg, "PRE_CHECK_COMMANDS", None)
        cfg.PRE_CHECK_COMMANDS = {"lint": ["ruff", "check"], "test": None, "coverage": None}
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        captured_cmd = {}
        def mock_run(cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            return mock_result
        try:
            with patch("subprocess.run", side_effect=mock_run):
                pre_check_service.check_lint(["-bad-filename.py"])
            assert "--" in captured_cmd["cmd"]
            assert captured_cmd["cmd"].index("--") < captured_cmd["cmd"].index("-bad-filename.py")
        finally:
            cfg.PRE_CHECK_COMMANDS = original

    def test_warns_on_command_not_found(self):
        """lint コマンドが見つからない場合 WARN が返ること。"""
        from multi_llm_reviewer.core import config as cfg
        original = getattr(cfg, "PRE_CHECK_COMMANDS", None)
        cfg.PRE_CHECK_COMMANDS = {"lint": ["nonexistent-linter"], "test": None, "coverage": None}
        try:
            with patch("subprocess.run", side_effect=FileNotFoundError("not found")):
                issues, warnings, passed = pre_check_service.check_lint(["src/foo.py"])
            assert issues == []
            assert len(warnings) == 1
        finally:
            cfg.PRE_CHECK_COMMANDS = original


# ---------------------------------------------------------------------------
# check_tests_pass
# ---------------------------------------------------------------------------

class TestCheckTestsPass:
    def test_skips_when_command_not_configured(self):
        """PRE_CHECK_COMMANDS['test'] が None の場合はスキップ。"""
        from multi_llm_reviewer.core import config as cfg
        original = getattr(cfg, "PRE_CHECK_COMMANDS", None)
        cfg.PRE_CHECK_COMMANDS = {"lint": None, "test": None, "coverage": None}
        try:
            issues, warnings, passed = pre_check_service.check_tests_pass()
            assert issues == []
            assert warnings == []
        finally:
            cfg.PRE_CHECK_COMMANDS = original

    def test_blocks_on_test_failure(self):
        """テストコマンドが exit code 1 を返した場合 BLOCK が返ること。"""
        from multi_llm_reviewer.core import config as cfg
        original = getattr(cfg, "PRE_CHECK_COMMANDS", None)
        cfg.PRE_CHECK_COMMANDS = {"lint": None, "test": ["pytest"], "coverage": None}
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "FAILED tests/test_foo.py::test_bar"
        mock_result.stderr = ""
        try:
            with patch("subprocess.run", return_value=mock_result):
                issues, warnings, passed = pre_check_service.check_tests_pass()
            assert len(issues) == 1  # BLOCK
            assert warnings == []
        finally:
            cfg.PRE_CHECK_COMMANDS = original

    def test_passes_on_test_success(self):
        """テストコマンドが exit code 0 を返した場合は何も返さないこと。"""
        from multi_llm_reviewer.core import config as cfg
        original = getattr(cfg, "PRE_CHECK_COMMANDS", None)
        cfg.PRE_CHECK_COMMANDS = {"lint": None, "test": ["pytest"], "coverage": None}
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "5 passed in 0.10s"
        mock_result.stderr = ""
        try:
            with patch("subprocess.run", return_value=mock_result):
                issues, warnings, passed = pre_check_service.check_tests_pass()
            assert issues == []
            assert warnings == []
            assert len(passed) == 1
            assert "test" in passed[0]
        finally:
            cfg.PRE_CHECK_COMMANDS = original

    def test_warns_on_command_not_found(self):
        """テストコマンドが見つからない場合 WARN が返ること。"""
        from multi_llm_reviewer.core import config as cfg
        original = getattr(cfg, "PRE_CHECK_COMMANDS", None)
        cfg.PRE_CHECK_COMMANDS = {"lint": None, "test": ["nonexistent-runner"], "coverage": None}
        try:
            with patch("subprocess.run", side_effect=FileNotFoundError("not found")):
                issues, warnings, passed = pre_check_service.check_tests_pass()
            assert issues == []
            assert len(warnings) == 1
        finally:
            cfg.PRE_CHECK_COMMANDS = original


# ---------------------------------------------------------------------------
# check_coverage
# ---------------------------------------------------------------------------

class TestCheckCoverage:
    def test_skips_when_command_not_configured(self):
        """PRE_CHECK_COMMANDS['coverage'] が None の場合はスキップ。"""
        from multi_llm_reviewer.core import config as cfg
        original = getattr(cfg, "PRE_CHECK_COMMANDS", None)
        cfg.PRE_CHECK_COMMANDS = {"lint": None, "test": None, "coverage": None}
        try:
            issues, warnings, passed = pre_check_service.check_coverage()
            assert issues == []
            assert warnings == []
        finally:
            cfg.PRE_CHECK_COMMANDS = original

    def test_warns_when_coverage_below_threshold(self):
        """coverage が閾値未満の場合 WARN が返ること。"""
        from multi_llm_reviewer.core import config as cfg
        orig_cmd = getattr(cfg, "PRE_CHECK_COMMANDS", None)
        orig_thr = getattr(cfg, "COVERAGE_THRESHOLD", None)
        cfg.PRE_CHECK_COMMANDS = {"lint": None, "test": None, "coverage": ["pytest", "--cov"]}
        cfg.COVERAGE_THRESHOLD = 80.0
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "TOTAL    500    200    60%"
        mock_result.stderr = ""
        try:
            with patch("subprocess.run", return_value=mock_result):
                issues, warnings, passed = pre_check_service.check_coverage()
            assert issues == []
            assert len(warnings) == 1
            assert "60" in warnings[0]
        finally:
            cfg.PRE_CHECK_COMMANDS = orig_cmd
            cfg.COVERAGE_THRESHOLD = orig_thr

    def test_passes_when_coverage_meets_threshold(self):
        """coverage が閾値以上の場合は何も返さないこと。"""
        from multi_llm_reviewer.core import config as cfg
        orig_cmd = getattr(cfg, "PRE_CHECK_COMMANDS", None)
        orig_thr = getattr(cfg, "COVERAGE_THRESHOLD", None)
        cfg.PRE_CHECK_COMMANDS = {"lint": None, "test": None, "coverage": ["pytest", "--cov"]}
        cfg.COVERAGE_THRESHOLD = 80.0
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "TOTAL    500    50    90%"
        mock_result.stderr = ""
        try:
            with patch("subprocess.run", return_value=mock_result):
                issues, warnings, passed = pre_check_service.check_coverage()
            assert issues == []
            assert warnings == []
            assert len(passed) == 1
            assert "90" in passed[0]
        finally:
            cfg.PRE_CHECK_COMMANDS = orig_cmd
            cfg.COVERAGE_THRESHOLD = orig_thr

    def test_warns_when_coverage_not_parseable(self):
        """coverage 出力から % が parse できない場合 WARN が返ること。"""
        from multi_llm_reviewer.core import config as cfg
        orig_cmd = getattr(cfg, "PRE_CHECK_COMMANDS", None)
        orig_thr = getattr(cfg, "COVERAGE_THRESHOLD", None)
        cfg.PRE_CHECK_COMMANDS = {"lint": None, "test": None, "coverage": ["pytest", "--cov"]}
        cfg.COVERAGE_THRESHOLD = 80.0
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "no coverage data collected"
        mock_result.stderr = ""
        try:
            with patch("subprocess.run", return_value=mock_result):
                issues, warnings, passed = pre_check_service.check_coverage()
            assert issues == []
            assert len(warnings) == 1
        finally:
            cfg.PRE_CHECK_COMMANDS = orig_cmd
            cfg.COVERAGE_THRESHOLD = orig_thr

    def test_passes_with_decimal_coverage_above_threshold(self):
        """小数点付き coverage（例: 90.5%）が閾値以上なら WARN なし。"""
        from multi_llm_reviewer.core import config as cfg
        orig_cmd = getattr(cfg, "PRE_CHECK_COMMANDS", None)
        orig_thr = getattr(cfg, "COVERAGE_THRESHOLD", None)
        cfg.PRE_CHECK_COMMANDS = {"lint": None, "test": None, "coverage": ["pytest", "--cov"]}
        cfg.COVERAGE_THRESHOLD = 80.0
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "TOTAL    500    45    90.5%"
        mock_result.stderr = ""
        try:
            with patch("subprocess.run", return_value=mock_result):
                issues, warnings, passed = pre_check_service.check_coverage()
            assert issues == []
            assert warnings == []
            assert len(passed) == 1
            assert "90.5" in passed[0]
        finally:
            cfg.PRE_CHECK_COMMANDS = orig_cmd
            cfg.COVERAGE_THRESHOLD = orig_thr

    def test_warns_with_decimal_coverage_below_threshold(self):
        """小数点付き coverage（例: 79.9%）が閾値未満なら WARN が返ること。"""
        from multi_llm_reviewer.core import config as cfg
        orig_cmd = getattr(cfg, "PRE_CHECK_COMMANDS", None)
        orig_thr = getattr(cfg, "COVERAGE_THRESHOLD", None)
        cfg.PRE_CHECK_COMMANDS = {"lint": None, "test": None, "coverage": ["pytest", "--cov"]}
        cfg.COVERAGE_THRESHOLD = 80.0
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "TOTAL    500    100    79.9%"
        mock_result.stderr = ""
        try:
            with patch("subprocess.run", return_value=mock_result):
                issues, warnings, passed = pre_check_service.check_coverage()
            assert issues == []
            assert len(warnings) == 1
        finally:
            cfg.PRE_CHECK_COMMANDS = orig_cmd
            cfg.COVERAGE_THRESHOLD = orig_thr

    def test_warns_on_nonzero_returncode(self):
        """coverage コマンドが非ゼロで終了した場合 WARN が返ること。"""
        from multi_llm_reviewer.core import config as cfg
        orig_cmd = getattr(cfg, "PRE_CHECK_COMMANDS", None)
        orig_thr = getattr(cfg, "COVERAGE_THRESHOLD", None)
        cfg.PRE_CHECK_COMMANDS = {"lint": None, "test": None, "coverage": ["pytest", "--cov"]}
        cfg.COVERAGE_THRESHOLD = 80.0
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "ERROR: some error"
        mock_result.stderr = ""
        try:
            with patch("subprocess.run", return_value=mock_result):
                issues, warnings, passed = pre_check_service.check_coverage()
            assert issues == []
            assert len(warnings) == 1
        finally:
            cfg.PRE_CHECK_COMMANDS = orig_cmd
            cfg.COVERAGE_THRESHOLD = orig_thr

    def test_warns_on_command_not_found(self):
        """coverage コマンドが見つからない場合 WARN が返ること。"""
        from multi_llm_reviewer.core import config as cfg
        orig_cmd = getattr(cfg, "PRE_CHECK_COMMANDS", None)
        orig_thr = getattr(cfg, "COVERAGE_THRESHOLD", None)
        cfg.PRE_CHECK_COMMANDS = {"lint": None, "test": None, "coverage": ["nonexistent"]}
        cfg.COVERAGE_THRESHOLD = 80.0
        try:
            with patch("subprocess.run", side_effect=FileNotFoundError("not found")):
                issues, warnings, passed = pre_check_service.check_coverage()
            assert issues == []
            assert len(warnings) == 1
        finally:
            cfg.PRE_CHECK_COMMANDS = orig_cmd
            cfg.COVERAGE_THRESHOLD = orig_thr
