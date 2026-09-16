# Domain層ドキュメント

このプロジェクトの戦術的DDDを、現行コードとテストから学ぶための入口です。

- [実装ガイド](./DOMAIN_IMPLEMENTATION_GUIDE.md): カプセル化、不変性、同一性、永続化の責務。
- [境界と用語集](./BOUNDARIES_AND_GLOSSARY.md): 各集約の不変条件と業務上の前提。
- [ChatMessageのADR](../adr/0001-chat-message-aggregate-and-conversation-scope.md): メッセージ一件を集約とする理由。
- [アーキテクチャ](../ARCHITECTURE.md): アプリケーション全体の依存関係と構成。

## 読み始める順序

1. [TeamMembership](../../src/app/domain/aggregates/team_membership.py)で、生成時の状態と承認・退会の制約を確認する。
2. [Email](../../src/app/domain/value_objects/email.py)と[ConversationScope](../../src/app/domain/value_objects/conversation_scope.py)で、値の検証と不変性を確認する。
3. [承認ユースケース](../../src/app/usecases/memberships/approve_join_request.py)で、読み込み・ドメイン操作・保存・コミットの流れを追う。
4. [回帰テスト](../../tests/infrastructure/test_repositories.py)で、古いVersionからの削除が拒否されることを確認する。

## 新しい集約を追加するとき

- その集約が無いと守れない不変条件と、必要な整合性の範囲を決める。
- 既存集約を参考に、生成メソッド・ドメイン操作・同一性比較を定義する。単に `@dataclass` を付けただけでは、全フィールドによる状態比較になる。
- 永続化が必要ならORMモデルと明示的マッパーを作り、[登録処理](../../src/app/infrastructure/orm_registry.py)へ追加する。
- 不正な状態遷移、同一性、復元後の各属性、必要な同時実行制約をテストする。

監査日時やVersionは、それを必要とする集約だけに持たせます。
追記専用の `ChatMessage` はVersionと更新日時を持ちません。
