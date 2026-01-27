from unittest.mock import patch, MagicMock
from src.core import github_utils
import json

@patch("subprocess.run")
def test_fetch_issue_success(mock_run):
    mock_run.return_value = MagicMock(
        stdout=json.dumps({"title": "Test Issue", "body": "This is a test."}),
        returncode=0
    )
    result = github_utils.fetch_issue(123)
    assert "Title: Test Issue" in result
    assert "Body:\nThis is a test." in result

@patch("subprocess.run")
def test_fetch_issue_failure(mock_run):
    mock_run.side_effect = Exception("gh not found")
    result = github_utils.fetch_issue(123)
    assert result is None
