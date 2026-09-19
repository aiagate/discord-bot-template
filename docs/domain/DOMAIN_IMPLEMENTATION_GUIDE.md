# Domain層実装ガイド

最終更新日: 2026-09-19

このガイドは現行ドメイン実装の判断と読み方を説明します。新機能や集約の追加手順全体（登録・ORM・UoW・UseCase・マイグレーション・テスト）については、正本ガイドである **[機能追加ガイド](../development/ADDING_FEATURE.md)** を参照してください。

集約の実装例は
[User](../../src/app/domain/aggregates/user.py)、
[Team](../../src/app/domain/aggregates/team.py)、
[TeamMembership](../../src/app/domain/aggregates/team_membership.py)、
[ChatMessage](../../src/app/domain/aggregates/chat_message.py)を参照してください。

## 責務と依存関係

- Domainは値の検証と集約の状態遷移を担い、ORMや外部I/Oに依存しません。
- UseCasesは入力をドメイン型へ変換し、参照先の存在確認・ドメイン操作・保存を調整します。
- Infrastructureは明示的なORM変換、トランザクション、DB制約による整合性保証を担います。

`IRepository` はDomainの契約です。トランザクション境界の `IUnitOfWork` と
履歴取得の `IChatHistoryQuery` は `contracts/ports` に置き、Domainから依存しません。

## カプセル化・不変性・不変条件

カプセル化は、状態の変更をドメインメソッドに集めることです。`User` や
`TeamMembership` は状態が変わるEntityで、読み取り用propertyを公開しています。
Pythonの命名慣習（`_field`）により内部フィールドへの直接代入ではなく、業務メソッドを操作経路として明示します。

不変性は、生成した値を変更しないことです。`Email` などのValue Objectを
変更するときは、新しい値へ置き換えます。次の例では元のEmailの値は変わりません。

```python
from app.domain.aggregates.user import User
from app.domain.value_objects import DisplayName, Email

user = User.register(DisplayName("Alice"), Email("alice@example.com"))
old_email = user.email
user.change_email(Email("new@example.com"))
assert old_email == Email("alice@example.com")
assert user.email == Email("new@example.com")
```

不変条件は、状態が変わっても守られるべき業務ルールです。例えば
`TeamMembership.approve()` は `PENDING` からの承認だけを許可します。

```python
from app.domain.aggregates.team_membership import TeamMembership
from app.domain.value_objects import MembershipStatus, TeamId, UserId

membership = TeamMembership.request_join(
    TeamId.generate().expect("valid id"),
    UserId.generate().expect("valid id"),
)
membership.approve()
assert membership.status is MembershipStatus.ACTIVE
membership.leave()
assert membership.status is MembershipStatus.LEAVED
```

承認済み・終了済み期間への再承認や、終了後のロール変更は拒否します。
許可・拒否の組み合わせは[状態遷移テスト](../../tests/domain/aggregates/test_team_membership.py)
で確認できます。再加入では古い期間を戻さず、新しいIDの期間を作ります。

`ChatMessage` はEntityですが、追記専用というルールにより集約全体を不変に
しています。`MessageContent` は入力と返却値のpayloadを防御的にコピーします。

## Entityの同一性とValue Objectの等価性

4集約の `==` は、同じ具象型かつ同じIDなら真になります。属性・Version・監査日時は
比較に含めません。Value Objectは値で比較します。以下は同じEntityの二つの
表現をコピーで用意し、同一性と状態の違いを確認する例です。

```python
from copy import deepcopy

from app.domain.aggregates.team import Team
from app.domain.value_objects import TeamName

before = Team.form(TeamName("Alpha"))
after = deepcopy(before)
after.change_name(TeamName("Beta"))
assert before == after
assert before.name != after.name
assert before != Team.form(TeamName("Alpha"))
```

`@dataclass` の既定の `==` は全フィールドの比較です。このプロジェクトでは
集約ごとに `__eq__` を定義しています。可変の集約はハッシュ化できません。
不変な `ChatMessage` は型とIDでハッシュ化し、`==` と整合させています。
[Pythonのdataclass仕様](https://docs.python.org/3/library/dataclasses.html)も参照してください。

復元後の状態を検証するときは、Entity同士の `==` に加えて各属性を比較します。
[マッピングテスト](../../tests/infrastructure/test_domain_mappings.py)が実例です。

## 集約境界と業務ルールの保証

`TeamMembership` は一回の加入期間を表し、TeamとUserをIDで参照します。
「同じteam/userの現在の加入期間は一つ」というルールは、複数の期間にまたがります。
事前検索だけでは同時加入を防げないため、[部分一意インデックス](../../src/app/infrastructure/orm_models/team_membership_orm.py)
で保証し、Repositoryが競合を返します。

重複禁止が業務上の要件なら、それ自体は業務ルールです。部分一意インデックスは、
そのルールを同時実行時にも守るための実装手段です。

`ChatMessage` は一件を整合性境界とし、会話履歴は `ConversationScope` 全体を
条件にQueryで取得します。履歴を集約に含めない理由は[ADR 0001](../adr/0001-chat-message-aggregate-and-conversation-scope.md)
を参照してください。現在の業務ルールと未確定事項は[境界と用語集](./BOUNDARIES_AND_GLOSSARY.md)
に記録しています。

## 生成・復元・永続化

新規生成には `register()`、`form()`、`join()`、`request_join()` などを使います。
値の検証はValue Object、状態遷移の検証は集約が担います。ドメイン操作の命名は、
`approve()` や `leave()` のように業務上の行為を表します。

復元はInfrastructureの明示的マッパーから `restore()` を呼び、保存されたID・
Version・監査日時を引き継ぎます。新規登録とは別の操作として扱います。
[Userのマッピング](../../src/app/infrastructure/mappings/user.py)を参照してください。

保存は `async with uow` の中でRepositoryを取得し、操作結果を確認したうえで
`commit()` を呼びます。Repository自身はコミットしません。
[承認ユースケース](../../src/app/usecases/memberships/approve_join_request.py)が実例です。

- `add()` は新規挿入を行い、一意制約の競合時は `ALREADY_EXISTS` を返します。
- `update()` はORM `merge(load=True)` と `flush()` を使用し、集約全体のスナップショットを保存します。空コレクションは全削除として扱われ、子要素のみの変更や同値更新であっても集約のVersionを+1します。事前のVersion不一致時は `VERSION_CONFLICT` を返します（通常の事前不一致は先行する書き込みを壊しません）。
- `delete()` もVersionを持つ集約のIDとVersionを条件に削除します。古い版なら `VERSION_CONFLICT`、対象がなければ `NOT_FOUND` を返します。
- 追記専用の集約（`IAppendOnly`）は更新・削除を拒否します。
- 複雑なクエリやロード制御が必要な場合は、UoWに登録された専用Repository（`uow.GetCustomRepository(Port)`）を使用します。専用Repositoryは現在のSessionを共有します。成功を確定するcommitはUoWが行い、flush失敗時にはRepositoryが同じSessionをrollbackしてErrを返します。そのrollbackでUoWは失敗を記録し以後のcommitを拒否します。
- 正常な `uow.rollback()` は未確定の書き込みを破棄して同一スコープのまま処理を継続可能ですが、既に失敗済みのスコープでは失敗状態を消去しません。flush失敗時（`StaleDataError`, `IntegrityError` 等）やRepository内部からの直接ロールバックではSessionの `after_soft_rollback` によりUoWに失敗状態が記録され、同一スコープ内のcommitは拒否されます（新しいUoWスコープで再試行します）。

監査日時を持つ集約は `IAuditable`、Versionを持つ集約は `IVersionable` の
Protocolを満たします。Repositoryは更新日時・Versionを反映した新しい集約を
返すため、保存後の状態が必要なら戻り値を使います。

`@runtime_checkable` による `isinstance()` は属性の存在を確認するもので、
属性の型や業務上の妥当性までは検証しません。[PythonのProtocol仕様](https://docs.python.org/3/library/typing.html#typing.runtime_checkable)
を参照してください。

## 確認するテスト

- [集約のテスト](../../tests/domain/aggregates): 状態遷移（[許可・拒否の遷移表](../../tests/domain/aggregates/test_team_membership.py)）、同一性、不変性。
- 集約の共通契約テスト（[`tests/domain/test_aggregate_contracts.py`](../../tests/domain/test_aggregate_contracts.py)、ケース定義: [`tests/domain/aggregate_cases.py`](../../tests/domain/aggregate_cases.py)）: 全集約の同一性・可変性契約を共通assertで検証（※業務不変条件の網羅性を自動保証するものではありません）。
- [Value Objectのテスト](../../tests/domain/value_objects): 値の検証と等価性。
- [マッピング・復元テスト](../../tests/infrastructure/test_domain_mappings.py): 属性、Version、日時の復元維持と不正データの拒否。
- [Membershipの制約テスト](../../tests/infrastructure/test_team_membership_constraints.py): 同時加入時の一意性と更新競合。
- [Repositoryのテスト](../../tests/infrastructure/test_repositories.py): 古い版からの削除拒否と最新状態の保持。
- [集約永続化・UoW統合テスト](../../tests/infrastructure/test_aggregate_persistence.py)（モデル定義: [`tests/helpers/aggregate_persistence.py`](../../tests/helpers/aggregate_persistence.py)）: 親子集約の完全スナップショット保存、実race検出と競合ロールバック、専用RepositoryとUoWのトランザクション共有・ライフサイクル検証。
- 登録完全性テスト（[`tests/infrastructure/test_registration_completeness.py`](../../tests/infrastructure/test_registration_completeness.py)）: モデル・マッピング・Handler登録漏れの検出。

```bash
# ドメインおよびインフラテストの実行例
TEST_DATABASE_URL=sqlite+aiosqlite:// uv run --frozen pytest tests/domain tests/infrastructure
```
