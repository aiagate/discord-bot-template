# Domain層実装ガイド

最終更新日: 2025-11-26

このドキュメントは、Domain層（ドメイン層）の実装方法と、プロジェクトで使用するパターンを説明します。

---

## 目次

1. [Domain層の役割](#domain層の役割)
2. [ディレクトリ構成](#ディレクトリ構成)
3. [Aggregate（集約）の実装](#aggregate集約の実装)
4. [インターフェースの定義](#インターフェースの定義)
5. [バリデーション](#バリデーション)
6. [タイムスタンプ管理（IAuditable）](#タイムスタンプ管理iauditable)
7. [ベストプラクティス](#ベストプラクティス)
8. [アンチパターン](#アンチパターン)

---

## Domain層の役割

Domain層は**ビジネスロジックの中核**であり、以下の責務を持ちます：

- [OK] **ビジネスルールの定義**: ドメインの不変条件（Invariants）を保証
- [OK] **エンティティと集約の管理**: ドメインオブジェクトのライフサイクル管理
- [OK] **フレームワーク非依存**: 純粋なPythonオブジェクトとして実装
- [NG] **データベースアクセスは行わない**: インフラストラクチャ層の責務
- [NG] **外部APIを呼び出さない**: インフラストラクチャ層の責務
- [NG] **UIロジックを持たない**: プレゼンテーション層の責務

---

## ディレクトリ構成

```
src/app/domain/
├── aggregates/          # 集約ルート（Aggregate Roots）
│   ├── __init__.py
│   └── user.py         # User集約
├── interfaces/          # ドメインインターフェース
│   ├── __init__.py
│   └── auditable.py    # IAuditableプロトコル
└── value_objects/       # 値オブジェクト（将来追加）
    └── __init__.py
```

### ファイル命名規則

- **集約**: `snake_case.py`（例: `user.py`, `order.py`）
- **クラス名**: `PascalCase`（例: `User`, `Order`）
- **インターフェース**: `I` プレフィックス（例: `IAuditable`）

---

## Aggregate（集約）の実装

### 基本構造

集約は `@dataclass` デコレータを使用して実装します。

```python
from dataclasses import dataclass


@dataclass
class User:
    """User aggregate root.

    Represents a user in the system with name and email.
    """

    id: int
    name: str
    email: str

    def __post_init__(self) -> None:
        """Validate user data."""
        if not self.name:
            raise ValueError("User name cannot be empty.")
        if not self.email:
            raise ValueError("User email cannot be empty.")
```

### 主要な設計原則

#### 1. **イミュータビリティ（不変性）の原則**

ドメインオブジェクトの状態は、ドメインメソッドを通じてのみ変更します。

✅ **良い例**:

```python
@dataclass
class User:
    id: int
    name: str
    email: str

    def change_email(self, new_email: str) -> "User":
        """ビジネスルールに従ってメールアドレスを変更"""
        if not new_email:
            raise ValueError("Email cannot be empty.")
        if "@" not in new_email:
            raise ValueError("Invalid email format.")

        self.email = new_email
        return self
```

❌ **悪い例**:

```python
# ドメインメソッドを経由せず、直接変更
user.email = "new@example.com"  # バリデーションがスキップされる！
```

#### 2. **不変条件（Invariants）の保証**

集約は常に有効な状態を保ちます。

```python
@dataclass
class Order:
    id: int
    items: list[OrderItem]
    status: OrderStatus

    def __post_init__(self) -> None:
        """不変条件の検証"""
        if not self.items:
            raise ValueError("Order must have at least one item.")
        if self.status == OrderStatus.SHIPPED and not self.shipping_address:
            raise ValueError("Shipped order must have shipping address.")

    def add_item(self, item: OrderItem) -> "Order":
        """アイテムを追加（ビジネスルールを適用）"""
        if self.status != OrderStatus.DRAFT:
            raise ValueError("Cannot add items to non-draft order.")

        self.items.append(item)
        return self
```

#### 3. **集約境界の尊重**

集約外のオブジェクトへの参照は、IDのみを保持します。

✅ **良い例**:

```python
@dataclass
class Order:
    id: int
    user_id: int  # UserのIDのみを保持
    items: list[OrderItem]
```

❌ **悪い例**:

```python
@dataclass
class Order:
    id: int
    user: User  # 集約境界を越えた参照
    items: list[OrderItem]
```

---

## インターフェースの定義

Domain層のインターフェースは `Protocol` を使用して定義します。

### Protocolの使用例

```python
from typing import Protocol, runtime_checkable
from datetime import datetime


@runtime_checkable
class IAuditable(Protocol):
    """監査可能なエンティティのプロトコル"""
    created_at: datetime
    updated_at: datetime
```

### なぜProtocolを使うのか？

- **構造的部分型（Structural Subtyping）**: 明示的な継承不要
- **柔軟性**: 既存のクラスを変更せずにプロトコルを満たせる
- **型安全性**: `isinstance()` チェックで実行時検証が可能（`@runtime_checkable`）

### Protocolの実装

Pythonの`Protocol`は構造的部分型なので、明示的に継承する必要はありません：

```python
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class User:
    """User aggregate root.

    Implements IAuditable: timestamps are automatically managed
    by the repository layer.
    """
    id: int
    name: str
    email: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    # ↑ IAuditableプロトコルを満たす（明示的な継承不要）
```

---

## バリデーション

### `__post_init__`でのバリデーション

`@dataclass`の`__post_init__`メソッドで不変条件を検証します。

```python
@dataclass
class User:
    id: int
    name: str
    email: str

    def __post_init__(self) -> None:
        """Validate user data."""
        if not self.name:
            raise ValueError("User name cannot be empty.")
        if not self.email:
            raise ValueError("User email cannot be empty.")
        if "@" not in self.email:
            raise ValueError("Invalid email format.")
```

### 複雑なバリデーション

複雑なバリデーションは、専用のメソッドに分離します。

```python
import re


@dataclass
class User:
    EMAIL_REGEX: ClassVar[re.Pattern[str]] = re.compile(
        r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    )

    id: int
    name: str
    email: str

    def __post_init__(self) -> None:
        """Validate user data."""
        self._validate_name()
        self._validate_email()

    def _validate_name(self) -> None:
        """Validate user name."""
        if not self.name:
            raise ValueError("User name cannot be empty.")
        if len(self.name) > 255:
            raise ValueError("User name is too long (max 255 characters).")

    def _validate_email(self) -> None:
        """Validate email format."""
        if not self.email:
            raise ValueError("User email cannot be empty.")
        if not self.EMAIL_REGEX.match(self.email):
            raise ValueError(f"Invalid email format: {self.email}")
```

---

## タイムスタンプ管理（IAuditable）

### IAuditableプロトコル

タイムスタンプ（`created_at`, `updated_at`）を自動管理したいエンティティは、`IAuditable`プロトコルを満たします。

#### 定義

```python
# src/app/domain/interfaces/auditable.py
from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class IAuditable(Protocol):
    """Protocol for entities that support audit timestamps.

    Any domain aggregate implementing this protocol will have
    created_at and updated_at automatically managed by the repository layer.
    """
    created_at: datetime
    updated_at: datetime
```

#### 実装

```python
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class User:
    """User aggregate root.

    Implements IAuditable: timestamps are infrastructure concerns but exposed
    as read-only fields for auditing and display purposes. The repository layer
    automatically manages created_at and updated_at.
    """
    id: int
    name: str
    email: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate user data."""
        if not self.name:
            raise ValueError("User name cannot be empty.")
```

### タイムスタンプの自動更新

リポジトリ層が自動的に`updated_at`を更新します：

```python
# src/app/infrastructure/repositories/generic_repository.py
async def save(self, entity: T) -> Result[T, RepositoryError]:
    """Save entity.

    For IAuditable entities, automatically updates the updated_at timestamp.
    """
    orm_instance = domain_to_orm(entity)

    # IAuditableエンティティの場合、更新時にupdated_atを自動設定
    is_update = orm_instance.id is not None
    if is_update and isinstance(entity, IAuditable):
        orm_instance.updated_at = datetime.now(UTC)

    # ... 保存処理
```

### タイムスタンプ不要なエンティティ

タイムスタンプが不要なエンティティは、`IAuditable`を実装しません：

```python
@dataclass
class TemporarySession:
    """一時セッション（タイムスタンプ不要）"""
    id: int
    token: str
    # created_at/updated_atなし
```

---

## ベストプラクティス

### 1. ドメインメソッドの命名

ドメインメソッドは**ユビキタス言語（Ubiquitous Language）**を使用します。

✅ **良い例**:

```python
def change_email(self, new_email: str) -> "User": ...
def activate_account(self) -> "User": ...
def suspend_for_violation(self, reason: str) -> "User": ...
```

❌ **悪い例**:

```python
def update_email(self, email: str) -> "User": ...  # 技術用語
def set_active(self) -> "User": ...  # ビジネス意図が不明確
```

### 2. フィールドのデフォルト値

フィールドにデフォルト値を設定する場合は `field(default_factory=...)` を使用します。

✅ **良い例**:

```python
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class User:
    id: int
    name: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
```

❌ **悪い例**:

```python
@dataclass
class User:
    id: int
    name: str
    created_at: datetime = datetime.now(UTC)  # クラス定義時に評価される！
```

### 3. 型ヒントの使用

すべてのフィールドとメソッドに型ヒントを付けます。

```python
from dataclasses import dataclass


@dataclass
class User:
    id: int
    name: str
    email: str

    def change_email(self, new_email: str) -> "User":
        """Change user email."""
        self.email = new_email
        return self
```

### 4. Docstringの記述

公開APIには必ずDocstringを記述します。

```python
@dataclass
class User:
    """User aggregate root.

    Represents a user in the system with authentication credentials
    and profile information.

    Attributes:
        id: Unique identifier
        name: User's display name
        email: User's email address (unique)
    """
    id: int
    name: str
    email: str

    def change_email(self, new_email: str) -> "User":
        """Change user's email address.

        Args:
            new_email: New email address

        Returns:
            Updated user instance

        Raises:
            ValueError: If email format is invalid
        """
        if not new_email or "@" not in new_email:
            raise ValueError("Invalid email format.")
        self.email = new_email
        return self
```

### 5. フレームワーク非依存

Domain層はフレームワークに依存しないようにします。

✅ **良い例**:

```python
from dataclasses import dataclass
from datetime import datetime  # 標準ライブラリのみ


@dataclass
class User:
    id: int
    name: str
    created_at: datetime
```

❌ **悪い例**:

```python
from sqlmodel import SQLModel, Field  # インフラ層の依存


class User(SQLModel):  # ドメインにインフラが混入！
    id: int
    name: str
```

---

## アンチパターン

### [NG] アンチパターン1: 貧血ドメインモデル（Anemic Domain Model）

ビジネスロジックがない、データだけのクラス。

**悪い例**:

```python
@dataclass
class User:
    """単なるデータ構造"""
    id: int
    name: str
    email: str
    # ビジネスロジックなし
```

**良い例**:

```python
@dataclass
class User:
    """ビジネスロジックを持つ集約"""
    id: int
    name: str
    email: str

    def change_email(self, new_email: str) -> "User":
        """メール変更のビジネスルールを適用"""
        if not self._is_valid_email(new_email):
            raise ValueError("Invalid email format.")
        self.email = new_email
        return self
```

### [NG] アンチパターン2: インフラストラクチャへの依存

Domain層がデータベースやフレームワークに依存している。

**悪い例**:

```python
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import Session


class User:
    """ドメインとインフラが混在！"""
    def save(self, session: Session) -> None:
        session.add(self)
        session.commit()
```

**良い例**:

```python
# Domain層: 純粋なビジネスロジック
@dataclass
class User:
    id: int
    name: str

# Infrastructure層: 永続化の責務
class UserRepository:
    async def save(self, user: User) -> Result[User, RepositoryError]:
        # データベース保存処理
        ...
```

### [NG] アンチパターン3: 神クラス（God Class）

1つのクラスに責務が集中しすぎている。

**悪い例**:

```python
@dataclass
class User:
    """責務が多すぎる"""
    # ユーザー情報
    id: int
    name: str

    # 認証関連
    password_hash: str

    # 注文関連
    orders: list[Order]

    # 決済関連
    payment_methods: list[PaymentMethod]

    # ... さらに増え続ける
```

**良い例**:

```python
# 集約を分離
@dataclass
class User:
    """ユーザーの基本情報"""
    id: int
    name: str

@dataclass
class UserCredential:
    """認証情報"""
    user_id: int
    password_hash: str

@dataclass
class Order:
    """注文情報（別の集約）"""
    id: int
    user_id: int  # Userへの参照はIDのみ
```

---

## まとめ

### Domain層実装のチェックリスト

- [OK] `@dataclass` を使用してシンプルに実装
- [OK] `__post_init__` でバリデーションを実装
- [OK] ビジネスロジックはドメインメソッドに実装
- [OK] フレームワーク非依存を保つ
- [OK] 型ヒントとDocstringを記述
- [OK] タイムスタンプが必要な場合は`IAuditable`を実装
- [OK] 不変条件を常に保証
- [OK] 集約境界を尊重
- [NG] データベースアクセスを行わない
- [NG] 外部APIを呼び出さない
- [NG] インフラストラクチャに依存しない

---

## 参考資料

- [プロジェクトのアーキテクチャドキュメント](../ARCHITECTURE.md)
- [クリーンアーキテクチャ（Robert C. Martin）](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html)
- [ドメイン駆動設計（Eric Evans）](https://www.domainlanguage.com/ddd/)
- [Python Protocol（PEP 544）](https://peps.python.org/pep-0544/)
