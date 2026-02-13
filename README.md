# Multi-LLM Reviewer & Auto-Fixer

複数のLLM (Gemini, Copilot, Codex) を活用した、高度なコードレビューおよび自動修正システムです。
Gitの差分とGitHub Issueのコンテキストを理解し、多角的な視点でレビューを行い、発見された重大な問題を自動的に修正しようと試みます。

## 機能

### 1. マルチLLMレビュー (`src/review_all.py`)
- **複数のAIレビュアー:** Gemini (Pro/Flash), GitHub Copilot CLI, OpenAI Codex (via CLI) を並行実行。
- **スマートな差分取得:** 大規模な差分は自動的に要約し、ロックファイルやバイナリを除外。
- **コンテキスト認識:** 現在のブランチに関連するGitHub Issueの内容を自動取得 (`gh` CLI使用) し、仕様との整合性を確認。
- **自動モード選択:** 変更ファイル数や重要度（`core`, `security` 等）に応じて、シングルレビュアーか総力戦（全レビュアー）かを自動判断。
- **レートリミット対策:** API制限時に自動でフォールバックモデルに切り替え。

### 2. 自動修正ループ (`src/auto_fix_loop.py`)
- **Review-Fix-Verify サイクル:** レビューを実行し、重大な指摘があれば修正を試みるループを自動で回します。
- **ロールプレイ戦略:** ループ回数に応じてAIの役割（Role）を動的に変更し、解決率を高めます。
    1. **Efficiency Engineer:** 効率重視の最小修正。
    2. **Investigative Debugger:** ログ追加や原因調査に特化。
    3. **Precision Surgeon:** 特定された原因に対する外科手術的修正。
    4. **Strategic Architect:** 設計レベルの見直しや方針転換。
- **2段階修正プロセス:** 「設計フェーズ（思考のみ）」→「実装フェーズ（コーディング）」の2ステップを踏むことで、無謀な修正を防ぎます。

## 必要要件

### フロンティアLLMを使用する場合（推奨）
- Python 3
- `git`
- `gh` (GitHub CLI) - Issue情報の取得に必要
- 各LLMのCLIツール:
    - `gemini`
    - `gh` / `copilot` (GitHub Copilot CLI)
    - `codex` (または互換CLI)

### ローカルLLMを使用する場合（プライバシー重視）
- Python 3
- `git`
- `gh` (GitHub CLI) - Issue情報の取得に必要
- **Ollama** ([https://ollama.ai/](https://ollama.ai/))
    - ダウンロード後、`ollama run llama3` コマンドで動作確認
    - 推奨モデル: `llama3`（7B / 8B / 15B）或いは他のローカルLLM

### ローカルLLMのみを使用する場合
環境変数 `LOCAL_LLM_ONLY=1` を設定することで、フロンティアLLMを完全に無視できます。

### システム要件
- **メモリ**: ローカルLLMを使用する場合、推奨4GB以上（llama3-7Bの場合）
- **CPU/GPU**: OllamaがGPUを検出すると最適化され、応答速度が向上します

## インストール

このツールを任意のディレクトリで使用可能にするには、`uv tool` を使用してインストールします。

```bash
# リポジトリのルートで実行
uv tool install . --force
```

これにより、`llm-review` と `llm-fix` コマンドがシステムに登録されます。

## 使い方

インストール後は、任意のGitリポジトリ内で以下のコマンドを実行できます。

### レビューのみ実行 (`llm-review`)

```bash
# 自動モード（変更量に応じてレビュアーを決定）
llm-review

# 特定のブランチとの差分をレビュー
llm-review -b develop

# Issue番号を明示
llm-review -i 123

# 全レビュアー強制実行
llm-review --reviewers all
```

### 自動修正ループ実行 (`llm-fix`)

```bash
# デフォルト設定で実行
llm-fix

# メインの修正担当エージェントを指定
llm-fix --fixer copilot

# review 用の引数を渡す場合（-- の後に記述）
llm-fix --fixer gemini3pro -- -b develop -i 123
```

## トラブルシューティング

### ローカルLLMでエラーが発生する
- **ollamaコマンドが見つかりません**: [Ollama公式サイト](https://ollama.ai/) からインストールし、ターミナルで `ollama --version` が動作することを確認してください。
- **モデルが見つかりません**: `ollama list` を実行して `llama3` が存在することを確認してください。なければ `ollama pull llama3` を実行します。
- **実行が非常に遅い**: ローカルLLMはPCのスペックに依存します。GPUが利用可能な環境では大幅に高速化されます。

### 修正が反映されない
- `uv tool install` を使用している場合、ソースコードの変更を反映するには再インストールが必要です。
- 開発中は `uv tool install --editable .` を使用すると、再インストールなしにコードの変更が反映されます。

### レビュー内レビュー（Skills連鎖）を止めたい
- `src/multi_llm_reviewer/core/config.py` の `DISABLE_SKILLS_IN_NESTED_REVIEW = True` を有効にしてください（デフォルト有効）。

## ディレクトリ構造

```
src/
├── core/            # 基盤モジュール (Git, GitHub, LLMアクセス)
├── services/        # ビジネスロジック (レビュー, 修正ループ)
├── cli/             # CLIエントリーポイント
├── review_all.py    # 後方互換用スクリプト
└── auto_fix_loop.py # 後方互換用スクリプト
tests/               # 各モジュールの単体・結合テスト
```
