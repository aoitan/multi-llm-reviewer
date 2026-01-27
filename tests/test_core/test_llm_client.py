from unittest.mock import patch, MagicMock
from src.core import llm_client
import subprocess

def test_is_rate_limit():
    assert llm_client.is_rate_limit("Rate limit exceeded") is True
    assert llm_client.is_rate_limit("429 Too Many Requests") is True
    assert llm_client.is_rate_limit("Everything is fine") is False
    assert llm_client.is_rate_limit("") is False

@patch("subprocess.Popen")
def test_execute_command_success(mock_popen):
    mock_process = MagicMock()
    mock_process.stdout = ["Success line 1\n", "Success line 2\n"]
    mock_process.returncode = 0
    mock_popen.return_value = mock_process
    
    status, output = llm_client.execute_command(["ls"])
    
    assert status == "SUCCESS"
    assert "Success line 1" in output
    assert "Success line 2" in output

@patch("subprocess.Popen")
def test_execute_command_rate_limit(mock_popen):
    mock_process = MagicMock()
    mock_process.stdout = ["Error: 429 Rate Limit\n"]
    mock_process.returncode = 1
    mock_popen.return_value = mock_process
    
    status, output = llm_client.execute_command(["llm-cmd"])
    
    assert status == "RATE_LIMIT"
    assert "429" in output
