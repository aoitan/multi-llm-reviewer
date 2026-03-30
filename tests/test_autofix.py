from unittest.mock import patch

from multi_llm_reviewer.cli import autofix


@patch("multi_llm_reviewer.cli.autofix.fix_service.run_auto_fix_loop")
def test_autofix_cli_passes_review_args(mock_run_auto_fix_loop):
    with patch(
        "sys.argv",
        [
            "llm-fix",
            "--fixer",
            "copilot",
            "--red-team",
            "--reviewers",
            "single",
            "-b",
            "develop",
            "-i",
            "123",
            "extra",
            "spec",
        ],
    ):
        autofix.main()

    mock_run_auto_fix_loop.assert_called_once_with(
        fixer_name="copilot",
        review_args={
            "issue": "123",
            "base": "develop",
            "mode": "single",
            "red_team": True,
            "spec": "extra spec",
        },
    )
