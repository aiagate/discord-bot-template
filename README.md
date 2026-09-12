# discord-bot-template

## 概要

**※現在製作中のプロジェクトです。予期せぬバグ、不具合などが含まれる可能性があります。**

このプロジェクトは、Discord Botの開発を効率化するためのテンプレートです。
非同期処理、依存性注入、クリーンアーキテクチャを採用し、拡張性と保守性を重視した設計になっています。

## 特徴

### 1. **非同期処理の活用**

- `asyncio`を使用して非同期処理を実現。
- 高速かつ効率的な処理を可能にする設計。

### 2. **依存性注入 (DI)**

- `injector`ライブラリを使用して依存性注入を実現。
- テスト容易性とモジュール間の疎結合を実現。

### 3. **Mediatorパターンの採用**

- `flow-med`ライブラリを使用してMediatorパターンを実現。
- リクエストとハンドラーの分離により、コードの可読性と拡張性を向上。

### 4. **クリーンアーキテクチャ**

- ユースケース層 (`usecases/`) とドメイン層 (`domain/`) を明確に分離。
- ビジネスロジックとインフラストラクチャの独立性を確保。
- ドメイン層 (`domain/`) とインフラストラクチャ層 (`infrastructure/`) を完全分離。

### 5. **データベース統合**

- **SQLModel + Alembic**: 型安全なORMとマイグレーション管理。
- **非同期データベース**: aiosqlite による非同期SQLite操作。
- **クリーンアーキテクチャ準拠**: ORMモデルとドメイン集約を分離。
- **自動マイグレーション**: Alembicによるスキーマバージョン管理。

### 6. **コグ (Cog) によるコマンド管理**

- `discord.ext.commands`のCogを使用してコマンドをモジュール化。
- Botの機能を簡単に拡張可能。

### 7. **FastAPI 統合 (Web API)**

- Discord Botと並行して動作するREST API。
- 共通のユースケースを再利用し、外部システムとの連携が可能。
- Swagger UI によるインタラクティブなドキュメント。

### 8. **型安全性**

- Pythonの型ヒントを活用し、静的解析ツールによるエラー検出を強化。

### 9. **テスト環境の整備**

- `pytest`とAnyIOのpytestプラグインを使用したテスト環境を構築。
- `pytest-cov`によるコードカバレッジ測定。
- インメモリSQLiteを使用した高速なテスト実行。

### 10. **コード品質管理**

- `Ruff`: 高速なコードフォーマッターとリンター。
- `Pyright`: 厳格な型チェック (strict モード)。
- `pre-commit`: Git コミット前の自動チェック。

## ディレクトリ構成

```text
.
├── src/app/                       # アプリケーション本体
│   ├── application/               # アプリケーション共通処理
│   ├── contracts/                 # ポートとメッセージ契約
│   ├── container.py               # DIコンテナ設定
│   ├── domain/                    # ドメイン層
│   │   ├── aggregates/            # ドメイン集約
│   │   ├── interfaces/            # 抽象インターフェース
│   │   ├── queries/               # ドメインクエリ
│   │   ├── repositories/          # リポジトリインターフェース
│   │   └── value_objects/         # 値オブジェクト
│   ├── infrastructure/            # インフラストラクチャ層
│   │   ├── database.py            # DB設定・セッション管理
│   │   ├── memory/                # Markdown記憶ストア
│   │   ├── orm_models/            # ORMモデル
│   │   ├── queries/               # クエリ実装
│   │   └── repositories/          # リポジトリ実装
│   ├── presentation/              # 外部入口
│   │   ├── api/                   # Web API (start-api)
│   │   ├── bot/                   # Discord Bot (start-bot)
│   │   ├── line/                  # LINE Bot (start-line)
│   │   └── worker/                # 日次ワーカー (start-worker)
│   ├── usecases/                  # ユースケース層
│   │   ├── chat/                  # チャット関連
│   │   ├── memory/                # 長期記憶関連
│   │   ├── users/                 # ユーザー関連
│   │   └── teams/                 # チーム関連
│   └── ...
├── alembic/                       # Alembicマイグレーション
│   └── versions/                  # マイグレーションファイル
├── docs/                          # ドキュメント
├── tests/                         # テストコード
├── .pre-commit-config.yaml        # Pre-commit設定
├── pyproject.toml                 # プロジェクト設定
└── README.md                      # このファイル
```

## 必要な環境

DiscordからLiliaに調査、Noaにコーディングを依頼する場合は、
[キャラクター作業の設定と使い方](docs/character-work.md)を参照してください。

- Python 3.13 以上
- パッケージ管理 [uv](https://github.com/astral-sh/uv)
- 必要な依存関係は`pyproject.toml`に記載されています。

## セットアップ

1. 仮想環境を作成:

   ```bash
   uv venv -p 3.13 .venv
   source .venv/bin/activate  # Windows(PS)の場合は .venv\Scripts\activate
   ```

2. 依存関係をインストール:

   ```bash
   uv sync
   ```

3. Pre-commit フックをインストール:

   ```bash
   uv run pre-commit install
   ```

4. 環境変数を設定:

   `.env.example`を`.env`または`.env.local`にコピーして編集:

   ```bash
   # .env.local を作成
   cp .env.example .env.local
   ```

   `.env.local`の内容を編集:

   ```bash
   # Discord Bot トークン（必須）
   DISCORD_BOT_TOKEN=your_discord_bot_token_here

   # データベースURL（オプション、デフォルト: sqlite+aiosqlite:///./bot.db）
   DATABASE_URL=sqlite+aiosqlite:///./bot.db

   # AIキャラクター応答（任意。キー、Webhook URLリスト、Guild IDで有効）
   GEMINI_API_KEY=your_gemini_api_key_here
   GEMINI_MODEL=gemini-3.8-flash
   DISCORD_CHARACTER_WEBHOOK_URLS_JSON='["https://discord.com/api/webhooks/..."]'
   DISCORD_CHARACTER_GUILD_ID=123456789012345678
   DISCORD_CHARACTER_MASTER_USER_ID=234567890123456789
   ```

   `DISCORD_CHARACTER_WEBHOOK_URLS_JSON` にはWebhook URLのJSON配列を設定でき、
   複数のテキスト／フォーラムチャンネルを同時に有効化できます。各URLは指定した
   Guild内の異なるチャンネルを指す必要があり、同じチャンネルを複数指定するとAI
   応答全体が無効になります。テキストチャンネルではそのチャンネル、フォーラムチャンネルでは各投稿（Thread）を会話単位として、
   人間または外部Webhookの投稿を受信順に処理します。Geminiがキャラクター1人を選んで返信します。
   メンションは不要です。他Botの投稿は会話履歴へ保存し、外部Webhookの投稿は
   `author_kind: webhook` として送信元ID・表示名を付けたうえで返信生成に渡します。
   対象外チャンネルの外部Webhookは、最初に設定されたテキストチャンネルをメインの返信先として
   フォールバックします。対象外チャンネルの人間投稿は通常返信の対象外ですが、Timesを設定した
   場合は同じGuild内のTimesの話題として利用します。他Bot・外部Webhook・コマンド・Botへの
   メンションだけの投稿はTimesの発火対象外です。
   当システムが使用するWebhookの投稿はループ防止のため除外します。

   `DISCORD_CHARACTER_MASTER_USER_ID` は任意の固定マスターIDです。キャラクター選定・
   通常返信・Timesのコンテキストに `master.user_id` と `master.mention`（`<@ID>`）を渡します。
   本文にこの表記を含めた場合だけ、そのユーザーへのメンションを許可します。
   他ユーザー・ロール・全体へのメンションは無効です。未設定なら `master` は `null` で、
   メンションは無効のままです。不正なIDを設定するとAI応答を無効にします。

   マスターの好みや継続中の目標など、個人設定（ChatGPTのパーソナライズ相当）は、
   リポジトリルートの `master_context.md` にMarkdownで記述できます。任意設定のため、
   ファイルが存在しない場合は読み込まれません。利用時は `master_context.example.md` を
   コピーして作成してください。内容はBot起動時に読み込まれ、キャラクター選定・通常返信・
   Timesのコンテキスト（`master.context`）として渡されます（最大8,000文字）。
   変更の反映にはBotの再起動が必要です。このファイルはGit管理対象外ですが、
   内容はGeminiへ送信されるため、個人情報や認証情報などの機密情報は記述しないでください。

   キー・Webhook URLリスト・Guild IDの不足、キャラクター設定の不備、いずれかの
   送信先の検証失敗があればAIだけを無効にします。Bot・API・LINEの通常機能はAI設定を読み込まずに
   利用できます。開発用依存にはSDKを含みます。本番でAIを使う場合は
   `uv run --frozen --no-dev --extra ai start-bot`、使わない場合は
   `uv run --frozen --no-dev start-bot` で起動できます。

   キャラクターはリポジトリルートの `characters.override.json` で上書きできます。
   `CHARACTER_DEFINITIONS_PATH` で別ファイルを指定する場合、相対パスの基準も
   リポジトリルートです。[会話仕様・負荷上限・配信復旧](docs/adr/0002-optional-character-responses.md)
   に運用条件と設定例を記載しています。

   #### ユーザー長期記憶（任意）

   ユーザー別の長期記憶を使う場合は、まず `!users create <name> <email>` で
   canonical Userを作成し、返されたUser IDと外部参加者IDを
   `user_channel_identities`へ運用者が明示的に登録します。自動で異なる外部IDを
   同一人物へ統合することはありません。例:

   ```sql
   INSERT INTO user_channel_identities
     (platform, external_participant_id, user_id, created_at)
   VALUES ('DISCORD', '<discord-user-id>', '<canonical-user-id>', CURRENT_TIMESTAMP);
   ```

   DBマイグレーション適用後、次のワーカーを1プロセスだけ起動してください。毎日03:00 JSTに、
   前日までのraw chatをGeminiで評価し、`memory/users/<user-id>/`へProfileとTimelineを
   原子的に保存します。`WORKER_RUN_ONCE=1`なら1回だけ実行して終了します。

   ```bash
   uv run --frozen --no-dev --extra ai start-worker
   # 動作確認や手動実行
   WORKER_RUN_ONCE=1 uv run --frozen --no-dev --extra ai start-worker
   ```

   未対応の外部IDの投稿もraw chatとして保存しますが、個人メモリには取り込みません。
   既存の投稿へ自動で所有権を遡及付与しないため、対応表を登録済みの既存投稿を対象にする場合は、
   内容を確認してから個別に `chat_messages.user_id` をバックフィルしてください。
   キャラクター単位の共有記憶（`memory/characters`）は、このユーザー記憶とは別系統です。
   詳細な境界とシーケンス図は
   [ADR 0003](docs/adr/0003-user-owned-long-term-memory.md)を参照してください。

5. データベースマイグレーションを実行:

   ```bash
   # マイグレーション適用
   uv run alembic upgrade head

   # マイグレーション状態確認
   uv run alembic current
   ```

6. アプリケーションを起動:

   Discord Botを起動:

   ```bash
   uv run start-bot
   ```

   または、Web APIサーバーを起動:

   ```bash
   uv run start-api
   ```

## データベース管理

### マイグレーション操作

```bash
# スキーマ変更後、マイグレーションを自動生成
uv run alembic revision --autogenerate -m "Add new field"

# マイグレーション適用
uv run alembic upgrade head

# 1つ前に戻す
uv run alembic downgrade -1

# 現在のマイグレーション確認
uv run alembic current

# マイグレーション履歴表示
uv run alembic history
```

### データベース構造

- **使用DB**: SQLite (開発時) / PostgreSQL (本番推奨)
- **ORM**: SQLModel
- **マイグレーション**: Alembic
- **非同期対応**: aiosqlite

## テスト実行

```bash
# 全テスト実行
uv run pytest

# カバレッジ付きで実行
uv run pytest --cov=app --cov-report=term-missing

# 特定のテストファイルのみ実行
uv run pytest tests/infrastructure/test_repositories.py

# 詳細な出力
uv run pytest -v
```

## コード品質チェック

```bash
# フォーマット
uv run ruff format .

# リントチェック
uv run ruff check .

# リント自動修正
uv run ruff check . --fix

# 型チェック
uv run pyright

# 全チェック実行
uv run ruff format . && \
uv run ruff check . --fix && \
uv run pyright && \
uv run pytest
```

## 利用可能なDiscordコマンド

### ユーザー管理 (Users)

- `!users get <user_id>`: ユーザー情報を取得
- `!users create <name> <email>`: 新規ユーザーを作成

### チーム管理 (Teams)

- `!teams get <team_id>`: チーム情報を取得
- `!teams create <name>`: 新規チームを作成
- `!teams update <team_id> <new_name>`: チーム名を更新
- `!teams join <team_id> <user_id>`: チームに参加 (即時)
- `!teams request <team_id> <user_id>`: チーム参加リクエストを送信

### メンバーシップ管理 (Memberships)

- `!memberships approve <membership_id>`: 参加リクエストを承認
- `!memberships leave <membership_id>`: チームから脱退
- `!memberships role <membership_id> <role>`: メンバーのロールを変更

## アーキテクチャ

このテンプレートは以下のレイヤーで構成されています：

```text
┌─────────────────────────────────────┐  ┌─────────────────────────────────────┐
│    Presentation Layer (Web API)     │  │  Presentation Layer (Discord Bot)   │
│           (FastAPI)                 │  │          (discord.py)               │
└──────────────────┬──────────────────┘  └──────────────────┬──────────────────┘
                   │                                        │
┌──────────────────▼────────────────────────────────────────▼──────────────────┐
│                        Application Layer (UseCases)                          │
├──────────────────────────────────────────────────────────────────────────────┤
│                         Domain Layer (Aggregates)                            │
├──────────────────────────────────────────────────────────────────────────────┤
│                     Infrastructure Layer (Repository)                        │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 依存関係の方向

- 上位層から下位層への依存のみ許可
- ドメイン層はインフラストラクチャに依存しない
- リポジトリパターンで永続化を抽象化

### 詳細ドキュメント

プロジェクトの詳細なドキュメントは `docs/` ディレクトリにあります：

- **[アーキテクチャ設計](docs/ARCHITECTURE.md)** - システム全体のアーキテクチャ詳細
- **[Domain層実装ガイド](docs/domain/DOMAIN_IMPLEMENTATION_GUIDE.md)** - ドメインモデルの実装方法

## TODO

- Domain層の拡充（より多くの集約の追加）
- 複数データベースソリューションへの対応（PostgreSQL、MySQL等）
- 認証、認可の仕組みの導入
- イベントソーシング対応

## ライセンス

このプロジェクトは[MITライセンス](LICENSE)の下で公開されています。
