# Domain層ドキュメント

このディレクトリには、Domain層（ドメイン層）の設計と実装に関するドキュメントが含まれています。

## ドキュメント一覧

### [Domain実装ガイド](./DOMAIN_IMPLEMENTATION_GUIDE.md)

Domain層の実装方法を詳細に説明した総合ガイドです。

**含まれる内容:**

- Domain層の役割と責務
- Aggregate（集約）の実装パターン
- インターフェース（Protocol）の定義方法
- バリデーションのベストプラクティス
- タイムスタンプ管理（IAuditable）
- アンチパターンと回避方法

**対象読者:**

- 新しいドメインエンティティを追加する開発者
- Domain層のコードレビューを行う開発者
- プロジェクトのアーキテクチャを理解したい開発者

---

## クイックスタート

### 新しい集約を作成する

1. `src/app/domain/aggregates/` に新しいファイルを作成
2. `@dataclass` を使用してクラスを定義
3. `__post_init__` でバリデーションを実装
4. 必要に応じてビジネスロジックのメソッドを追加

```python
# src/app/domain/aggregates/product.py
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal


@dataclass
class Product:
    """Product aggregate root.

    Implements IAuditable for automatic timestamp management.
    """
    id: int
    name: str
    price: Decimal
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate product data."""
        if not self.name:
            raise ValueError("Product name cannot be empty.")
        if self.price < 0:
            raise ValueError("Product price must be non-negative.")

    def update_price(self, new_price: Decimal) -> "Product":
        """Update product price with validation."""
        if new_price < 0:
            raise ValueError("Price must be non-negative.")
        self.price = new_price
        return self
```

### タイムスタンプを自動管理する

タイムスタンプ（`created_at`, `updated_at`）を自動管理したい場合は、`IAuditable`プロトコルを満たすようにフィールドを定義します：

```python
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class MyEntity:
    """Implements IAuditable for automatic timestamp management."""
    id: int
    name: str
    # この2つのフィールドを追加するだけでIAuditableを満たす
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
```

リポジトリ層が自動的に`updated_at`を更新します。

---

## 関連ドキュメント

- [アーキテクチャ概要](../ARCHITECTURE.md) - プロジェクト全体のアーキテクチャ
- [課題・改善点リスト](../ISSUES_AND_IMPROVEMENTS.md) - 技術的な課題と改善提案

---

## ヒント

### 良いドメインモデルの特徴

- **ビジネスルールが明確**: コードを読めばビジネスルールがわかる
- **不変条件を保証**: 常に有効な状態を保つ
- **フレームワーク非依存**: 純粋なPythonオブジェクト
- **テストしやすい**: 外部依存なしでテスト可能

### よくある質問

**Q: ドメインメソッドとユースケースの違いは？**

A:

- **ドメインメソッド**: 単一の集約内のビジネスルール（例: `change_email`）
- **ユースケース**: 複数の集約やリポジトリを協調させるビジネスフロー（例: `CreateUserHandler`）

**Q: バリデーションはドメイン層とユースケース層のどちらで行うべき？**

A:

- **ドメイン層**: ドメインの不変条件（例: メールアドレス形式）
- **ユースケース層**: アプリケーション固有のバリデーション（例: 重複チェック）

**Q: タイムスタンプはドメインの責務？**

A: タイムスタンプは監査（Audit）のためのインフラの関心事ですが、ドメインオブジェクトに含めることで、監査情報を参照できるようにしています。`IAuditable`プロトコルにより、この関心事を明示的に分離しています。

---

## 貢献

Domain層の実装パターンを改善する提案がある場合は、以下の手順で貢献してください：

1. 新しいパターンを実装
2. テストを追加
3. このドキュメントを更新
4. プルリクエストを作成

---

最終更新日: 2025-11-26
