from unittest.mock import patch

import pytest

from multi_llm_reviewer.cli import review


@patch("multi_llm_reviewer.cli.review.review_service.run_multi_llm_review")
def test_review_cli_passes_red_team_args(mock_run_review):
    mock_run_review.return_value = [{"success": True}]

    with patch("sys.argv", ["llm-review", "--red-team", "--reviewers", "single", "-b", "develop", "-i", "123", "extra", "spec"]):
        with pytest.raises(SystemExit) as exc_info:
            review.main()

    assert exc_info.value.code == 0
    mock_run_review.assert_called_once_with(
        target_branch="develop",
        issue_num="123",
        mode="single",
        spec_text="extra spec",
        red_team=True,
    )


@patch("multi_llm_reviewer.cli.review.review_service.run_multi_llm_review")
def test_review_cli_exits_nonzero_on_failure(mock_run_review):
    mock_run_review.return_value = [{"success": False}]

    with patch("sys.argv", ["llm-review"]):
        with pytest.raises(SystemExit) as exc_info:
            review.main()

    assert exc_info.value.code == 1
