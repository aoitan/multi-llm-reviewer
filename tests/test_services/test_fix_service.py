from unittest.mock import patch

from multi_llm_reviewer.services import fix_service

def test_has_critical_issues_json_true():
    review_text = """
    Some comments...
    ```json
    {
      "reviewer_name": "Test",
      "critical_issues_found": true,
      "reason": "Bug found"
    }
    ```
    """
    is_critical, reason = fix_service.has_critical_issues(review_text)
    assert is_critical is True
    assert "Bug found" in reason

def test_has_critical_issues_json_false():
    review_text = """
    ```json
    {
      "reviewer_name": "Test",
      "critical_issues_found": false,
      "reason": "None"
    }
    ```
    """
    is_critical, reason = fix_service.has_critical_issues(review_text)
    assert is_critical is False

def test_has_critical_issues_text_gemini():
    review_text = """
    #### 重大な問題点
    - セキュリティホールがあります。
    """
    is_critical, reason = fix_service.has_critical_issues(review_text)
    assert is_critical is True
    assert "Gemini" in reason

def test_get_role_instructions():
    role_1 = fix_service.get_role_instructions(1)
    assert "Efficiency Engineer" in role_1["role"]
    
    role_3 = fix_service.get_role_instructions(3)
    assert "Investigative Debugger" in role_3["role"]
    
    role_5 = fix_service.get_role_instructions(5)
    assert "Strategic Architect" in role_5["role"]


@patch("multi_llm_reviewer.services.fix_service.git_utils.get_changed_files")
@patch("multi_llm_reviewer.services.fix_service.llm_client.execute_command")
@patch("multi_llm_reviewer.services.fix_service.local_llm_client.is_ollama_available", return_value=False)
@patch("multi_llm_reviewer.services.fix_service.config.load_prompt")
def test_run_fix_attempt_uses_review_base_branch(
    mock_load_prompt, _mock_ollama, mock_execute, mock_get_changed_files
):
    mock_get_changed_files.return_value = ["src/foo.py"]
    mock_load_prompt.side_effect = ["DESIGN_PROMPT", "IMPLEMENT_PROMPT"]
    mock_execute.side_effect = [
        ("SUCCESS", "design output"),
        ("SUCCESS", "implementation output"),
    ]

    status, output = fix_service.run_fix_attempt(
        "review text",
        "gemini3pro",
        1,
        base_branch="develop",
    )

    assert status == "SUCCESS"
    assert output == "implementation output"
    mock_get_changed_files.assert_called_once_with("develop")


@patch("multi_llm_reviewer.services.fix_service.run_fix_attempt", return_value=("SUCCESS", "ok"))
def test_run_fix_with_fallback_passes_base_branch(mock_run_fix_attempt):
    success = fix_service.run_fix_with_fallback(
        "review text",
        "gemini3pro",
        1,
        base_branch="develop",
    )

    assert success is True
    assert mock_run_fix_attempt.call_args.kwargs["base_branch"] == "develop"
