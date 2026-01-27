from unittest.mock import patch, MagicMock
from src.core import git_utils

@patch("subprocess.run")
def test_get_current_branch_issue_num(mock_run):
    # ケース1: 数字が含まれるブランチ名
    mock_run.return_value = MagicMock(stdout="feature/issue-123-fix\n")
    assert git_utils.get_current_branch_issue_num() == "123"

    # ケース2: 数字が含まれないブランチ名
    mock_run.return_value = MagicMock(stdout="main\n")
    assert git_utils.get_current_branch_issue_num() is None

    # ケース3: コマンド失敗
    mock_run.side_effect = Exception("error")
    assert git_utils.get_current_branch_issue_num() is None

@patch("subprocess.run")
def test_get_changed_files(mock_run):
    mock_run.return_value = MagicMock(stdout="file1.py\nfile2.py\n")
    files = git_utils.get_changed_files("main")
    assert files == ["file1.py", "file2.py"]
    mock_run.assert_called_with(
        ["git", "diff", "--name-only", "main"],
        capture_output=True, text=True
    )

@patch("subprocess.run")
def test_get_git_diff_small(mock_run):
    mock_run.return_value = MagicMock(stdout="diff content")
    diff = git_utils.get_git_diff("main")
    assert "diff content" in diff
    # stat用とdiff用の2回呼ばれるはず
    assert mock_run.call_count == 2
