# アーキテクチャ設計ドキュメント

最終更新日: 2026-09-12

このドキュメントは、Discord Bot テンプレートのアーキテクチャ設計と実装パターンを詳細に説明します。

---

## アーキテクチャ概要

このプロジェクトは **クリーンアーキテクチャ（Clean Architecture）** に基づいて設計されています。

現行コードで確定しているドメイン境界と用語は
[現行のドメイン境界と用語集](./domain/BOUNDARIES_AND_GLOSSARY.md) にまとめています。
このテンプレートでは、未確定のコアドメインやサービス分割を仮定しません。

### レイヤー構造

```
┌─────────────────────────────────────────────┐
│  Presentation Layer                         │  外部インターフェース
│  (Discord Bot, Cogs)                        │  - ユーザーからの入力受付
│  - src/app/presentation/bot/__main__.py      │  - 出力のフォーマット
│  - src/app/presentation/bot/cogs/*.py       │
├─────────────────────────────────────────────┤
│  Application Layer                          │  ユースケース
│  (Use Cases, Mediator)                      │  - ビジネスフロー制御
│  - src/app/application/                     │  - Mediatorの構成
│  - src/app/usecases/                        │  - DTOでの入出力
│  - flow-med (External Library)              │  - Result型でのエラーハンドリング
├─────────────────────────────────────────────┤
│  Domain Layer                               │  ビジネスルール
│  (Aggregates, Entities, Value Objects)      │  - 純粋なPythonオブジェクト
│  - src/app/domain/aggregates/               │  - フレームワーク非依存
│  - src/app/domain/repositories/             │  - 汎用Repository契約
├─────────────────────────────────────────────┤
│  Contracts / Ports                          │  アプリケーション境界
│  - src/app/contracts/ports/                 │  - UoW・読み取りQuery・外部サービス契約
├─────────────────────────────────────────────┤
│  Infrastructure Layer                       │  技術的詳細
│  (Database, ORM, External Services)         │  - データベースアクセス
│  - src/app/infrastructure/database.py       │  - 外部API呼び出し
│  - src/app/infrastructure/orm_models/       │  - ファイルシステムアクセス
│  - src/app/infrastructure/repositories/     │
│  - src/app/infrastructure/unit_of_work.py   │
│  - src/app/container.py (DI)                │
└─────────────────────────────────────────────┘
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
- `IUnitOfWork` と `IChatHistoryQuery` は `contracts/ports` に置き、Domainから参照しない
- チャット履歴QueryはUnit of Workに含めず、呼び出しごとに読み取りセッションを閉じる
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

`src/app/domain/aggregates/user.py`:

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

`src/app/domain/repositories/interfaces.py`:

```python
from abc import ABC, abstractmethod
from flow_res import Result

class IRepository[T](ABC):
    """基本リポジトリインターフェース（追加・更新操作）"""

    @abstractmethod
    async def add(self, entity: T) -> Result[T, RepositoryError]:
        pass

    @abstractmethod
    async def update(self, entity: T) -> Result[T, RepositoryError]:
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

`IRepository` と `RepositoryError` はDomainの汎用契約である。トランザクションの
ライフサイクルを表す `IUnitOfWork` と読み取り専用の `IChatHistoryQuery` は、
Domainから独立した `src/app/contracts/ports/` のApplicationポートである。

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

`Result`、`Ok`、`Err`、`AwaitableResult` は `flow_res` が提供します。
アプリケーション固有のエラー型は
[src/app/usecases/result.py](../src/app/usecases/result.py) に定義しています。

各Handlerの戻り値は `Result[出力DTO, UseCaseResultError]` です。
`UseCaseResultError` は `RepositoryError | UseCaseError` の型エイリアスであり、
Handlerはリポジトリのエラーをそのまま返し、入力検証やドメイン上のエラーだけを
`UseCaseError` に変換します。

`Result` のチェーンは、Handlerを呼び出すプレゼンテーション側で利用できます。
実際の呼び出し方は
[src/app/presentation/bot/cogs/teams_cog.py](../src/app/presentation/bot/cogs/teams_cog.py)
を参照してください。

---

### 2. Application Layer（アプリケーション層）

**責務**: ユースケースの実装、ビジネスフローの制御

**特徴**:

- ドメインオブジェクトを操作してビジネスフローを実現
- DTOで入出力を定義
- トランザクション境界の管理（Unit of Work）

#### 構成要素

##### 2.1 Use Cases（ユースケース）

各ユースケースのリクエスト、結果DTO、Handlerは、ユースケースごとのモジュールに
まとめます。たとえば、[GetUserの実装](../src/app/usecases/users/get_user.py) と
[CreateUserの実装](../src/app/usecases/users/create_user.py) を参照してください。

Handlerの契約は次のとおりです。

- `Request` は文字列などの外部入力を受け取ります。
- Handlerは `Result[ResultDTO, UseCaseResultError]` を返します。
- 入力検証やドメイン上の失敗は `UseCaseError` に変換します。
- RepositoryやUnit of Workの失敗は、`RepositoryError` のまま返します。
- Create/Updateの結果は識別子を返し、必要な詳細情報はQueryで取得します。

この契約により、ドメイン固有の処理はUse Case層に閉じ、プレゼンテーション層は
結果の表示だけを担当できます。

##### 2.2 Mediator Pattern（メディエーターパターン）

内部のディスパッチには `flow-med` を使用しますが、外部インターフェースが直接
利用するのは
[ApplicationMediator](../src/app/application/mediator.py) です。
`ApplicationMediator.send_async` はインスタンスメソッドで、Handlerの結果を返す前に
`classify_error` を一度だけ適用します。

Handlerの登録は
[`_HANDLER_TYPES`](../src/app/application/mediator.py) に明示し、
`create_application_mediator` が `HandlerRegistry` へ登録してからMediatorを構築します。
新しいHandlerを追加した場合は、この一覧に追加してください。

```python
mediator: ApplicationMediator
result = await mediator.send_async(GetUserQuery(user_id="01H...Z"))
```

Presentation層はBot、APIのいずれも同じ `ApplicationMediator` をDIで受け取り、
そのインスタンスメソッドだけを呼び出します。

##### 2.3 DTOs（Data Transfer Objects）

Result DTOは共有DTOモジュールに集約せず、各ユースケースのモジュールで定義します。
たとえば `GetUserResult` と `CreateUserResult` は
[usersのユースケース](../src/app/usecases/users/) にあります。
DTOはドメイン集約をそのまま公開せず、プレゼンテーションに必要なプリミティブ値を
返します。

---

### 3. Infrastructure Layer（インフラストラクチャ層）

**責務**: 技術的な詳細の実装（DB、外部API等）

**特徴**:

- ドメイン層のインターフェースを実装
- ORM、データベース接続、外部サービスとの通信
- ドメイン集約とORMモデルの変換

#### 構成要素

##### 3.1 ORM Models

`src/app/infrastructure/orm_models/user_orm.py`:

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

`src/app/infrastructure/repositories/generic_repository.py`:

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

        # 登録済みマッパーで ORM → Domain を変換
        return Ok(ORMMappingRegistry.from_orm(orm_instance))
```

**ポイント**:

- 型安全な汎用実装（Generics使用）
- ORM ↔ Domain の変換を `ORMMappingRegistry` に委譲
- Result型でエラーハンドリング

##### 3.3 ORM Mapping Registry

ドメイン集約とORMモデル間の変換は、Infrastructureの明示的なマッパーによって行い、
`ORMMappingRegistry` は型ごとのマッパーを登録・検索します。

`src/app/infrastructure/orm_mapping.py`:

```python
register_orm_mapping(
    DomainClass, ORMClass, to_orm=domain_to_orm, from_orm=domain_from_orm
)
# from_orm(orm_instance) で登録済みの明示マッパーを使ってORMからドメインへ変換
# to_orm(domain_instance) でドメインからORMへ変換
```

User、Team、TeamMembership、ChatMessageは、それぞれのドメイン語彙と復元APIを
明示的に指定します。これにより、property名やprivate fieldの追加が暗黙にDB列へ
影響することを防ぎ、versionと監査日時も復元時に保持します。
登録には双方向の変換関数が必須です。未登録の型の変換はエラーとなり、
フィールド名や型注釈からの自動変換は行いません。

**利点**:

- **型安全**: 集約ごとの復元APIとValue Object変換を明示
- **保守性向上**: 永続化列の変更を対応するマッパーに閉じ込める
- **依存性逆転**: ドメイン層がインフラ層に依存しない
- **DRY原則**: 変換ロジックの重複を排除
- **一元管理**: 全てのマッピングを `orm_registry.py` で集中管理

##### 3.4 Unit of Work Pattern

`src/app/infrastructure/unit_of_work.py`:

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
- 例外時のロールバック（コンテキストマネージャー）。成功時のコミットは各ユースケースが明示する

チャット履歴の読み取りは `IChatHistoryQuery` をDIで取得し、SQLAlchemy実装が
session factoryから呼び出し単位のセッションを作成・終了します。Unit of Workの
repositoryキャッシュやトランザクション境界とは独立しています。

##### 3.5 Dependency Injection Container

`src/app/container.py`:

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

[`src/app/presentation/bot/__main__.py`](../src/app/presentation/bot/__main__.py):

```python
class MyBot(commands.Bot):
    async def setup_hook(self) -> None:
        await self._init_database()
        await self.load_cogs()

    async def _init_database(self) -> None:
        injector = Injector([container.configure])
        self.mediator = injector.get(ApplicationMediator)

    async def load_cogs(self) -> None:
        await self.add_cog(TeamsCog(self, self.mediator))
        await self.add_cog(UsersCog(self, self.mediator))
```

DIコンテナは `ApplicationMediator` を生成し、Handler一覧の登録とエラー分類を
アプリケーション起動時に構成します。各Cogには同じMediatorインスタンスを渡します。

##### 4.2 Discord Cogs

[`src/app/presentation/bot/cogs/users_cog.py`](../src/app/presentation/bot/cogs/users_cog.py):

```python
query = GetUserQuery(user_id=user_id)
message = await (
    self.mediator.send_async(query)
    .map(lambda value: f"User Information:\nID: {value.id}")
    .unwrap()
)
await ctx.send(content=message)
```

**ポイント**:

- `ApplicationMediator` 経由でユースケースを呼び出し
- `Result` 型で成功と失敗を扱う
- エラー表示には `UseCaseError.display_message` を使う
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
3. ApplicationMediator -> GetUserHandler
   ↓ UserId.from_primitive("01H...")
4. UoW -> GenericRepository.get_by_id(UserId(...))
   ↓ SELECT ... WHERE id = "01H..."
5. Database -> UserORM
   ↓ ORMMappingRegistry.from_orm()
6. User (Domain) -> GetUserResult
   ↓ Ok(GetUserResult)
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
3. ApplicationMediator -> CreateTeamHandler -> Team(id=TeamId.generate(), ...)
   ↓ UoW -> GenericRepository.add()
4. ORMMappingRegistry.to_orm() -> TeamORM
   ↓ INSERT ...
5. Database commits
   ↓ Ok(CreateTeamResult(id="01H..."))
6. TeamsCog: .and_then() is called
   ↓ GetTeamQuery(id="01H...")
7. (Queryフローと同様の処理)
   ↓ Ok(GetTeamResult)
8. TeamsCog: .map() formats message
   ↓
9. User: receives success message
```

Create操作は作成したエンティティのIDを返します。詳細情報が必要な場合は、
Presentation層が同じ `ApplicationMediator` を通じてGet操作を続けて呼び出します。
CreateとGetの結果をつなぐ実例は
[`TeamsCog.teams_create`](../src/app/presentation/bot/cogs/teams_cog.py) にあります。

---

## テスト戦略

### 1. ユニットテスト

`tests/domain/aggregates/test_user.py`:

```python
import pytest

@pytest.mark.anyio
async def test_create_user_with_empty_name_raises_error() -> None:
    with pytest.raises(ValueError, match="User name cannot be empty"):
        User(id=UserId.generate().unwrap(), name="", email=Email.from_primitive("a@a.com").unwrap())
```

### 2. 統合テスト

`tests/usecases/users/test_get_user.py`:

```python
import pytest
from app.domain.value_objects import UserId, Email

@pytest.mark.anyio
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
    assert is_ok(result)
    assert result.value.user.name == "Bob"
```

**特徴**:

- 非同期テストには `@pytest.mark.anyio` を使用
- データベースを含む
- トランザクション動作の検証

---

## 依存関係管理

依存パッケージは [pyproject.toml](../pyproject.toml) で管理します。
本番用は `project.dependencies`、開発用は `dependency-groups.dev` を参照してください。
非同期テストには、開発依存のAnyIOに同梱されたpytestプラグインを使います。

---

## 拡張方法

### 新しい集約の追加

1. **ドメイン集約とValue Objectを作成**

```python
# src/app/domain/aggregates/guild.py
@dataclass
class Guild:
    id: GuildId
    name: str
```

1. **ORMモデルを作成**

```python
# src/app/infrastructure/orm_models/guild_orm.py
class GuildORM(SQLModel, table=True):
    __tablename__ = "guilds"
    id: str | None = Field(default=None, primary_key=True)
    name: str
```

1. **明示的マッパーを作成して登録**

`src/app/infrastructure/mappings/guild.py` に `guild_to_orm` と
`guild_from_orm` を実装します。既存の集約別マッパーと同様に、
保存する列とドメインの復元処理を明示します。

```python
# src/app/infrastructure/orm_registry.py
from app.domain.aggregates.guild import Guild
from app.infrastructure.mappings.guild import guild_from_orm, guild_to_orm
from app.infrastructure.orm_mapping import register_orm_mapping
from app.infrastructure.orm_models.guild_orm import GuildORM

def init_orm_mappings() -> None:
    """Initialize all ORM mappings."""
    # 既存の登録に追加
    register_orm_mapping(
        Guild, GuildORM, to_orm=guild_to_orm, from_orm=guild_from_orm
    )
```

`init_orm_mappings` はアプリ起動時に `src/app/container.py` から自動で呼び出されるため、ここの追加だけでマッピングは完了します。

1. **ユースケースを作成**

```python
# src/app/usecases/guilds/get_guild.py
# ... GetGuildQuery, GetGuildHandler などを実装
```

1. **Cogを作成**

```python
# src/app/presentation/bot/cogs/guilds_cog.py
# ... ApplicationMediator経由でユースケースを呼び出すコマンドを実装
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
