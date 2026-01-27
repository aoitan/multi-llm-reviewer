from unittest.mock import patch
from src.services import review_service
from src.core import config

@patch("src.core.git_utils.get_changed_files")
def test_decide_reviewers_auto_small(mock_get_files):
    # ファイル数が少ない場合 -> Single
    mock_get_files.return_value = ["README.md"]
    slots, log = review_service.decide_reviewers("main", "auto")
    assert "Single" in log
    assert len(slots) == 1

@patch("src.core.git_utils.get_changed_files")
def test_decide_reviewers_auto_large(mock_get_files):
    # ファイル数が多い場合 -> ALL
    mock_get_files.return_value = ["f1.py", "f2.py", "f3.py", "f4.py", "f5.py"]
    slots, log = review_service.decide_reviewers("main", "auto")
    assert "ALL" in log
    assert len(slots) == len(config.REVIEWER_SLOTS)

@patch("src.core.git_utils.get_changed_files")
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
