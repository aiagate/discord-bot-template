# Domain層実装ガイド

最終更新日: 2026-09-16

このガイドは現行実装の判断と読み方を説明します。集約の実装は
[User](../../src/app/domain/aggregates/user.py)、
[Team](../../src/app/domain/aggregates/team.py)、
[TeamMembership](../../src/app/domain/aggregates/team_membership.py)、
[ChatMessage](../../src/app/domain/aggregates/chat_message.py)を参照してください。

## 責務と依存関係

- Domainは値の検証と集約の状態遷移を担い、DBや外部APIを呼び出さない。
- UseCasesは入力をドメイン型へ変換し、参照先の存在確認・ドメイン操作・保存を調整する。
- Infrastructureは明示的なORM変換、トランザクション、DB制約による整合性保証を担う。

`IRepository` はDomainの契約です。トランザクション境界の `IUnitOfWork` と
履歴取得の `IChatHistoryQuery` は `contracts/ports` に置き、Domainから依存しません。

## カプセル化・不変性・不変条件

カプセル化は、状態の変更をドメインメソッドに集めることです。`User` や
`TeamMembership` は状態が変わるEntityで、読み取り用propertyを公開しています。
内部の `_email` や `_status` への直接代入は、この契約を破るため行いません。

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

- `add()` は新規挿入を行い、一意制約の競合時は `ALREADY_EXISTS` を返す。
- `update()` はVersionを持つ集約のIDとVersionを条件に更新し、Versionを進める。
- `delete()` もVersionを持つ集約のIDとVersionを条件に削除する。古い版なら `VERSION_CONFLICT`、対象がなければ `NOT_FOUND` を返す。
- 追記専用の集約は更新・削除を拒否する。

監査日時を持つ集約は `IAuditable`、Versionを持つ集約は `IVersionable` の
Protocolを満たします。Repositoryは更新日時・Versionを反映した新しい集約を
返すため、保存後の状態が必要なら戻り値を使います。

`@runtime_checkable` による `isinstance()` は属性の存在を確認するもので、
属性の型や業務上の妥当性までは検証しません。[PythonのProtocol仕様](https://docs.python.org/3/library/typing.html#typing.runtime_checkable)
を参照してください。

## 確認するテスト

- [集約のテスト](../../tests/domain/aggregates): 状態遷移、同一性、不変性。
- [Value Objectのテスト](../../tests/domain/value_objects): 値の検証と等価性。
- [Membershipの制約テスト](../../tests/infrastructure/test_team_membership_constraints.py): 同時加入時の一意性と更新競合。
- [Repositoryのテスト](../../tests/infrastructure/test_repositories.py): 古い版からの削除拒否と最新状態の保持。

```bash
uv run --frozen pytest tests/domain tests/infrastructure
```
