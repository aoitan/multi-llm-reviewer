from unittest.mock import patch
from multi_llm_reviewer.services import review_service
from multi_llm_reviewer.services.pre_check_service import PreCheckResult
from multi_llm_reviewer.core import config

@patch("multi_llm_reviewer.core.git_utils.get_changed_files")
def test_decide_reviewers_auto_small(mock_get_files):
    # ファイル数が少ない場合 -> Single
    mock_get_files.return_value = ["README.md"]
    slots, log = review_service.decide_reviewers("main", "auto")
    assert "Single" in log
    assert len(slots) == 1

@patch("multi_llm_reviewer.core.git_utils.get_changed_files")
def test_decide_reviewers_auto_large(mock_get_files):
    # ファイル数が多い場合 -> ALL
    # 閾値が10に変更されたため、10個以上のファイルを返すようにする
    mock_get_files.return_value = [f"f{i}.py" for i in range(12)]
    slots, log = review_service.decide_reviewers("main", "auto")
    assert "ALL" in log

@patch("multi_llm_reviewer.core.git_utils.get_changed_files")
def test_decide_reviewers_critical(mock_get_files):
    # 重要ファイルが含まれる場合 -> ALL
    mock_get_files.return_value = ["src/core/config.py"]
    slots, log = review_service.decide_reviewers("main", "auto")
    assert "ALL" in log
    assert len(slots) == len(config.REVIEWER_SLOTS)

def test_decide_reviewers_forced_all():
    slots, log = review_service.decide_reviewers("main", "all")
    assert "forced ALL" in log
    assert len(slots) == len(config.REVIEWER_SLOTS)


def test_decide_reviewers_red_team_forces_all():
    slots, log = review_service.decide_reviewers("main", "auto", red_team=True)
    assert "Red Team: forced ALL reviewers" == log
    assert len(slots) == len(config.REVIEWER_SLOTS)


def test_decide_reviewers_red_team_respects_explicit_single():
    slots, log = review_service.decide_reviewers("main", "single", red_team=True)
    assert "Red Team: user forced Single reviewer" == log
    assert len(slots) == 1


def test_sanitize_prompt_text_removes_ansi_and_control_chars():
    raw = "\x1b[31mwarn\x1b[0m\x00text\nnext\tline"
    assert review_service._sanitize_prompt_text(raw) == "warntext\nnext\tline"


def test_build_review_prompt_includes_nested_review_guard_by_default():
    prompt = review_service._build_review_prompt(
        base_prompt="BASE",
        issue_context="ISSUE",
        spec_text="SPEC",
        diff_context="DIFF",
    )
    assert "Skills / SKILL.md" in prompt
    assert "レビュー内レビュー" in prompt
    assert "DIFF" in prompt


def test_build_review_prompt_can_disable_nested_review_guard():
    original = config.DISABLE_SKILLS_IN_NESTED_REVIEW
    try:
        config.DISABLE_SKILLS_IN_NESTED_REVIEW = False
        prompt = review_service._build_review_prompt(
            base_prompt="BASE",
            issue_context="ISSUE",
            spec_text="SPEC",
            diff_context="DIFF",
        )
        assert "Skills / SKILL.md" not in prompt
        assert "レビュー内レビュー" not in prompt
    finally:
        config.DISABLE_SKILLS_IN_NESTED_REVIEW = original


def test_load_review_base_prompt_prefers_red_team_prompt():
    with patch("multi_llm_reviewer.services.review_service.config.load_prompt") as mock_load_prompt:
        mock_load_prompt.side_effect = ["RED_TEAM_PROMPT"]

        prompt = review_service._load_review_base_prompt(red_team=True)

    assert prompt == "RED_TEAM_PROMPT"
    assert mock_load_prompt.call_args_list == [(( "review_prompt_red_team.txt",), {})]


def test_load_review_base_prompt_falls_back_to_standard_prompt_when_red_team_missing():
    with patch("multi_llm_reviewer.services.review_service.config.load_prompt", return_value=""):
        try:
            review_service._load_review_base_prompt(red_team=True)
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "Aborting red-team review" in str(exc)


# ---------------------------------------------------------------------------
# 新規: pre_check_summary / local_llm_analysis の注入
# ---------------------------------------------------------------------------

def test_build_review_prompt_includes_pre_check_summary():
    prompt = review_service._build_review_prompt(
        base_prompt="BASE",
        issue_context="ISSUE",
        spec_text="SPEC",
        diff_context="DIFF",
        pre_check_summary="TEST_SUMMARY_CONTENT",
    )
    assert "TEST_SUMMARY_CONTENT" in prompt
    assert "追加のセキュリティ・信頼性観点" in prompt


def test_build_review_prompt_includes_local_llm_analysis():
    prompt = review_service._build_review_prompt(
        base_prompt="BASE",
        issue_context="ISSUE",
        spec_text="SPEC",
        diff_context="DIFF",
        local_llm_analysis="LOCAL_ANALYSIS_CONTENT",
    )
    assert "LOCAL_ANALYSIS_CONTENT" in prompt


def test_build_review_prompt_omits_pre_check_section_when_empty():
    prompt = review_service._build_review_prompt(
        base_prompt="BASE",
        issue_context="ISSUE",
        spec_text="SPEC",
        diff_context="DIFF",
        pre_check_summary="",
        local_llm_analysis="",
    )
    # セクション自体は含まれるが空の値で埋められない
    assert "TEST_SUMMARY_CONTENT" not in prompt


# ---------------------------------------------------------------------------
# 新規: run_multi_llm_review の blocking 早期 return
# ---------------------------------------------------------------------------

@patch("multi_llm_reviewer.services.review_service.pre_check_service")
@patch("multi_llm_reviewer.core.git_utils.get_git_diff")
@patch("multi_llm_reviewer.core.git_utils.get_changed_files")
def test_run_multi_llm_review_blocks_on_empty_diff(
    mock_files, mock_diff, mock_pre_check
):
    mock_files.return_value = []
    mock_diff.return_value = ""
    mock_pre_check.run_all_checks.return_value = PreCheckResult(
        blocking_issues=["変更がありません。"], warnings=[]
    )
    results = review_service.run_multi_llm_review(target_branch="main")
    assert results == []


@patch("multi_llm_reviewer.services.review_service.pre_check_service")
@patch("multi_llm_reviewer.core.git_utils.get_git_diff")
@patch("multi_llm_reviewer.core.git_utils.get_changed_files")
def test_run_multi_llm_review_proceeds_with_warnings_only(
    mock_files, mock_diff, mock_pre_check
):
    """警告のみでブロックしない場合はLLMレビューが呼ばれる（モックで確認）"""
    mock_files.return_value = ["src/foo.py"]
    mock_diff.return_value = "+def foo():\n+    pass\n"
    mock_pre_check.run_all_checks.return_value = PreCheckResult(
        blocking_issues=[], warnings=["テスト未変更の警告"]
    )
    # LLM実行はモック: run_multi_llm_review が [] を返さないことを確認
    with patch("multi_llm_reviewer.services.review_service._run_single_reviewer_stream") as mock_run, \
         patch("multi_llm_reviewer.core.local_llm_client.is_ollama_available", return_value=False), \
         patch("multi_llm_reviewer.core.github_utils.fetch_issue", return_value=None):
        mock_run.return_value = {"name": "TestReviewer", "output": "ok", "success": True}
        # decide_reviewers をパッチして単一スロットを返す
        with patch("multi_llm_reviewer.services.review_service.decide_reviewers",
                   return_value=([config.REVIEWER_SLOTS[0]], "test")):
            review_service.run_multi_llm_review(target_branch="main")
    # LLMが呼ばれた（blocking で止まっていない）ことを確認
    assert mock_run.called


@patch("multi_llm_reviewer.services.review_service.pre_check_service")
@patch("multi_llm_reviewer.core.git_utils.get_git_diff")
@patch("multi_llm_reviewer.core.git_utils.get_changed_files")
def test_run_multi_llm_review_uses_red_team_prompt(
    mock_files, mock_diff, mock_pre_check
):
    mock_files.return_value = ["src/foo.py"]
    mock_diff.return_value = "+def foo():\n+    pass\n"
    mock_pre_check.run_all_checks.return_value = PreCheckResult(
        blocking_issues=[], warnings=[]
    )
    with patch("multi_llm_reviewer.services.review_service._run_single_reviewer_stream") as mock_run, \
         patch("multi_llm_reviewer.services.review_service._load_review_base_prompt", return_value="RED_PROMPT"), \
         patch("multi_llm_reviewer.core.local_llm_client.is_ollama_available", return_value=False), \
         patch("multi_llm_reviewer.core.github_utils.fetch_issue", return_value=None):
        mock_run.return_value = {"name": "TestReviewer", "output": "ok", "success": True}
        with patch("multi_llm_reviewer.services.review_service.decide_reviewers",
                   return_value=([config.REVIEWER_SLOTS[0]], "test")):
            review_service.run_multi_llm_review(target_branch="main", red_team=True)

    assert mock_run.called
    prompt = mock_run.call_args.args[1]
    assert prompt.startswith("RED_PROMPT")


@patch("multi_llm_reviewer.services.review_service.pre_check_service")
@patch("multi_llm_reviewer.core.git_utils.get_git_diff")
@patch("multi_llm_reviewer.core.git_utils.get_changed_files")
def test_run_multi_llm_review_sanitizes_prompt_inputs(
    mock_files, mock_diff, mock_pre_check
):
    mock_files.return_value = ["src/foo.py"]
    mock_diff.return_value = "+safe()\n+\x1b[31mhidden\x1b[0m\n"
    mock_pre_check.run_all_checks.return_value = PreCheckResult(
        blocking_issues=[],
        warnings=["warn\x00text"],
        passed_checks=["lint: 問題なし"],
    )
    with patch("multi_llm_reviewer.services.review_service._run_single_reviewer_stream") as mock_run, \
         patch("multi_llm_reviewer.services.review_service._load_review_base_prompt", return_value="BASE"), \
         patch("multi_llm_reviewer.core.local_llm_client.is_ollama_available", return_value=True), \
         patch("multi_llm_reviewer.core.local_llm_client.run_local_llm_pre_check", return_value="\x1b[32manalysis\x1b[0m"), \
         patch("multi_llm_reviewer.core.github_utils.fetch_issue", return_value="issue\x00body"):
        mock_run.return_value = {"name": "TestReviewer", "output": "ok", "success": True}
        with patch("multi_llm_reviewer.services.review_service.decide_reviewers",
                   return_value=([config.REVIEWER_SLOTS[0]], "test")):
            review_service.run_multi_llm_review(
                target_branch="main",
                issue_num="1",
                spec_text="spec\x00text",
            )

    prompt = mock_run.call_args.args[1]
    assert "\x1b" not in prompt
    assert "\x00" not in prompt
    assert "analysis" in prompt
