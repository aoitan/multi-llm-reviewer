from unittest.mock import patch, MagicMock
from multi_llm_reviewer.core import llm_client

def test_is_rate_limit():
    assert llm_client.is_rate_limit("Rate limit exceeded") is True
    assert llm_client.is_rate_limit("429 Too Many Requests") is True
    assert llm_client.is_rate_limit("Everything is fine") is False
    assert llm_client.is_rate_limit("") is False

@patch("subprocess.Popen")
@patch("multi_llm_reviewer.core.llm_client._read_process_output", return_value=("SUCCESS", "Success line 1\nSuccess line 2\n"))
def test_execute_command_success(mock_read_output, mock_popen):
    mock_process = MagicMock()
    mock_popen.return_value = mock_process

    status, output = llm_client.execute_command(["ls"])
    
    assert status == "SUCCESS"
    assert "Success line 1" in output
    assert "Success line 2" in output
    mock_read_output.assert_called_once_with(mock_process, echo_stdout=True)

@patch("subprocess.Popen")
@patch("multi_llm_reviewer.core.llm_client._read_process_output", return_value=("RATE_LIMIT", "Error: 429 Rate Limit\n"))
def test_execute_command_rate_limit(mock_read_output, mock_popen):
    mock_process = MagicMock()
    mock_popen.return_value = mock_process

    status, output = llm_client.execute_command(["llm-cmd"])
    
    assert status == "RATE_LIMIT"
    assert "429" in output
    mock_read_output.assert_called_once_with(mock_process, echo_stdout=True)


@patch("multi_llm_reviewer.core.llm_client.select.select", return_value=([], [], []))
@patch("subprocess.Popen")
def test_execute_command_async_times_out(mock_popen, _mock_select):
    mock_process = MagicMock()
    mock_process.stdout.readline.return_value = ""
    mock_process.poll.return_value = None
    mock_process.args = ["dummy"]
    mock_popen.return_value = mock_process

    with patch("multi_llm_reviewer.core.llm_client.time.monotonic", side_effect=[0, 181]):
        status, output = llm_client.execute_command_async(["dummy"])

    assert status == "ERROR"
    assert "timed out" in output
    mock_process.kill.assert_called_once()
