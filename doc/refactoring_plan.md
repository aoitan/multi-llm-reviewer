# コード分割・リファクタリング計画

現在のコードベース（`review_all.py`, `auto_fix_loop.py`）の複雑度を下げ、保守性と拡張性を向上させるための分割計画です。

## 1. 現状の課題
- **責務の混在:** Git操作、設定値、LLM実行ロジック、CLIハンドリングが1つのファイルに同居している。
- **コードの重複:** レートリミット判定やコマンド実行の基盤ロジックが分散している。
- **連携の脆弱性:** 自動修正ループからレビュー機能をプロセス実行として呼び出しているため、データの受け渡しが非効率。

## 2. 目指す構造
責務を **Core (基盤)**, **Services (ビジネスロジック)**, **CLI (インターフェース)** の3層に分離します。

```text
src/
├── core/                  # システム全体の基盤
│   ├── config.py          # 設定・定数 (モデル定義、キーワード等)
│   ├── git_utils.py       # Git操作 (diff取得、ブランチ取得)
│   ├── github_utils.py    # GitHub CLI操作 (Issue取得)
│   └── llm_client.py      # LLMコマンド実行・レートリミット制御
├── services/              # ビジネスロジック
│   ├── review_service.py  # レビューの並列実行・モード判定
│   └── fix_service.py     # 修正ループ・ロールプレイ戦略
└── cli/                   # エントリーポイント
    ├── review.py          # レビューCLI
    └── autofix.py         # 自動修正CLI
```

## 3. モジュール詳細

| モジュール | 内容 | 役割 |
| :--- | :--- | :--- |
| `core/config.py` | レビュアー定義、重要パス設定 | 設定の一元管理 |
| `core/git_utils.py` | `git diff`, `git branch` 等 | Git操作の抽象化 |
| `core/github_utils.py` | `gh issue view` 等 | GitHub連携の抽象化 |
| `core/llm_client.py` | 共通コマンド実行、429エラー検知 | LLMアクセスの共通基盤 |
| `services/review_service.py` | レビュアー選定、並列実行 | レビュー機能の純粋なロジック |
| `services/fix_service.py` | 修正設計・実装、ループ制御 | 修正プロセスの純粋なロジック |
| `cli/*.py` | `argparse`, 出力フォーマット | ユーザーインターフェース |

## 4. 移行ステップ

1. **Phase 1: 基盤整備 (`core/`)**
   - 設定、Git/GitHub操作、LLMクライアントを共通モジュールとして切り出す。
2. **Phase 2: ロジック抽出 (`services/`)**
   - レビューと修正のメインロジックをクラス/関数として独立させる。
   - `auto_fix` から `review_service` を直接呼び出せるようにする。
3. **Phase 3: CLI再構築 (`cli/`)**
   - 新しいサービス層を利用するエントリーポイントを作成する。
4. **Phase 4: 統合とクリーンアップ**
   - 旧スクリプトを削除し、新しい構造に完全移行する。
