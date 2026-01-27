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

- Python 3
- `git`
- `gh` (GitHub CLI) - Issue情報の取得に必要
- 各LLMのCLIツール:
    - `gemini`
    - `copilot`
    - `codex` (または互換CLI)

## 使い方

### レビューのみ実行

```bash
# 自動モード（変更量に応じてレビュアーを決定）
python3 src/review_all.py

# 特定のブランチとの差分をレビュー
python3 src/review_all.py -b develop

# Issue番号を明示
python3 src/review_all.py -i 123

# 全レビュアー強制実行
python3 src/review_all.py --reviewers all
```

### 自動修正ループ実行

```bash
# デフォルト設定で実行
python3 src/auto_fix_loop.py

# メインの修正担当エージェントを指定
python3 src/auto_fix_loop.py --fixer copilot

# review_all.py に引数を渡す場合
python3 src/auto_fix_loop.py -- -b develop -i 123
```

## ディレクトリ構造

```
src/
├── review_all.py    # レビュー実行スクリプト
└── auto_fix_loop.py # 自動修正ループ制御スクリプト
```
