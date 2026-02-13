"""設定・定数を管理するモジュール。"""

# --- レビュー・修正ループの全般設定 ---
MAX_LOOPS = 5

import os

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

# --- レビュアー構成 (フォールバック順) ---
REVIEWER_SLOTS = [
    {
        "name": "Gemini",
        "cmds": [
            ["gemini", "-m", "gemini-3-pro-preview", "--yolo"],
            ["gemini", "-m", "gemini-2.5-pro", "--yolo"],
            ["gemini", "-m", "gemini-3-flash-preview", "--yolo"],
            ["gemini", "-m", "gemini-2.5-flash", "--yolo"]
        ]
    },
    {
        "name": "Copilot",
        "cmds": [
            ["copilot", "--allow-all-tools"]
        ]
    },
    {
        "name": "Codex",
        "cmds": [
            ["codex", "exec", "--full-auto"],
            ["codex", "exec", "--full-auto", "-m", "gpt-5.1-codex-mini"]
        ]
    }
]

# --- 修正実行エージェントの設定 ---
# 修正時に優先的に使用されるエージェントのリスト
FIXER_ORDER = [
    "gemini3pro",
    "gemini2.5pro",
    "copilot",
    "codex",
    "gemini3flash",
    "codex-mini"
]

# エージェント名から実行コマンドへのマッピング
FIXER_COMMANDS = {
    "gemini3pro": ["gemini", "-m", "gemini-3-pro-preview", "--yolo"],
    "gemini2.5pro": ["gemini", "-m", "gemini-2.5-pro", "--yolo"],
    "gemini3flash": ["gemini", "-m", "gemini-3-flash-preview", "--yolo"],
    "copilot": ["copilot", "--allow-all-tools"],
    "codex": ["codex", "exec", "--full-auto"],
    "codex-mini": ["codex", "exec", "--full-auto", "-m", "gpt-5.1-codex-mini"]
}

# --- ローカルLLM用の追加設定 ---
# セキュリティ・プライバシー重視のため、ローカルLLM（Ollama）を優先して使用
# ユーザーは環境変数 LOCAL_LLM_ONLY=1 を設定することで、フロンティアLLMを完全に無視できる

# ローカルLLM用の優先レビュアーSlot（フロンティアLLMの前に優先的に使われる）
LOCAL_LLM_REVIEWER_SLOT = {
    "name": "LocalLlama3 (優先)",
    "cmds": [
        ["ollama", "run", "llama3"]
    ]
}

# ローカルLLM用の修正エージェントマッピング
LOCAL_LLM_FIXER_COMMANDS = {
    "llama3-fix": ["ollama", "run", "llama3"]
}

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

# --- 自動モード判定の閾値 ---
# このファイル数を超えると "Large changeset" とみなしてALLモードになる
LARGE_CHANGESET_THRESHOLD = 10

# --- レビュー内レビュー抑止 ---
# True の場合、レビュー実行時のプロンプトに「Skills/AGENTSトリガーを使わない」指示を追加する
DISABLE_SKILLS_IN_NESTED_REVIEW = True
