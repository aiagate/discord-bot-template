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

- **SQLModel + Alembic**: 型安全なORM とマイグレーション管理。
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

- `pytest`と`pytest-asyncio`を使用したテスト環境を構築。
- `pytest-cov`によるコードカバレッジ測定。
- インメモリSQLiteを使用した高速なテスト実行。

### 10. **コード品質管理**

- `Ruff`: 高速なコードフォーマッターとリンター。
- `Pyright`: 厳格な型チェック (strict モード)。
- `pre-commit`: Git コミット前の自動チェック。

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
│   ├── core/                      # アプリケーションコア (Result, Mediatorなど)
│   ├── container.py               # DIコンテナ設定
│   ├── domain/                    # ドメイン層
│   │   ├── aggregates/            # ドメイン集約 (user.py, team.py)
│   │   ├── interfaces/            # 抽象インターフェース
│   │   ├── repositories/          # リポジトリインターフェース
│   │   └── value_objects/         # 値オブジェクト
│   ├── infrastructure/            # インフラストラクチャ層
│   │   ├── database.py            # DB設定・セッション管理
│   │   ├── orm_models/            # ORMモデル (user_orm.py, team_orm.py)
│   │   └── repositories/          # リポジトリ実装
│   └── usecases/                  # ユースケース層
│       ├── users/                 # ユーザー関連ユースケース
│       └── teams/                 # チーム関連ユースケース
├── alembic/                       # Alembicマイグレーション
│   └── versions/                  # マイグレーションファイル
├── docs/                          # ドキュメント
├── tests/                         # テストコード
├── .pre-commit-config.yaml        # Pre-commit設定
├── pyproject.toml                 # プロジェクト設定
└── README.md                      # このファイル
```

## 必要な環境

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
   ```

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
- **[課題・改善点リスト](docs/ISSUES_AND_IMPROVEMENTS.md)** - 技術的な課題と改善提案

## TODO

- Domain層の拡充（より多くの集約の追加）
- 複数データベースソリューションへの対応（PostgreSQL、MySQL等）
- 認証、認可の仕組みの導入
- イベントソーシング対応

## ライセンス

このプロジェクトは[MITライセンス](LICENSE)の下で公開されています。
