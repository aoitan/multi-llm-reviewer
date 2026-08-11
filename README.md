# Multi-LLM Reviewer & Auto-Fixer

> **Note**: 本リポジトリは個人利用目的で作成・公開しているツールです。OSSとしてのサポート提供や機能追加の対応は保証していません。自己責任の上でご利用ください。

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

## レビュアー／Fixer コマンドの設定

外部 CLI の実行コマンドは、拡張子なしの TOML ファイルで上書きできます。
設定は次の順に読み込まれ、後のものが優先されます。

1. パッケージ組み込みの既定値
2. ユーザー設定: `~/.config/.multi-llm-reviewer`
3. 対象 Git リポジトリの設定: `<repo-root>/.multi-llm-reviewer`

完全な記述例は [`.multi-llm-reviewer.example`](.multi-llm-reviewer.example) を参照してください。
たとえば、リポジトリ固有のレビュアーだけに置き換える最小設定は次のとおりです。

```toml
version = 1

[[reviewers]]
name = "Repository Codex"
commands = [
  ["codex", "exec", "--sandbox", "read-only", "--ephemeral", "-"],
]
```

- `reviewers` を指定すると、そのファイルより低い優先順位の reviewer 一覧をまとめて置き換えます。
- `fixers.commands` と `local_fixers` は名前単位でマージされます。`fixers.order` は指定した一覧で置き換えます。
- reviewer/fixer へ渡すプロンプトは常に標準入力です。標準入力を明示する必要がある CLI では、Codex の `-` のような引数も `commands` に含めてください。Gemini は headless モードを明示するため `--prompt ""` を指定し、標準入力をその prompt に追加します。
- 不明なキー、空コマンド、存在しない fixer 名などは起動時エラーになります。CLI バイナリの存在確認や認証は各 CLI 側で行ってください。

組み込み既定値はモデル名を固定せず、各 CLI の設定／現行既定モデルを使います。reviewer は Gemini の `plan`、Copilot の write/shell/url deny、Codex の `read-only` sandbox を使います。fixer はコード変更が目的のため書き込み可能な非対話モードです。特に Gemini の `yolo` と Copilot の `--allow-all-tools` は対象リポジトリ内でも強い権限を持つため、必要に応じてリポジトリ設定で制限してください。

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

# レッドチーム観点で監査
# 既定では全レビュアーで実行
llm-review --red-team

# レッドチーム観点を維持しつつ reviewer 数を明示制御
llm-review --red-team --reviewers single

# ベンダー送信を避けてローカルLLMのみでレッドチーム実行
LOCAL_LLM_ONLY=1 llm-review --red-team
```

### 自動修正ループ実行 (`llm-fix`)

```bash
# デフォルト設定で実行
llm-fix

# メインの修正担当エージェントを指定
llm-fix --fixer copilot

# review 用の引数を渡す場合（-- の後に記述）
llm-fix --fixer gemini -- -b develop -i 123 --red-team
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

### 外部コマンド設定が読み込めない
- ファイル名が `.multi-llm-reviewer` で、TOML として有効か確認してください。
- リポジトリ設定は Git ルート（`.git` がある場所）に置いてください。
- `.multi-llm-reviewer.example` と同じく、コマンドは文字列の配列で記述してください。

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
