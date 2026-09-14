# Handoff

## 実施内容

- `codex/maid-goal-usecase-design`、`backup/maid-goal-design-a94616a`、`origin/codex/align-ai-maid-definitions` などから、複数キャラクター会話で再利用するキャラクター定義、会話コンテキスト、マスターコンテキスト、応答契約を抽出した。
- キャラクター定義とマスターコンテキストを、`src/app/contracts/messages/` と `src/app/application/` の再利用可能な型・サービスとして整理した。
- キャラクターの発話投稿を `CharacterSpeechMessage`、`ISpeechPublisher`、
  `ISpeechDeliveryStore` の契約として分離し、Discord Webhook の通常チャンネル・
  フォーラムスレッドへの分割投稿、送信状態の永続化・再開、投稿先検証を
  `DiscordWebhookSpeechPublisher` と `DiscordWebhookSpeechPublisherRouter` に実装した。
- 非同期ツール呼び出しの接続ライフサイクルに基づき、`src/app/infrastructure/mcp/client.py` に MCP 接続を実装した。stdio と Streamable HTTP、ツール一覧のページング、許可ツール制御、環境変数経由の認証、タイムアウト、結果正規化、接続終了処理を含む。
- LLM 呼び出しを `TextGenerationRequest`、`TextGenerationResponse`、`ITextGenerationClient` のプロバイダー非依存契約として整理した。
- Gemini と OpenAI Responses API の非同期アダプターを追加し、JSON Schema による構造化出力、タイムアウト、クライアント終了処理を実装した。
- `CharacterResponseGenerator` を追加し、キャラクター選定と応答生成、キャラクター ID、応答本文、記憶候補、選定要約の検証を実装した。
- MCP 接続処理と LLM アダプターを分離し、キャラクター側の生成器からプロバイダー SDK を直接参照しない構成にした。
- Gemini、OpenAI、MCP、キャラクター応答生成器のテストを追加した。
- `google-genai` と `openai` を `uv` で依存関係に追加した。
- 変更を `codex/add-mcp-tool-connection` のコミット `f512b60` にまとめ、`origin/codex/add-mcp-tool-connection` へ Push した。

## 検証結果

- `uv run --frozen pytest -q`: 339 passed
- `uv run --frozen ruff format .`: 成功
- `uv run --frozen ruff check .`: 成功
- `uv run --frozen pyright`: 0 errors
