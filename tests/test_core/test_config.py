from multi_llm_reviewer.core import config

def test_config_constants():
    """主要な定数が定義されていることを確認する"""
    assert config.MAX_LOOPS == 5
    assert isinstance(config.REVIEWER_SLOTS, list)
    assert len(config.REVIEWER_SLOTS) > 0
    assert "Gemini" in [s["name"] for s in config.REVIEWER_SLOTS]

def test_fixer_commands_mapping():
    """修正コマンドのマッピングが定義されていることを確認する"""
    assert "gemini3pro" in config.FIXER_COMMANDS
    assert "copilot" in config.FIXER_COMMANDS
    assert config.FIXER_COMMANDS["copilot"] == ["copilot", "--allow-all-tools"]

def test_critical_path_keywords():
    """重要パスのキーワードがリストであることを確認する"""
    assert isinstance(config.CRITICAL_PATH_KEYWORDS, list)
    assert "core" in config.CRITICAL_PATH_KEYWORDS
    assert "security" in config.CRITICAL_PATH_KEYWORDS


def test_local_llm_config():
    """ローカルLLM用の設定が定義されていることを確認する"""
    # ローカルLLM用の優先レビュアーSlot
    assert hasattr(config, 'LOCAL_LLM_REVIEWER_SLOT')
    assert isinstance(config.LOCAL_LLM_REVIEWER_SLOT, dict)
    assert "name" in config.LOCAL_LLM_REVIEWER_SLOT
    assert "cmds" in config.LOCAL_LLM_REVIEWER_SLOT
    assert "LocalLlama3" in config.LOCAL_LLM_REVIEWER_SLOT["name"]
    assert len(config.LOCAL_LLM_REVIEWER_SLOT["cmds"]) > 0

    # ローカルLLM用の修正エージェントマッピング
    assert hasattr(config, 'LOCAL_LLM_FIXER_COMMANDS')
    assert isinstance(config.LOCAL_LLM_FIXER_COMMANDS, dict)
    assert "llama3-fix" in config.LOCAL_LLM_FIXER_COMMANDS
    assert isinstance(config.LOCAL_LLM_FIXER_COMMANDS["llama3-fix"], list)
    assert config.LOCAL_LLM_FIXER_COMMANDS["llama3-fix"][0] == "ollama"
