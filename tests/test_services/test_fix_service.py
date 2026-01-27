from multi_llm_reviewer.services import fix_service
import json

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
