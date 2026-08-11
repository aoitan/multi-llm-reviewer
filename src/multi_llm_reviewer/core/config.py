"""設定・定数を管理するモジュール。"""

from copy import deepcopy
import os
from pathlib import Path
import tomllib
from typing import Any

# --- レビュー・修正ループの全般設定 ---
MAX_LOOPS = 5

def load_prompt(filename):
    """promptsディレクトリからプロンプトファイルを読み込む"""
    base_dir = os.path.dirname(os.path.dirname(__file__))
    prompt_path = os.path.join(base_dir, "prompts", filename)
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        print(f"[WARN] Failed to load prompt {filename}: {e}")
        return ""

class ConfigError(ValueError):
    """外部コマンド設定が不正な場合のエラー。"""


_DEFAULT_COMMAND_CONFIG = {
    "reviewers": [
        {
            "name": "Gemini",
            "commands": [
                [
                    "gemini",
                    "--approval-mode",
                    "plan",
                    "--output-format",
                    "text",
                    "--prompt",
                    "",
                ]
            ],
        },
        {
            "name": "Copilot",
            "commands": [
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
            ],
        },
        {
            "name": "Codex",
            "commands": [
                ["codex", "exec", "--sandbox", "read-only", "--ephemeral", "-"]
            ],
        },
    ],
    "fixers": {
        "order": ["gemini", "copilot", "codex"],
        "commands": {
            "gemini": [
                "gemini",
                "--approval-mode",
                "yolo",
                "--output-format",
                "text",
                "--prompt",
                "",
            ],
            "copilot": [
                "copilot",
                "--silent",
                "--no-ask-user",
                "--allow-all-tools",
            ],
            "codex": ["codex", "exec", "--approve-for-me", "--ephemeral", "-"],
        },
    },
    "local_reviewer": {
        "name": "LocalLlama3 (優先)",
        "commands": [["ollama", "run", "llama3"]],
    },
    "local_fixers": {"llama3-fix": ["ollama", "run", "llama3"]},
}


def _find_repository_root(start: Path) -> Path | None:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _config_error(path: Path, message: str) -> ConfigError:
    return ConfigError(f"Invalid multi-llm-reviewer config {path}: {message}")


def _validate_argv(value: Any, path: Path, location: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise _config_error(path, f"{location} must be a non-empty array of strings")
    if not all(isinstance(part, str) and part for part in value):
        raise _config_error(path, f"{location} must contain only non-empty strings")
    return list(value)


def _validate_commands(value: Any, path: Path, location: str) -> list[list[str]]:
    if not isinstance(value, list) or not value:
        raise _config_error(path, f"{location} must be a non-empty array of commands")
    return [
        _validate_argv(command, path, f"{location}[{index}]")
        for index, command in enumerate(value)
    ]


def _validate_reviewer(value: Any, path: Path, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _config_error(path, f"{location} must be a table")
    unknown = set(value) - {"name", "commands"}
    if unknown:
        raise _config_error(path, f"unknown key in {location}: {sorted(unknown)[0]}")
    name = value.get("name")
    if not isinstance(name, str) or not name:
        raise _config_error(path, f"{location}.name must be a non-empty string")
    return {
        "name": name,
        "commands": _validate_commands(value.get("commands"), path, f"{location}.commands"),
    }


def _parse_command_config(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as config_file:
            raw = tomllib.load(config_file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise _config_error(path, str(exc)) from exc

    unknown = set(raw) - {
        "version",
        "reviewers",
        "fixers",
        "local_reviewer",
        "local_fixers",
    }
    if unknown:
        raise _config_error(path, f"unknown key: {sorted(unknown)[0]}")
    version = raw.get("version", 1)
    if type(version) is not int or version != 1:
        raise _config_error(path, "version must be 1")

    parsed: dict[str, Any] = {}
    if "reviewers" in raw:
        reviewers = raw["reviewers"]
        if not isinstance(reviewers, list) or not reviewers:
            raise _config_error(path, "reviewers must be a non-empty array of tables")
        parsed["reviewers"] = [
            _validate_reviewer(reviewer, path, f"reviewers[{index}]")
            for index, reviewer in enumerate(reviewers)
        ]

    if "fixers" in raw:
        fixers = raw["fixers"]
        if not isinstance(fixers, dict):
            raise _config_error(path, "fixers must be a table")
        unknown_fixers = set(fixers) - {"order", "commands"}
        if unknown_fixers:
            raise _config_error(
                path, f"unknown key in fixers: {sorted(unknown_fixers)[0]}"
            )
        parsed_fixers: dict[str, Any] = {}
        if "order" in fixers:
            order = fixers["order"]
            if (
                not isinstance(order, list)
                or not order
                or not all(isinstance(name, str) and name for name in order)
            ):
                raise _config_error(
                    path, "fixers.order must be a non-empty array of strings"
                )
            parsed_fixers["order"] = list(order)
        if "commands" in fixers:
            commands = fixers["commands"]
            if not isinstance(commands, dict) or not commands:
                raise _config_error(path, "fixers.commands must be a non-empty table")
            parsed_fixers["commands"] = {
                name: _validate_argv(command, path, f"fixers.commands.{name}")
                for name, command in commands.items()
                if isinstance(name, str) and name
            }
            if len(parsed_fixers["commands"]) != len(commands):
                raise _config_error(path, "fixers.commands keys must be non-empty strings")
        parsed["fixers"] = parsed_fixers

    if "local_reviewer" in raw:
        parsed["local_reviewer"] = _validate_reviewer(
            raw["local_reviewer"], path, "local_reviewer"
        )

    if "local_fixers" in raw:
        local_fixers = raw["local_fixers"]
        if not isinstance(local_fixers, dict) or not local_fixers:
            raise _config_error(path, "local_fixers must be a non-empty table")
        parsed["local_fixers"] = {
            name: _validate_argv(command, path, f"local_fixers.{name}")
            for name, command in local_fixers.items()
            if isinstance(name, str) and name
        }
        if len(parsed["local_fixers"]) != len(local_fixers):
            raise _config_error(path, "local_fixers keys must be non-empty strings")
    return parsed


def _merge_command_config(effective: dict[str, Any], overlay: dict[str, Any]) -> None:
    if "reviewers" in overlay:
        effective["reviewers"] = overlay["reviewers"]
    if "fixers" in overlay:
        if "order" in overlay["fixers"]:
            effective["fixers"]["order"] = overlay["fixers"]["order"]
        if "commands" in overlay["fixers"]:
            effective["fixers"]["commands"].update(overlay["fixers"]["commands"])
    if "local_reviewer" in overlay:
        effective["local_reviewer"] = overlay["local_reviewer"]
    if "local_fixers" in overlay:
        effective["local_fixers"].update(overlay["local_fixers"])


def load_command_config(
    cwd: str | Path | None = None, home: str | Path | None = None
) -> dict[str, Any]:
    """ユーザー設定、リポジトリ設定の順でコマンド設定を読み込む。"""
    working_directory = Path.cwd() if cwd is None else Path(cwd)
    home_directory = Path.home() if home is None else Path(home)
    repository_root = _find_repository_root(working_directory)
    paths = [home_directory / ".config" / ".multi-llm-reviewer"]
    if repository_root is not None:
        paths.append(repository_root / ".multi-llm-reviewer")

    effective = deepcopy(_DEFAULT_COMMAND_CONFIG)
    sources = []
    for path in paths:
        if not path.is_file():
            continue
        _merge_command_config(effective, _parse_command_config(path))
        sources.append(path)

    known_fixers = effective["fixers"]["commands"]
    for fixer_name in effective["fixers"]["order"]:
        if fixer_name not in known_fixers:
            source = sources[-1] if sources else paths[0]
            raise _config_error(source, f"unknown fixer in fixers.order: {fixer_name}")

    reviewer_names = [reviewer["name"] for reviewer in effective["reviewers"]]
    if len(reviewer_names) != len(set(reviewer_names)):
        source = sources[-1] if sources else paths[0]
        raise _config_error(source, "reviewer names must be unique")

    effective["sources"] = sources
    return effective


_COMMAND_CONFIG = load_command_config()

# --- レビュアー構成 (フォールバック順) ---
REVIEWER_SLOTS = [
    {"name": reviewer["name"], "cmds": reviewer["commands"]}
    for reviewer in _COMMAND_CONFIG["reviewers"]
]

# --- 修正実行エージェントの設定 ---
FIXER_ORDER = _COMMAND_CONFIG["fixers"]["order"]
FIXER_COMMANDS = _COMMAND_CONFIG["fixers"]["commands"]

# --- ローカルLLM用の追加設定 ---
# セキュリティ・プライバシー重視のため、ローカルLLM（Ollama）を優先して使用
# ユーザーは環境変数 LOCAL_LLM_ONLY=1 を設定することで、フロンティアLLMを完全に無視できる

# ローカルLLM用の優先レビュアーSlot（フロンティアLLMの前に優先的に使われる）
LOCAL_LLM_REVIEWER_SLOT = {
    "name": _COMMAND_CONFIG["local_reviewer"]["name"],
    "cmds": _COMMAND_CONFIG["local_reviewer"]["commands"],
}

# ローカルLLM用の修正エージェントマッピング
LOCAL_LLM_FIXER_COMMANDS = _COMMAND_CONFIG["local_fixers"]

# --- 重要パスの判定キーワード ---
# これらが含まれるファイルが変更された場合、自動的にALLモードでレビューを行う
CRITICAL_PATH_KEYWORDS = [
    "core", "auth", "security", "config", "infra", "database", "model", "api", 
    "login", "guard", "project.toml", "package.json", "requirements.txt",
    "docker", "k8s", "terraform", "pipeline", "workflow"
]

# --- 無視するファイルパターン ---
EXCLUDE_PATTERNS = [
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock", "uv.lock",
    "*.min.js", "*.min.css", "*.map", "*.svg", "*.png", "*.jpg", "*.jpeg", "*.gif", "*.ico",
    "dist/*", "build/*", ".next/*", "node_modules/*", "__pycache__/*"
]

# --- その他 ---
DEFAULT_BASE_BRANCH = "main"
MAX_DIFF_CHARS = 100000
REVIEW_COMMAND_TIMEOUT_SECONDS = 180

# --- 自動モード判定の閾値 ---
# このファイル数を超えると "Large changeset" とみなしてALLモードになる
LARGE_CHANGESET_THRESHOLD = 10

# --- レビュー内レビュー抑止 ---
# True の場合、レビュー実行時のプロンプトに「Skills/AGENTSトリガーを使わない」指示を追加する
DISABLE_SKILLS_IN_NESTED_REVIEW = True

# --- Gate 1: 設定ベースの lint/test/coverage チェック ---
# 各コマンドを list 形式で設定する。None の場合はそのチェックをスキップする。
# プロジェクトごとに適切なコマンドを設定すること。
# 例:
#   "lint":     ["ruff", "check"]            # または ["npm", "run", "lint"]
#   "test":     ["uv", "run", "pytest"]      # または ["npm", "test"]
#   "coverage": ["uv", "run", "pytest", "--cov", "--cov-report=term-missing"]
#
# lint の場合は変更ファイルのパスが引数として自動付与される。
# test / coverage はコマンドをそのまま実行する。
PRE_CHECK_COMMANDS: dict = {
    "lint":     None,
    "test":     None,
    "coverage": None,
}

# coverage チェックの閾値（%）。coverage がこの値を下回った場合 WARN を出す。
COVERAGE_THRESHOLD: float = 80.0
