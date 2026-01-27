# 優先度付き順次ストリーミング (Prioritized Sequential Streaming) 設計

## 1. 概要
複数のLLM（Gemini, Codex, Copilot）を並列実行しつつ、ターミナルへの出力を制御することで、パフォーマンスとUXの両立を図る。
各プロセスの出力を「優先度」に基づいて順次表示し、バックグラウンドプロセスの出力はバッファリングする。

## 2. 要件
- **並列実行:** 全てのLLMプロセスは同時に起動する。
- **優先表示:** 指定された優先順位（例: Gemini > Codex > Copilot）に従って出力を表示する。
- **バッファリング:** 非表示中のプロセスの出力はメモリに蓄積する。
- **シームレスな切り替え:** 現在の表示対象が終了次第、バッファされた次の優先度の出力をフラッシュし、ライブ表示へ移行する。

## 3. アーキテクチャ

### 3.1 `StreamManager` (新設クラス)
出力の調停を行う中核クラス。

- **責務:**
    - 各プロセスの出力（stdout/stderr）を受け取る。
    - 現在の「表示権（Focus）」を持つプロセスを管理する。
    - 非表示プロセスの出力をバッファリングする。
    - フォーカス切り替え時にバッファを一括出力する。

- **データ構造:**
    - `streams`: `{ "gemini": StreamBuffer, "codex": StreamBuffer, ... }`
    - `priority_queue`: `["gemini", "codex", "copilot"]`
    - `current_focus`: 現在表示中のプロセス名

### 3.2 `StreamBuffer`
個々のプロセスの状態とデータを保持する。

- **プロパティ:**
    - `buffer`: `List[str]` (出力行のリスト)
    - `is_finished`: `bool`
    - `return_code`: `int`

### 3.3 変更が必要なモジュール
- **`src/core/llm_client.py`:** 
    - `subprocess.run` (同期) から `subprocess.Popen` (非同期) への変更。
    - 出力を一行ずつ読み取り、`StreamManager` にコールバックする仕組みの実装。
- **`src/services/review_service.py`:**
    - `ThreadPoolExecutor` での並列実行ではなく、プロセス起動と監視ループへの変更。

## 4. 処理フロー

1. **初期化:** `review_service` が `StreamManager` を作成し、優先順位を設定。
2. **起動:** 各LLMコマンドを非同期 (`Popen`) で一斉に起動。
3. **監視ループ:** 
    - 各プロセスの stdout/stderr を別スレッドで読み取る。
    - 読み取った行を `manager.write(source, line)` に渡す。
4. **表示制御 (Manager内部):**
    - `if source == current_focus`: `sys.stdout.write(line)`
    - `else`: `buffer.append(line)`
5. **完了通知:** プロセス終了時、`manager.finish(source)` を呼ぶ。
6. **切り替え:** 
    - `current_focus` が完了した場合、`priority_queue` から次の候補を取り出す。
    - 次の候補のバッファ済みデータを全て出力する。
    - `current_focus` を更新する。

## 5. UI/UX イメージ

```text
(Gemini is outputting...)
> [Gemini] Code looks good.
> ...

(Gemini finishes. Switch to Codex instantly.)

(Codex output flushed if buffered)
> [Codex] Found a bug.
> ...
```
