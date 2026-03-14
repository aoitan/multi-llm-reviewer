# LLMレビュー前段チェック設計

フロンティアLLMのリクエストコストを削減し、レビューの質を高めるために、LLMレビューの前に複数段階の事前チェックを導入する設計方針を記録する。

## 全体フロー

```
diff取得
  ↓
[Gate 1] ルールベース事前チェック（機械的・決定論的）
  → ブロック条件: 即座に中断＆メッセージ出力
  → 警告条件: ユーザーに確認を促して続行
  ↓
[Gate 2] ローカルLLMチェック（ollama / llama3等）
  → 結果を「参考情報」として蓄積（ブロックはしない）
  ↓
[Gate 3] フロンティアLLMレビュー
  → Gate1・Gate2の結果をプロンプトに注入して実行
```

---

## Gate 1: ルールベース事前チェック

機械的・決定論的に判断できる項目。LLMを一切使わずに検出する。

### A. 差分・ファイル品質チェック（コーディング）

| チェック項目 | 検出方法 | 重大度 | ユーザーへのメッセージ例 |
|---|---|---|---|
| **差分がゼロ** | diff文字列が空 or `"(No changes detected)"` | BLOCK | 「変更がありません。レビューを中断します。」 |
| **マージコンフリクトマーカー残存** | `<<<<<<< ` / `=======` / `>>>>>>> ` を grep | BLOCK | 「コンフリクトマーカーが残っています。解消してから再実行してください。」 |
| **ロックファイル・バイナリのみの変更** | 全変更ファイルが `EXCLUDE_PATTERNS` にマッチ | BLOCK | 「レビュー対象のソースコードがありません（ロックファイルのみの変更）。」 |
| **secrets/credentials のハードコード** | 正規表現: `(?i)(api[_-]?key\|secret\|password\|token\|aws_access)\s*=\s*['"][^'"]{8,}` | BLOCK | 「機密情報の可能性があるハードコードが検出されました。コミット前に確認してください。」 |
| **極端に巨大な単一ファイル変更** | 1ファイルあたりの追加行数 > 500行 | WARN | 「`foo.py` の変更が大きすぎます（+N行）。コミットを分割するか `--reviewers all` で実行してください。」 |
| **TODO/FIXME の混入** | diff追加行（`+` 始まり）に `TODO\|FIXME\|HACK\|XXX` | WARN | 「未解決のTODOコメントが追加されています。意図的なものか確認してください。」 |

### B. コード構文・静的解析チェック（コーディング）

| チェック項目 | 検出方法 | 重大度 | ユーザーへのメッセージ例 |
|---|---|---|---|
| **Python構文エラー** | `python -m py_compile <file>` または `flake8 --select=E9` | BLOCK | 「構文エラーが検出されました。LLMレビュー前に修正してください。」 |
| **未使用import / 重複import** | `flake8 --select=F401,F811` | WARN | 「未使用importが検出されました。クリーンアップを推奨します。」 |
| **フォーマット違反** | `black --check --diff` / `ruff check` | WARN | 「コードフォーマットが統一されていません。`black .` を実行してください。」 |
| **型ヒント・docstring欠落（公開API）** | 正規表現: `def [a-z]\w+\(` で `->` なし＆docstringなし | WARN | 「型ヒント・docstringのない公開関数があります。」 |

### C. ユニットテスト観点チェック

| チェック項目 | 検出方法 | 重大度 | ユーザーへのメッセージ例 |
|---|---|---|---|
| **テストファイルが1つもない** | `tests/` 以下のファイル数ゼロ | WARN | 「テストが存在しません。実装前にテストを作成することを推奨します。」 |
| **変更ソースに対応するテストがない** | `src/foo.py` 変更あり、`tests/test_foo.py` 変更なし | WARN | 「`foo.py` が変更されていますが、対応するテストが変更されていません。テストの更新を検討してください。」 |
| **アサーションなしテスト関数** | `def test_` で始まる関数に `assert` も `pytest.raises` もない | WARN | 「アサーションのないテスト関数があります（偽陽性テストの疑い）。」 |
| **大量スキップ** | `@pytest.mark.skip` / `@unittest.skip` の数 > 閾値（例: 3件） | WARN | 「スキップされているテストが X 件あります。意図的なものか確認してください。」 |
| **pytest収集エラー** | `pytest --collect-only -q` の終了コード != 0 | BLOCK | 「テストの収集に失敗しました。構文エラーまたはimportエラーを確認してください。」 |

---

## Gate 2: ローカルLLMチェック

フロンティアLLMほどの推論能力を必要とせず、7B〜13Bクラスのローカルモデル（`ollama run llama3` 等）で十分な精度が期待できる項目。結果はブロックではなく「参考情報」としてGate 3のプロンプトに注入する。

| カテゴリ | 具体的チェック項目 | ローカルLLMで十分な理由 |
|---|---|---|
| **命名規則** | snake_case/camelCase の混在、意味のない1文字変数（ループ外）| パターン的判断で文脈依存性が低い |
| **コードスメル（定量的）** | 関数行数 > 50行、ネスト深度 > 4、引数 > 5個 | 基準が明確で「説明」を生成させればよい |
| **重複コード** | diff範囲内での同一・類似ロジックの出現 | 局所的な比較で十分 |
| **コメント品質** | コードと矛盾するコメント、日本語/英語混在 | 浅い文脈理解で検出可 |
| **テスト構造** | AAAパターン(Arrange/Act/Assert)、テスト名の説明性 | テスト名→説明のマッピングだけでよい |
| **docstring品質** | public関数/クラスへのdocstring有無、引数説明の揃い | 形式的チェックに近い |
| **例外握り潰し** | `except: pass` / ログなしの例外キャッチ | パターンマッチに近い |
| **デバッグコード混入** | src本体にprint文・デバッグコードが残っている | 形式チェックに近く文脈不要 |

**実装方針**: ローカルLLMにはチェックリスト形式の指示を渡し、スコアリングではなく「Yes/No + 該当箇所の列挙」のみを求める。推論コストを最小化する。

---

## Gate 3: フロンティアLLMレビュー プロンプト改善案

Gate 1・2の結果を構造化して注入することで、LLMが重複作業をせず本質的な問題に集中できるようにする。

`_build_review_prompt()` の引数として `pre_check_summary` と `local_llm_analysis` を追加する。

### プロンプトテンプレート（改善案）

```
【役割】世界トップクラスのソフトウェアアーキテクト兼セキュリティスペシャリスト

【タスク】提供されたCode DiffとIssue情報を詳細に分析し、厳格かつ建設的なレビューを行ってください。

【事前自動チェック済み項目（重複指摘は不要）】
{pre_check_summary}
例:
- ✅ マージコンフリクトマーカー: なし
- ✅ 構文エラー (py_compile): なし
- ⚠️ src/foo.py の変更に対応するテスト変更なし
- ⚠️ 関数 `process_data` に docstring なし（ローカルLLM指摘）

【ローカルLLM事前分析（参考情報）】
{local_llm_analysis}
例: コードスメル検出: `review_service.py` の `_run_single_reviewer_stream` が70行超。分割を検討する余地あり。

【あなたがフォーカスすべき観点（事前チェックで検出不能なもの）】
1. バグ・不具合（エラー処理、Null参照、型安全性、競合状態）
2. リグレッション・副作用（既存機能・後方互換性への影響）
3. セキュリティ（権限昇格、インジェクション等の深い脆弱性）
4. 設計・アーキテクチャ（SOLID, DRY, 境界設計、将来の拡張性）
5. 仕様整合性（Issueの要件を過不足なく満たしているか）

【制約】
- コードの修正や書き込みは禁止。評価のみを行う。
- 事前チェック済みの形式的問題（命名・フォーマット等）の指摘は最小限に。
- コンテキスト不足時は読み取りツール（read_file, ls, grep等）を自律的に使用。
- 日本語で回答。
- 最後に必ず以下の形式のJSONブロックのみを出力。

【出力JSON形式】
```json
{
  "reviewer_name": "YOUR_NAME",
  "critical_issues_found": boolean,
  "reason": "重大な問題の理由または全体要約",
  "review_score": 0-100,
  "pre_check_confirmed": ["事前チェック⚠️項目への追加見解（任意）"],
  "actionable_feedback": ["具体的な修正提案1", "具体的な修正提案2"]
}
```
```

### 変更点まとめ

- `{pre_check_summary}`: Gate 1のルールベースチェック結果（✅/⚠️ 箇条書き）
- `{local_llm_analysis}`: Gate 2のローカルLLM分析結果（自由テキスト）
- `pre_check_confirmed` フィールド追加: LLMが事前チェックの⚠️項目に対して追加の見解を返せるようにする
- フォーカス観点を明示することで、形式的問題への重複指摘を抑制

---

## 実装上の推奨インターフェース

```python
# review_service.py の run_multi_llm_review() 冒頭に追加
pre_check_result = run_pre_checks(target_branch)   # Gate 1
if pre_check_result.has_blocking_issues:
    print(pre_check_result.block_message)
    return []

local_analysis = run_local_llm_check(diff_text)    # Gate 2 (optional)

# Gate 3: プロンプトに結果を注入
prompt = _build_review_prompt(
    base_prompt=base_prompt,
    issue_context=issue_context,
    spec_text=spec_text,
    diff_context=diff_context,
    pre_check_summary=pre_check_result.summary,     # 追加
    local_llm_analysis=local_analysis,              # 追加
)
```
