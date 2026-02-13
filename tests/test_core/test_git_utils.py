from unittest.mock import patch, MagicMock
from multi_llm_reviewer.core import git_utils

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
    mock_run.side_effect = [
        MagicMock(stdout="origin/main\n", returncode=0),   # rev-parse origin/main
        MagicMock(stdout="file1.py\nfile2.py\n", returncode=0),  # committed
        MagicMock(stdout="file2.py\nfile3.py\n", returncode=0),  # staged
        MagicMock(stdout="file3.py\nfile4.py\n", returncode=0),  # unstaged
    ]
    files = git_utils.get_changed_files("main")
    assert files == ["file1.py", "file2.py", "file3.py", "file4.py"]
    assert mock_run.call_count == 4
    call_args = [call.args[0] for call in mock_run.call_args_list]
    assert call_args[1][:4] == ["git", "diff", "--name-only", "origin/main...HEAD"]
    assert call_args[2][:5] == ["git", "diff", "--name-only", "--cached", "--"]
    assert call_args[3][:4] == ["git", "diff", "--name-only", "--"]

@patch("subprocess.run")
def test_get_git_diff_small(mock_run):
    mock_run.side_effect = [
        MagicMock(stdout="origin/main\n", returncode=0),  # rev-parse origin/main
        MagicMock(stdout="diff --git a/a.py b/a.py\n", returncode=0),  # committed
        MagicMock(stdout="", returncode=0),  # staged
        MagicMock(stdout="", returncode=0),  # unstaged
    ]
    diff = git_utils.get_git_diff("main")
    assert "Committed changes vs origin/main" in diff
    assert "diff --git a/a.py b/a.py" in diff
    assert mock_run.call_count == 4


@patch("subprocess.run")
def test_get_git_diff_includes_uncommitted_when_base_not_found(mock_run):
    mock_run.side_effect = [
        MagicMock(stdout="", stderr="bad ref", returncode=1),  # rev-parse origin/main
        MagicMock(stdout="", stderr="bad ref", returncode=1),  # rev-parse main
        MagicMock(stdout="diff --git a/staged.py b/staged.py\n", returncode=0),  # staged
        MagicMock(stdout="diff --git a/wt.py b/wt.py\n", returncode=0),  # unstaged
    ]
    diff = git_utils.get_git_diff("main")
    assert "Staged changes" in diff
    assert "Unstaged changes" in diff
    assert "staged.py" in diff
    assert "wt.py" in diff
