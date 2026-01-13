# discord-bot-template

## 概要

**※現在製作中のプロジェクトです。予期せぬバグ、不具合などが含まれる可能性があります。**

このプロジェクトは、Discord Botの開発を効率化するためのテンプレートです。
非同期処理、依存性注入、クリーンアーキテクチャを採用し、拡張性と保守性を重視した設計になっています。
Bot Interface (Discordとのやり取り) と Worker (ビジネスロジックの実行) を分離し、スケーラビリティを高めています。

## 特徴

### 1. **アーキテクチャの分離 (Bot & Worker)**

- **Bot Process**: Discord Gatewayとの通信、コマンドの受付、レスポンスの送信を担当。軽量に保たれます。
- **Worker Process**: 重い処理やビジネスロジックの実行を担当。PostgreSQLベースのEvent Busを介してBotと連携します。

### 2. **非同期処理の活用**

- `asyncio`を使用して非同期処理を実現。
- 高速かつ効率的な処理を可能にする設計。

### 3. **依存性注入 (DI)**

- `injector`ライブラリを使用して依存性注入を実現。
- テスト容易性とモジュール間の疎結合を実現。

### 4. **Mediatorパターンの採用**

- `app/core/mediator.py`でMediatorパターンを実装。
- リクエストとハンドラーの分離により、コードの可読性と拡張性を向上。

### 5. **クリーンアーキテクチャ**

- ユースケース層 (`usecases/`) とドメイン層 (`domain/`) を明確に分離。
- ビジネスロジックとインフラストラクチャの独立性を確保。
- ドメイン層 (`domain/`) とインフラストラクチャ層 (`infrastructure/`) を完全分離。

### 6. **データベース統合**

- **PostgreSQL**: 本番環境およびEvent Busのバックエンドとして推奨。
- **SQLModel + Alembic**: 型安全なORM とマイグレーション管理。
- **クリーンアーキテクチャ準拠**: ORMモデルとドメイン集約を分離。

### 7. **Event Bus / Outbox パターン**

- **PostgreSQL Event Bus**: プロセス間の信頼性の高いメッセージングを実現。
- **Command Outbox**: WorkerからBotへの操作指示を確実に伝達。

### 8. **コグ (Cog) によるコマンド管理**

- `discord.ext.commands`のCogを使用してコマンドをモジュール化。
- Botの機能を簡単に拡張可能。

### 9. **FastAPI 統合 (Web API)**

- Discord Botと並行して動作するREST API。
- 共通のユースケースを再利用し、外部システムとの連携が可能。
- Swagger UI によるインタラクティブなドキュメント。

### 10. **型安全性とコード品質**

- **Type Checking**: `Pyright` (strict mode) による厳格な型チェック。
- **Linting & Formatting**: `Ruff` による高速なチェックと整形。
- **Pre-commit**: コミット前の自動検証。

## ディレクトリ構成

```text
.
├── app/                           # アプリケーション本体
│   ├── api/                       # Web API層
│   │   ├── __main__.py            # APIエントリーポイント (start-api)
│   │   └── routers/               # APIルーター
│   ├── bot/                       # Discord Bot層
│   │   ├── __main__.py            # Botエントリーポイント (start-bot)
│   │   └── cogs/                  # Cogモジュール
│   ├── worker/                    # Worker層 (ビジネスロジック実行)
│   │   ├── __main__.py            # Workerエントリーポイント (start-worker)
│   │   ├── consumer.py            # イベントコンシューマー
│   │   └── handlers.py            # イベントハンドラー
│   ├── core/                      # アプリケーションコア
│   │   ├── container.py           # DIコンテナ設定
│   │   ├── mediator.py            # Mediatorパターンの実装
│   │   └── result.py              # Result型定義
│   ├── domain/                    # ドメイン層
│   │   ├── aggregates/            # ドメイン集約
│   │   ├── interfaces/            # 抽象インターフェース
│   │   └── value_objects/         # 値オブジェクト
│   ├── infrastructure/            # インフラストラクチャ層
│   │   ├── database.py            # DB設定・セッション管理
│   │   ├── messaging/             # メッセージング (Event Bus)
│   │   ├── orm_models/            # ORMモデル
│   │   ├── repositories/          # リポジトリ実装
│   │   └── services/              # 外部サービス実装
│   └── usecases/                  # ユースケース層
├── alembic/                       # Alembicマイグレーション
├── docs/                          # ドキュメント
├── tests/                         # テストコード
├── .pre-commit-config.yaml        # Pre-commit設定
├── pyproject.toml                 # プロジェクト設定
└── README.md                      # このファイル
```

## 必要な環境

- Python 3.13 以上
- PostgreSQL (推奨) または SQLite (開発用、ただしEvent Bus機能には制限あり)
- パッケージ管理 [uv](https://github.com/astral-sh/uv)

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
   cp .env.example .env.local
   ```

   `.env.local`の内容を編集:

   ```bash
   # Discord Bot トークン
   DISCORD_BOT_TOKEN=your_token

   # データベースURL (PostgreSQL推奨)
   # Event Busを使用する場合はPostgreSQLが必要です
   DATABASE_URL=postgresql+asyncpg://user:password@localhost/dbname
   ```

5. データベースマイグレーションを実行:

   ```bash
   uv run alembic upgrade head
   ```

6. アプリケーションを起動:

   Botプロセス (Interface):

   ```bash
   uv run start-bot
   ```

   Workerプロセス (Business Logic):

   ```bash
   uv run start-worker
   ```

   (オプション) APIサーバー:

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
```

## テスト実行

```bash
uv run pytest
```

## アーキテクチャ

このプロジェクトは、**クリーンアーキテクチャ (Clean Architecture)** の原則に基づき、さらに **CQRS (Command Query Responsibility Segregation)** と **Event-Driven Architecture** の要素を取り入れています。

### システム構成

```text
┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│   Discord API    │ <--> │   Bot Process    │ <--> │    PostgreSQL    │
└──────────────────┘      │ (Interface Layer)│      │   (Event Bus)    │
                          └──────────────────┘      └─────────┬────────┘
                                   ^                          │
                                   │ Commands                 │ Events
                                   │ (Outbox)                 │ (Queue)
                                   │                          v
                          ┌──────────────────┐      ┌──────────────────┐
                          │    PostgreSQL    │ <--> │  Worker Process  │
                          │ (Domain Data)    │      │ (Business Logic) │
                          └──────────────────┘      └──────────────────┘
```

1. **Bot Process**: ユーザー入力を受け取り、コマンドとしてデータベース (Outbox) に保存します。また、処理結果を表示します。
2. **Worker Process**: イベントやコマンドを検知し、実際のユースケースを実行します。
3. **PostgreSQL**: データの永続化だけでなく、プロセス間の通信路 (Event Bus / Outbox) としても機能します。

### 詳細ドキュメント

プロジェクトの詳細なドキュメントは `docs/` ディレクトリにあります：

- **[アーキテクチャ設計](docs/ARCHITECTURE.md)** - システム全体のアーキテクチャ詳細
- **[Domain層実装ガイド](docs/domain/DOMAIN_IMPLEMENTATION_GUIDE.md)** - ドメインモデルの実装方法
- **[課題・改善点リスト](docs/ISSUES_AND_IMPROVEMENTS.md)** - 技術的な課題と改善提案

## TODO

- Domain層の拡充（より多くの集約の追加）
- 複数データベースソリューションへの対応（PostgreSQL、MySQL等）
- 認証、認可の仕組みの導入
- イベントソーシング対応

## ライセンス

このプロジェクトは[MITライセンス](LICENSE)の下で公開されています。
