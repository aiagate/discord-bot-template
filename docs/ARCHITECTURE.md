# アーキテクチャ設計ドキュメント

最終更新日: 2025-11-28

このドキュメントは、Discord Bot テンプレートのアーキテクチャ設計と実装パターンを詳細に説明します。

---

## アーキテクチャ概要

このプロジェクトは **クリーンアーキテクチャ（Clean Architecture）** に基づいて設計されています。

### レイヤー構造

```
┌─────────────────────────────────────────┐
│  Presentation Layer                     │  外部インターフェース
│  (Discord Bot, Cogs)                    │  - ユーザーからの入力受付
│  - app/__main__.py                      │  - 出力のフォーマット
│  - app/cogs/*.py                        │
├─────────────────────────────────────────┤
│  Application Layer                      │  ユースケース
│  (Use Cases, Mediator)                  │  - ビジネスフロー制御
│  - app/usecases/                        │  - DTOでの入出力
│  - app/core/mediator.py                 │  - Result型でのエラーハンドリング
├─────────────────────────────────────────┤
│  Domain Layer                           │  ビジネスルール
│  (Aggregates, Entities, Value Objects)  │  - 純粋なPythonオブジェクト
│  - app/domain/aggregates/               │  - フレームワーク非依存
│  - app/domain/repositories/             │  - ビジネスロジックの検証
├─────────────────────────────────────────┤
│  Infrastructure Layer                   │  技術的詳細
│  (Database, ORM, External Services)     │  - データベースアクセス
│  - app/infrastructure/database.py       │  - 外部API呼び出し
│  - app/infrastructure/orm_models/       │  - ファイルシステムアクセス
│  - app/infrastructure/repositories/     │
│  - app/infrastructure/unit_of_work.py   │
│  - app/container.py (DI)                │
└─────────────────────────────────────────┘
```

### 依存関係の方向

```
Presentation ──▶ Application ──▶ Domain ◀── Infrastructure
                                    ▲
                                    │
                            依存性の逆転原理
                          (Dependency Inversion)
```

**重要な原則**:

- 上位層は下位層に依存可能
- **下位層は上位層に依存してはならない**
- **ドメイン層は最も独立しており、他のどの層にも依存しない**
- インフラ層はドメイン層のインターフェースに依存（依存性逆転）

---

## 各レイヤーの詳細

### 1. Domain Layer（ドメイン層）

**責務**: ビジネスルールとビジネスロジックの実装

**特徴**:

- 純粋なPythonコード（dataclass、関数）
- フレームワーク非依存
- データベース、Web、UIに関する知識を持たない
- 他のどのレイヤーにも依存しない

#### 構成要素

##### 1.1 Aggregates（集約）

`app/domain/aggregates/user.py`:

```python
from app.domain.value_objects import Email, UserId

@dataclass
class User:
    """User aggregate root."""

    id: UserId
    name: str
    email: Email

    def __post_init__(self) -> None:
        # ドメインルールの検証
        if not self.name:
            raise ValueError("User name cannot be empty.")

    def change_email(self, new_email: Email) -> "User":
        """ビジネスロジック: メールアドレス変更"""
        self.email = new_email
        return self
```

**ポイント**:

- ビジネスルールを `__post_init__` で検証
- **Value Objects** (`UserId`, `Email`) を使用して型安全性を向上
- リッチドメインモデル（データだけでなく振る舞いを持つ）

##### 1.2 Repository Interfaces（リポジトリインターフェース）

`app/domain/repositories/interfaces.py`:

```python
from abc import ABC, abstractmethod
from flow_res import Result

class IRepository[T](ABC):
    """基本リポジトリインターフェース（追加・削除操作）"""

    @abstractmethod
    async def add(self, entity: T) -> Result[T, RepositoryError]:
        pass

    @abstractmethod
    async def delete(self, entity: T) -> Result[None, RepositoryError]:
        pass


class IRepositoryWithId[T, K](IRepository[T], ABC):
    """ID検索機能付きリポジトリインターフェース"""

    @abstractmethod
    async def get_by_id(self, id: K) -> Result[T, RepositoryError]:
        pass
```

**ポイント**:

- ドメイン層でインターフェースを定義
- 実装はインフラ層が担当（依存性逆転）
- Result型で型安全なエラーハンドリング

**設計判断: Protocol から ABC への移行**:

当初は `Protocol` ベースの設計を採用していましたが、DI（依存性注入）による
インターフェース分離が実現されているため、`Protocol` の構造的型付けの柔軟性は
不要であることが判明しました。

`ABC` ベースの明示的継承により、以下の利点が得られます:

- 型安全性の向上（クラス定義時にエラー検出）
- IDEサポートの改善（自動補完、リファクタリング）
- 開発者の意図の明確化
- インターフェースと実装の乖離防止

なお、`IValueObject` などのドメイン層インターフェースは、ランタイム型チェックが
必要なため、引き続き `Protocol` を使用します。

##### 1.3 Result Type（結果型）

`app/core/result.py`:

```python
@dataclass(frozen=True)
class Ok[T]:
    """成功結果"""
    value: T

@dataclass(frozen=True)
class Err[E]:
    """失敗結果"""
    error: E

Result = Ok[T] | Err[E]
```

**ポイント**:

- Rust の Result型にインスパイア
- 例外ではなく値でエラーを表現
- `map`, `and_then`, `unwrap` などのメソッドチェーンで安全な処理を実現

**使用例**:

```python
# teams_cog.py の例
message = await (
    Mediator.send_async(CreateTeamCommand(name=name))
    .and_then(lambda r: Mediator.send_async(GetTeamQuery(r.team_id)))
    .map(lambda v: f"Team Created: ID: {v.team.id}, Name: {v.team.name}")
    .unwrap()
)
```

---

### 2. Application Layer（アプリケーション層）

**責務**: ユースケースの実装、ビジネスフローの制御

**特徴**:

- ドメインオブジェクトを操作してビジネスフローを実現
- DTOで入出力を定義
- トランザクション境界の管理（Unit of Work）

#### 構成要素

##### 2.1 Use Cases（ユースケース）

各ユースケースは以下の3要素で構成:

1. **Query/Command クラス**: リクエスト
2. **Result クラス**: レスポンス
3. **Handler クラス**: 処理ロジック

**重要な設計原則**: Create系のユースケースは作成したエンティティのIDのみを返し、詳細情報の取得はGet系のユースケースに委譲します。これにより以下のSOLID原則がより厳密に守られます：

- **単一責任の原則（SRP）**: Createは「エンティティの作成」、Getは「エンティティの詳細取得」という明確な単一責任を持つ
- **開放閉鎖の原則（OCP）**: 表示ロジックをGetに一元化することで、表示形式の変更時に既存のCreateコードを変更する必要がない
- **インターフェース分離の原則（ISP）**: Createは最小限の情報（ID）のみを返し、クライアントに不要な情報を公開しない

`app/usecases/users/get_user.py`:

```python
# 1. Query（リクエスト）- IDはstringで受け取る
class GetUserQuery(Request[Result[GetUserResult, UseCaseError]]):
    def __init__(self, user_id: str) -> None:
        self.user_id = user_id

# 2. Result（レスポンス）
class GetUserResult:
    def __init__(self, user: UserDTO) -> None:
        self.user = user

# 3. Handler（処理ロジック）
class GetUserHandler(RequestHandler[GetUserQuery, Result[GetUserResult, UseCaseError]]):
    @inject
    def __init__(self, uow: IUnitOfWork) -> None:
        self._uow = uow

    async def handle(self, request: GetUserQuery) -> Result[GetUserResult, UseCaseError]:
        # 文字列からValue Objectへの変換
        user_id_result = UserId.from_primitive(request.user_id)
        if isinstance(user_id_result, Err):
            return Err(UseCaseError(type=ErrorType.VALIDATION_ERROR, ...))

        user_id = user_id_result.unwrap()

        async with self._uow:
            # リポジトリにはValue Objectでアクセス
            user_repo = self._uow.GetRepository(User, UserId)
            user_result = await user_repo.get_by_id(user_id)

            match user_result:
                case Ok(user):
                    # Domain -> DTO への変換
                    user_dto = UserDTO(
                        id=user.id.to_primitive(),
                        name=user.name,
                        email=user.email.to_primitive()
                    )
                    return Ok(GetUserResult(user_dto))
                case Err(repo_error):
                    return Err(UseCaseError.from_repo_error(repo_error))

```

**ポイント**:

- **CQRS パターン**: Query（読み取り）と Command（書き込み）を分離
- **DTO（Data Transfer Object）**: プレゼンテーション層との境界
- **依存性注入**: `@inject` デコレータで IUnitOfWork を注入
- **トランザクション**: `async with self._uow` でトランザクション管理
- **入力バリデーション**: Handler内で文字列をValue Objectに変換し、不正な値を弾く

`app/usecases/users/create_user.py` (Command例):

```python
# 1. Command（リクエスト）
class CreateUserCommand(Request[Result[CreateUserResult, UseCaseError]]):
    def __init__(self, name: str, email: str) -> None:
        self.name = name
        self.email = email

# 2. Result（レスポンス）- IDのみを返す
class CreateUserResult:
    def __init__(self, user_id: str) -> None:
        self.user_id = user_id

# 3. Handler（処理ロジック）
class CreateUserHandler(RequestHandler[CreateUserCommand, Result[CreateUserResult, UseCaseError]]):
    @inject
    def __init__(self, uow: IUnitOfWork) -> None:
        self._uow = uow

    async def handle(self, request: CreateUserCommand) -> Result[CreateUserResult, UseCaseError]:
        # Value Objectの生成とドメインルールの検証
        user_result = Ok(User(
            id=UserId.generate().unwrap(),
            name=request.name,
            email=Email.from_primitive(request.email).unwrap()
        ))

        if isinstance(user_result, Err):
            return Err(UseCaseError(...)) # エラー処理

        user = user_result.unwrap()

        async with self._uow:
            user_repo = self._uow.GetRepository(User)
            save_result = await user_repo.add(user)

            match save_result:
                case Ok(saved_user):
                    # IDのみを文字列で返す
                    return Ok(CreateUserResult(saved_user.id.to_primitive()))
                case Err(repo_error):
                    return Err(UseCaseError.from_repo_error(repo_error))
```

**Createの設計パターン**: CreateユースケースはIDのみを返します。プレゼンテーション層（Cog）では、返されたIDを使ってGetユースケースを呼び出すことで、詳細情報を取得します。このフローは `Result` 型の `and_then` メソッドを使うことで、よりクリーンに実装できます。

```python
# app/cogs/teams_cog.py
@teams.command(name="create")
async def teams_create(self, ctx: commands.Context[commands.Bot], name: str) -> None:
    """Create new team. Usage: !teams create <name>"""
    message = await (
        # 1. Createを実行してIDを取得
        Mediator.send_async(CreateTeamCommand(name=name))
        # 2. 成功すれば、返されたIDでGetを実行
        .and_then(
            lambda result: Mediator.send_async(GetTeamQuery(result.team_id))
        )
        # 3. Getの成功結果をメッセージにフォーマット
        .map(
            lambda value: (
                f"Team Created:\nID: {value.team.id}\nName: {value.team.name}"
            )
        )
        # 4. 最終的な結果 (成功メッセージ or エラー) を取り出す
        .unwrap()
    )
    await ctx.send(content=message)
```

この設計により：

- Createは「作成してIDを返す」という単一責任に専念
- Getは「詳細情報の取得と形式化」という単一責任に専念
- 結果の表示形式を変更する場合、Getの実装のみを変更すればよい（OCP）
- `and_then`でフローが明確になり、ネストが深くならない

##### 2.2 Mediator Pattern（メディエーターパターン）

`app/core/mediator.py`:

```python
class Mediator:
    """CQRS-style mediator for request/response."""

    @classmethod
    async def send_async[TResponse](
        cls, request: Request[TResponse]
    ) -> TResponse:
        """Send request to handler and get response."""
        handler = cls._get_handler(type(request))
        return await handler.handle(request)
```

**利点**:

- プレゼンテーション層とアプリケーション層の疎結合
- ハンドラーの自動登録（メタクラス使用）
- 一貫したリクエスト/レスポンスパターン

**使用例**:

```python
# Discord Cog から
query = GetUserQuery(user_id="01H...Z")
result = await Mediator.send_async(query)
```

##### 2.3 DTOs（Data Transfer Objects）

`app/usecases/users/user_dto.py`:

```python
@dataclass(frozen=True)
class UserDTO:
    """User Data Transfer Object."""
    id: str  # ULID
    name: str
    email: str
```

**ポイント**:

- イミュータブル（`frozen=True`）
- ドメイン集約とは別物（表示用）
- プレゼンテーション層に公開する情報はプリミティブ型（`str`, `int`など）
- Value Objectは `to_primitive()` で変換されて格納される

---

### 3. Infrastructure Layer（インフラストラクチャ層）

**責務**: 技術的な詳細の実装（DB、外部API等）

**特徴**:

- ドメイン層のインターフェースを実装
- ORM、データベース接続、外部サービスとの通信
- ドメイン集約とORMモデルの変換

#### 構成要素

##### 3.1 ORM Models

`app/infrastructure/orm_models/user_orm.py`:

```python
from datetime import datetime
from sqlalchemy import Column, DateTime, func
from sqlmodel import Field, SQLModel

class UserORM(SQLModel, table=True):
    """User table ORM model."""
    __tablename__ = "users"

    id: str | None = Field(default=None, primary_key=True, max_length=26)
    name: str = Field(max_length=255, index=True)
    email: str = Field(max_length=255, unique=True, index=True)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
```

**ポイント**:

- **ドメイン集約とは完全に分離**
- データベーステーブルの表現
- IDはULIDのため `str` 型、タイムスタンプは `datetime` 型

##### 3.2 Generic Repository

`app/infrastructure/repositories/generic_repository.py`:

```python
class GenericRepository[T, K](IRepositoryWithId[T, K]):
    """汎用リポジトリ実装"""

    def __init__(
        self,
        session: AsyncSession,
        entity_type: type[T],
    ) -> None:
        self._session = session
        self._entity_type = entity_type
        self._orm_type = ORMMappingRegistry.get_orm_type(entity_type)

    async def get_by_id(self, id: K) -> Result[T, RepositoryError]:
        # Value Object をプリミティブ型に変換して検索
        primitive_id = id.to_primitive() if isinstance(id, IValueObject) else id

        statement = select(self._orm_type).where(self._orm_type.id == primitive_id)
        result = await self._session.execute(statement)
        orm_instance = result.scalar_one_or_none()

        if orm_instance is None:
            return Err(RepositoryError(type=RepositoryErrorType.NOT_FOUND, ...))

        # ORM → Domain 自動変換
        return Ok(ORMMappingRegistry.from_orm(orm_instance, self._entity_type))
```

**ポイント**:

- 型安全な汎用実装（Generics使用）
- ORM ↔ Domain の変換を `ORMMappingRegistry` に委譲
- Result型でエラーハンドリング

##### 3.3 ORM Mapping Registry

ドメイン集約とORMモデル間の変換は、`ORMMappingRegistry` によって一元管理されます。

`app/infrastructure/orm_mapping.py`:

```python
# registry_orm_mapping(DomainClass, ORMClass) でマッピングを登録
# from_orm(orm_instance, domain_type) でORMからドメインへ変換
# to_orm(domain_instance) でドメインからORMへ変換
```

このレジストリは、リフレクションと型ヒントを利用して、`IValueObject` を含むドメイン集約とORMモデル間の変換を自動的に行います。これにより、変換ロジックを都度記述する必要がなくなり、保守性が大幅に向上します。

**利点**:

- **型安全**: 型アノテーションベースで自動変換
- **保守性向上**: 新しいValue Objectを追加しても変換コード不要
- **依存性逆転**: ドメイン層がインフラ層に依存しない
- **DRY原則**: 変換ロジックの重複を排除
- **一元管理**: 全てのマッピングを `orm_registry.py` で集中管理

##### 3.4 Unit of Work Pattern

`app/infrastructure/unit_of_work.py`:

```python
class SQLAlchemyUnitOfWork(IUnitOfWork):
    """トランザクション境界を管理"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        # ...

    def GetRepository[T, K](...) -> IRepository[T, K]:
        # リポジトリの取得（キャッシュ付き）
        # ...

    async def __aenter__(self) -> "SQLAlchemyUnitOfWork":
        # ...

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is None:
            await self.commit()  # 成功時はコミット
        else:
            await self.rollback()  # 例外時はロールバック
        # ...
```

**ポイント**:

- **トランザクション境界の明確化**
- リポジトリのキャッシュ（同一トランザクション内で再利用）
- 自動コミット/ロールバック（コンテキストマネージャー）

##### 3.5 Dependency Injection Container

`app/container.py`:

```python
from injector import Binder, Module, singleton
from app.infrastructure.orm_registry import init_orm_mappings

class AppModule(Module):
    """DIコンテナの設定"""

    def configure(self, binder: Binder) -> None:
        # アプリケーション起動時に一度だけORMマッピングを初期化
        init_orm_mappings()

        # セッションファクトリをシングルトンでバインド
        binder.bind(async_sessionmaker[AsyncSession], to=get_session_factory(), ...)

        # UnitOfWork をリクエストごとに生成
        binder.bind(IUnitOfWork, to=SQLAlchemyUnitOfWork)
```

**ポイント**:

- `injector` ライブラリを使用
- `init_orm_mappings()` をコンテナ設定時に呼び出し、マッピングを保証
- テスト時のモック注入が容易

---

### 4. Presentation Layer（プレゼンテーション層）

**責務**: ユーザーインターフェース、入出力の制御

**特徴**:

- Discord Bot のコマンド実装
- 入力の受付とバリデーション
- 出力のフォーマット

#### 構成要素

##### 4.1 Discord Bot Entry Point

`app/__main__.py`:

```python
class MyBot(commands.Bot):
    # ...
    async def setup_hook(self) -> None:
        await self._init_database()
        await self.load_cogs()

    async def _init_database(self) -> None:
        # ... DIコンテナとMediatorの初期化
        injector = Injector([container.configure])
        Mediator.initialize(injector)

    async def load_cogs(self) -> None:
        # Cogモジュールをインポートしてロード
        await self.load_extension(teams_cog.__name__)
        await self.load_extension(users_cog.__name__)

bot = MyBot()
bot.run(token)
```

##### 4.2 Discord Cogs

`app/cogs/users_cog.py`:

```python
class UsersCog(commands.Cog):
    # ...
    @users.command(name="get")
    async def users_get(
        self, ctx: commands.Context[commands.Bot], user_id: str
    ) -> None:
        """Get user by ID."""
        query = GetUserQuery(user_id=user_id) # 文字列でQueryを作成
        result = await Mediator.send_async(query)

        match result:
            case Ok(ok_value):
                user = ok_value.user
                await ctx.send(
                    f"**User #{user.id}**\n"
                    f"Name: {user.name}\n"
                    f"Email: {user.email}"
                )
            case Err(err_value):
                await ctx.send(f"❌ Error: {err_value.message}")
```

**ポイント**:

- Mediator経由でユースケースを呼び出し
- Result型でエラーハンドリング
- Discord用のメッセージフォーマット
- IDは文字列として受け取る

---

## データフロー

### Query（読み取り）のフロー

```
1. User: !users get 01H...
   ↓
2. UsersCog: GetUserQuery(user_id="01H...")
   ↓
3. Mediator -> GetUserHandler
   ↓ UserId.from_primitive("01H...")
4. UoW -> GenericRepository.get_by_id(UserId(...))
   ↓ SELECT ... WHERE id = "01H..."
5. Database -> UserORM
   ↓ ORMMappingRegistry.from_orm()
6. User (Domain) -> UserDTO
   ↓ Ok(GetUserResult(UserDTO))
7. UsersCog: formats message
   ↓
8. User: receives message
```

### Command（書き込み）のフロー

```
1. User: !teams create "My Team"
   ↓
2. TeamsCog: CreateTeamCommand(name="My Team")
   ↓
3. Mediator -> CreateTeamHandler -> Team(id=TeamId.generate(), ...)
   ↓ UoW -> GenericRepository.add()
4. ORMMappingRegistry.to_orm() -> TeamORM
   ↓ INSERT ...
5. Database commits
   ↓ Ok(CreateTeamResult(team_id="01H..."))
6. TeamsCog: .and_then() is called
   ↓ GetTeamQuery(team_id="01H...")
7. (Queryフローと同様の処理)
   ↓ Ok(GetTeamResult(TeamDTO))
8. TeamsCog: .map() formats message
   ↓
9. User: receives success message
```

**重要**: Create操作は作成したエンティティのIDのみを返します。詳細情報の取得は必ずGet操作を経由することで、表示ロジックが一元化され、SOLID原則（特にSRPとOCP）が守られます。`and_then` を使ったフローにより、この処理が簡潔に表現されます。

---

## テスト戦略

### 1. ユニットテスト

`tests/domain/aggregates/test_user.py`:

```python
import pytest

@pytest.mark.asyncio
async def test_create_user_with_empty_name_raises_error() -> None:
    with pytest.raises(ValueError, match="User name cannot be empty"):
        User(id=UserId.generate().unwrap(), name="", email=Email.from_primitive("a@a.com").unwrap())
```

### 2. 統合テスト

`tests/usecases/users/test_get_user.py`:

```python
import pytest
from app.domain.value_objects import UserId, Email

@pytest.mark.asyncio
async def test_get_user_handler(uow: IUnitOfWork) -> None:
    # Setup
    user = User(id=UserId.generate().unwrap(), name="Bob", email=Email.from_primitive("bob@a.com").unwrap())
    async with uow:
        repo = uow.GetRepository(User, UserId)
        await repo.add(user)
        await uow.commit()

    # Execute
    handler = GetUserHandler(uow)
    query = GetUserQuery(user_id=user.id.to_primitive())
    result = await handler.handle(query)

    # Assert
    assert isinstance(result, Ok)
    assert result.value.user.name == "Bob"
```

**特徴**:

- テストには `@pytest.mark.asyncio` を使用
- データベースを含む
- トランザクション動作の検証

---

## 依存関係管理

### プロダクション依存関係

```toml
[project.dependencies]
aiosqlite = ">=0.21.0"
alembic = ">=1.17.2"
discord-py = ">=2.5.2"
injector = ">=0.22.0"
python-dotenv = ">=1.2.1"
python-ulid = ">=3.1.0"   # ULID生成
sqlmodel = ">=0.0.24"
```

### 開発依存関係

```toml
[dependency-groups.dev]
# anyio は pytest-asyncio の依存関係として導入されます
pre-commit = ">=4.5.0"
pyright = ">=1.1.407"
pytest = ">=8.3.5"
pytest-asyncio = ">=1.3.0" # 非同期テストランナー
pytest-cov = ">=7.0.0"
pytest-mock = ">=3.14.0"
ruff = ">=0.14.6"
```

---

## 拡張方法

### 新しい集約の追加

1. **ドメイン集約とValue Objectを作成**

```python
# app/domain/aggregates/guild.py
@dataclass
class Guild:
    id: GuildId
    name: str
```

1. **ORMモデルを作成**

```python
# app/infrastructure/orm_models/guild_orm.py
class GuildORM(SQLModel, table=True):
    __tablename__ = "guilds"
    id: str | None = Field(default=None, primary_key=True)
    name: str
```

1. **マッピングを登録**

```python
# app/infrastructure/orm_registry.py
from app.domain.aggregates.guild import Guild
from app.infrastructure.orm_models.guild_orm import GuildORM

def init_orm_mappings() -> None:
    """Initialize all ORM mappings."""
    register_orm_mapping(User, UserORM)
    register_orm_mapping(Team, TeamORM)
    register_orm_mapping(Guild, GuildORM) # ここに追加
```

`init_orm_mappings` はアプリ起動時に `app/container.py` から自動で呼び出されるため、ここの追加だけでマッピングは完了します。

1. **ユースケースを作成**

```python
# app/usecases/guilds/get_guild.py
# ... GetGuildQuery, GetGuildHandler などを実装
```

1. **Cogを作成**

```python
# app/cogs/guilds_cog.py
# ... Mediator経由でユースケースを呼び出すコマンドを実装
```

### データベースマイグレーション

```bash
# スキーマ変更後、マイグレーションを生成
uv run alembic revision --autogenerate -m "Add guilds table"

# マイグレーション適用
uv run alembic upgrade head
```

---

## 📚 参考資料

- [Clean Architecture (Robert C. Martin)](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html)
- [Domain-Driven Design](https://www.domainlanguage.com/ddd/)
- [CQRS Pattern](https://martinfowler.com/bliki/CQRS.html)
- [Repository Pattern](https://martinfowler.com/eaaCatalog/repository.html)
- [Unit of Work Pattern](https://martinfowler.com/eaaCatalog/unitOfWork.html)

---

**ドキュメント作成者**: Claude Code
**作成日**: 2025-11-26
**バージョン**: 1.0
