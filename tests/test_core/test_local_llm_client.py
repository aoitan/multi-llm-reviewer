"""local_llm_client の run_local_llm_pre_check テスト"""
from unittest.mock import patch
from multi_llm_reviewer.core import local_llm_client


class TestRunLocalLlmPreCheck:
    def test_returns_empty_string_when_ollama_not_available(self):
        with patch.object(local_llm_client, "is_ollama_available", return_value=False):
            result = local_llm_client.run_local_llm_pre_check("+def foo():\n+    pass\n")
        assert result == ""

    def test_returns_empty_string_on_execution_failure(self):
        with patch.object(local_llm_client, "is_ollama_available", return_value=True), \
             patch.object(local_llm_client, "execute_local_llm_cli", return_value=("ERROR", "some error")):
            result = local_llm_client.run_local_llm_pre_check("+def foo():\n+    pass\n")
        assert result == ""

    def test_returns_llm_output_on_success(self):
        expected = "命名: snake_case混在あり。コードスメル: 関数行数が長い。"
        with patch.object(local_llm_client, "is_ollama_available", return_value=True), \
             patch.object(local_llm_client, "execute_local_llm_cli", return_value=("SUCCESS", expected)):
            result = local_llm_client.run_local_llm_pre_check("+def foo():\n+    pass\n")
        assert result == expected

    def test_prompt_contains_diff_text(self):
        """execute_local_llm_cli に渡されるプロンプトに diff_text が含まれること"""
        diff = "+def my_function():\n+    x = 1\n"
        captured_input = {}

        def mock_execute(cmd, input_text=None, stream_callback=None):
            captured_input["text"] = input_text
            return ("SUCCESS", "no issues")

        with patch.object(local_llm_client, "is_ollama_available", return_value=True), \
             patch.object(local_llm_client, "execute_local_llm_cli", side_effect=mock_execute):
            local_llm_client.run_local_llm_pre_check(diff)

        assert diff in captured_input.get("text", "")

    def test_safe_when_local_slot_has_empty_cmds(self):
        """LOCAL_LLM_REVIEWER_SLOT.cmds が空リストでも IndexError を起こさないこと"""
        from multi_llm_reviewer.core import config as cfg
        original = getattr(cfg, "LOCAL_LLM_REVIEWER_SLOT", None)
        cfg.LOCAL_LLM_REVIEWER_SLOT = {"cmds": []}
        try:
            with patch.object(local_llm_client, "is_ollama_available", return_value=True), \
                 patch.object(local_llm_client, "execute_local_llm_cli", return_value=("SUCCESS", "ok")) as mock_exec:
                local_llm_client.run_local_llm_pre_check("+x = 1\n")
                # cmdsが空なのでデフォルトコマンドが使われる
                called_cmd = mock_exec.call_args[0][0]
                assert called_cmd == ["ollama", "run", "llama3"]
        finally:
            cfg.LOCAL_LLM_REVIEWER_SLOT = original
