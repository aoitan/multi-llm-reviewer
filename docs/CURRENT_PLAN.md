# Current Plan: External reviewer command configuration

## Goal

レビュアー／fixer の実行コマンドをコードから切り離し、ユーザー単位・リポジトリ単位で安全に上書きできるようにする。

## In-Scope

1. TOML 形式の `~/.config/.multi-llm-reviewer` と `<repo-root>/.multi-llm-reviewer` を読み込む。
2. 組み込み既定値、ユーザー設定、リポジトリ設定の順で上書きする。
3. reviewer 一覧、fixer 順序／コマンド、ローカル reviewer／fixer を検証して公開する。
4. Gemini CLI、GitHub Copilot CLI、Codex CLI の既定コマンドを現行の非対話・権限制御オプションへ更新する。
5. 設定例と README を更新し、優先順位と安全上の違いを説明する。
6. 優先順位、不正設定、既定コマンド、fixer 選択の回帰テストを追加する。

## Non-Goals

- ユーザーの実ファイル `~/.config/.multi-llm-reviewer` を作成・更新すること。
- CLI バイナリの自動インストール・更新や認証設定を行うこと。
- プロンプト、レビュー判定、Git 差分生成ロジックを変更すること。
- 既存の pre-check 設定全体を外部化すること。

## Verification

- 追加テストを先に失敗させ、実装後に成功することを確認する。
- `uv run pytest -q`
- `uv run ruff check .`
- `git diff --check`
- ローカルに導入済みの各 CLI の `--help` と組み込み既定コマンドを照合する。

## Guardrails

- リポジトリ設定はユーザー設定より強くするが、未指定セクションは保持する。
- 不正な設定や未知キーを黙って無視しない。
- reviewer の既定コマンドには書き込み権限を与えない。
- fixer の危険な無制限実行オプションは避け、各 CLI の workspace 向けモードを使う。
