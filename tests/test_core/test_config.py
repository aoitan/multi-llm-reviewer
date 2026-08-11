from pathlib import Path

import pytest

from multi_llm_reviewer.core import config

def test_config_constants():
    """主要な定数が定義されていることを確認する"""
    assert config.MAX_LOOPS == 5
    assert isinstance(config.REVIEWER_SLOTS, list)
    assert len(config.REVIEWER_SLOTS) > 0
    assert all("name" in slot and "cmds" in slot for slot in config.REVIEWER_SLOTS)

def test_fixer_commands_mapping():
    """修正コマンドのマッピングが定義されていることを確認する"""
    loaded = config.load_command_config(cwd=Path("/"), home=Path("/nonexistent"))
    assert "agy" in loaded["fixers"]["commands"]
    assert "copilot" in loaded["fixers"]["commands"]
    assert loaded["fixers"]["commands"]["copilot"] == [
        "copilot",
        "--silent",
        "--no-ask-user",
        "--allow-all-tools",
    ]
    assert loaded["fixers"]["commands"]["agy"] == [
        "agy",
        "--print",
        "--mode",
        "accept-edits",
        "--dangerously-skip-permissions",
        "--output-format",
        "text",
        "--disable-slash-commands",
    ]


def _write_config(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_load_command_config_uses_current_non_interactive_defaults(tmp_path):
    loaded = config.load_command_config(cwd=tmp_path, home=tmp_path / "home")

    commands = {reviewer["name"]: reviewer["commands"] for reviewer in loaded["reviewers"]}
    assert commands["Agy"] == [
        [
            "agy",
            "--print",
            "--mode",
            "plan",
            "--sandbox",
            "--output-format",
            "text",
            "--disable-slash-commands",
        ]
    ]
    assert commands["Copilot"] == [
        [
            "copilot",
            "--silent",
            "--no-ask-user",
            "--allow-all-tools",
            "--available-tools=view,glob,grep",
            "--disable-builtin-mcps",
            "--deny-tool=write",
            "--deny-tool=shell",
            "--deny-tool=url",
        ]
    ]
    assert commands["Codex"] == [
        ["codex", "exec", "--sandbox", "read-only", "--ephemeral", "-"]
    ]
    assert loaded["fixers"]["commands"]["codex"] == [
        "codex",
        "exec",
        "--approve-for-me",
        "--ephemeral",
        "-",
    ]


def test_load_command_config_applies_user_then_repository_overrides(tmp_path):
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    nested = repo / "src" / "package"
    (repo / ".git").mkdir(parents=True)
    nested.mkdir(parents=True)

    _write_config(
        home / ".config" / ".multi-llm-reviewer",
        """
[[reviewers]]
name = "User Reviewer"
commands = [["user-review", "--stdin"]]

[fixers.commands]
custom = ["custom-fix"]
""",
    )
    _write_config(
        repo / ".multi-llm-reviewer",
        """
[[reviewers]]
name = "Repository Reviewer"
commands = [["repo-review", "--read-only"]]

[fixers]
order = ["custom", "codex"]

[fixers.commands]
codex = ["repo-codex", "fix"]
""",
    )

    loaded = config.load_command_config(cwd=nested, home=home)

    assert loaded["reviewers"] == [
        {"name": "Repository Reviewer", "commands": [["repo-review", "--read-only"]]}
    ]
    assert loaded["fixers"]["order"] == ["custom", "codex"]
    assert loaded["fixers"]["commands"]["custom"] == ["custom-fix"]
    assert loaded["fixers"]["commands"]["codex"] == ["repo-codex", "fix"]
    assert loaded["sources"] == [
        home / ".config" / ".multi-llm-reviewer",
        repo / ".multi-llm-reviewer",
    ]


@pytest.mark.parametrize(
    "content, expected_message",
    [
        ('unknown = true\n', "unknown key"),
        ('version = true\n', "version"),
        ('[[reviewers]]\nname = "Broken"\ncommands = ["not-nested"]\n', "commands"),
        ('[fixers]\norder = ["missing"]\n', "unknown fixer"),
    ],
)
def test_load_command_config_rejects_invalid_configuration(
    tmp_path, content, expected_message
):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    config_path = repo / ".multi-llm-reviewer"
    _write_config(config_path, content)

    with pytest.raises(config.ConfigError) as exc_info:
        config.load_command_config(cwd=repo, home=tmp_path / "home")

    assert str(config_path) in str(exc_info.value)
    assert expected_message in str(exc_info.value).lower()

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
    assert len(config.LOCAL_LLM_REVIEWER_SLOT["cmds"]) > 0

    # ローカルLLM用の修正エージェントマッピング
    assert hasattr(config, 'LOCAL_LLM_FIXER_COMMANDS')
    assert isinstance(config.LOCAL_LLM_FIXER_COMMANDS, dict)
    assert "llama3-fix" in config.LOCAL_LLM_FIXER_COMMANDS
    assert isinstance(config.LOCAL_LLM_FIXER_COMMANDS["llama3-fix"], list)
    assert config.LOCAL_LLM_FIXER_COMMANDS["llama3-fix"][0] == "ollama"

def test_load_prompt():
    """プロンプトの読み込みが機能することを確認する"""
    # 存在するファイルを読み込んでみる
    content = config.load_prompt("review_prompt.txt")
    assert content != ""
    assert "役割" in content

    # 存在しないファイルの場合は空文字を返す
    assert config.load_prompt("non_existent.txt") == ""
