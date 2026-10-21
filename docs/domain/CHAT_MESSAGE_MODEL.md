# ChatMessageの集約境界と会話スコープ

## モデルの役割

本プロジェクトは、DiscordやLINEなどの外部メッセージングプラットフォームから
受信したメッセージを保存し、会話単位で履歴を取得する。

ドメインモデルには、メッセージの整合性境界、外部送信者の識別、会話の識別、
プラットフォーム固有情報の表現方法を明確に定める必要がある。

## モデルの仕様

### 集約境界

`ChatMessage` 1件を独立した集約ルートとする。

`ChatMessage` は生成時に必要な情報がすべて確定する、不変かつ追記専用の集約である。
アプリケーションのRepository操作として、該当するメッセージの更新および削除を
許可しない。

会話全体を集約として扱わない。会話履歴は、指定された `ConversationScope` に
属する `ChatMessage` の集合を読み取り専用のクエリ結果として構成する。
履歴取得のために会話集約または別DTOを必須としない。

この境界により、履歴件数に比例して集約が肥大化することや、同じ会話に対する
メッセージ追加が単一集約の同時更新として競合することを避ける。

### ChatMessageの構成

`ChatMessage` は次の情報を保持する。

- `MessageId`: メッセージを一意に識別するULID
- `ChatPlatform`: メッセージの送信元プラットフォーム
- `ConversationScope`: メッセージが属する会話の識別子
- `ExternalActorId`: 外部プラットフォーム上の送信者識別子
- `AuthorKind`: 送信者の種別（user、bot、system）
- `MessageContent`: メッセージ内容
- `occurred_at`: 外部プラットフォーム上でメッセージが発生したUTC日時

`ChatMessage` はプラットフォームと `ConversationScope` のプラットフォームが
一致することを保証する。`occurred_at` はドメインへの入力時にタイムゾーン付き
日時のみを受け付け、UTCへ正規化する。永続化アダプターも、復元時には
タイムゾーン付きUTC日時をドメインへ渡す。

`MessageContent` は内部payloadを防御的にコピーし、生成後に外部から内容を
変更できないようにする。

### プラットフォーム差の表現

DiscordおよびLINEの差は、`ChatMessage` の継承ではなく
`ConversationScope` の直和型で表現する。

```python
type ConversationScope = (
    DiscordConversationScope | LineConversationScope
)
```

`DiscordConversationScope` は次の組み合わせで一つの会話を識別する。

- `guild_id`
- `channel_id`

`LineConversationScope` は次のいずれか一つだけを保持する。

- ユーザー会話の `line_user_id`
- グループ会話の `line_group_id`
- ルーム会話の `line_room_id`

LINEの会話スコープは、複数の識別子を同時に持つ状態と、識別子を一つも持たない
状態を許可しない。

新しいプラットフォームを追加する場合は、そのプラットフォームの会話識別規則を
表す `ConversationScope` 型を追加する。同時に、`ChatPlatform`、スコープの
シリアライズと復元、完全なスコープによる履歴検索、必要な永続化設定を一貫して
追加する。プラットフォーム固有の配送情報だけを理由に `ChatMessage` の
サブクラスを追加しない。

### 外部IDと内部ID

`ExternalActorId` はDiscordやLINEが発行する外部識別子であり、アプリケーションの
`UserId` とは別の概念として扱う。

外部アカウントと内部ユーザーを関連付ける場合は、別の関連モデルまたは解決ポートを
使用する。`ExternalActorId` を暗黙に `UserId` として使用しない。

### 永続化

`ChatMessage` は `chat_messages` テーブルへ保存する。永続化モデルはドメインの語彙に
合わせ、次の情報を格納する。

- `id`
- `platform`
- `conversation_scope`
- `external_sender_id`
- `author_kind`
- `content`
- `occurred_at`

ドメインとORMの変換はInfrastructure層の明示的なマッピングが担当する。
Application層およびDomain層は、ORMモデル、SQLAlchemyセッション、DBカラム構造へ
依存しない。

`conversation_scope` のJSON形式は永続化契約の一部とする。

```json
{"platform": "DISCORD", "guild_id": "...", "channel_id": "..."}
```

```json
{"platform": "LINE", "kind": "group", "locator": "..."}
```

LINEの `kind` は `"user"`、`"group"`、`"room"` のいずれか一つとする。
各形式のキーは固定し、余分なキーや不足したキーを許可しない。テーブルの
`platform` と `conversation_scope.platform` は同じ値を表す。前者は検索用の列、
後者は自己完結したスコープ表現の一部であり、両者は必ず一致する。

保存には既存の汎用Repositoryを使用する。`IAppendOnly` は、更新および削除を
許可しない集約の能力契約である。共通RepositoryのAPIに更新・削除操作が存在する
場合でも、`IAppendOnly` を示す集約に対してはRepository実装がエラーを返す。
Repositoryの能力を静的な型で分離することは要求しない。

### 履歴取得

履歴取得は `ConversationScope` 全体を検索条件とする。

プラットフォームだけ、または外部送信者だけを条件にして会話履歴を構成しない。
Discordではguildとchannelの組み合わせ、LINEでは会話種別とlocatorの組み合わせを
完全に一致させる。

履歴Queryは `occurred_at` の降順、同一日時では `MessageId` の降順で、指定された
会話の最新N件を選択する。呼び出し元には両キーの昇順で返す。

## 設計上の特性と制約

- メッセージ追加は他のメッセージと独立して処理できる。
- 会話履歴の増加によって集約のロードサイズが増大しない。
- プラットフォーム固有の会話識別規則を型と不変条件で保証できる。
- 外部アカウントIDと内部ユーザーIDの意味が分離される。
- Domain/Application層は永続化方式から独立する。
- 会話全体にまたがる強整合性が必要になった場合は、別の集約またはプロセス管理が
  必要になる。
- JSONで保存する `conversation_scope` の検索性能は、データ量と利用DBに応じて
  専用カラム、生成列、式インデックスなどで最適化する必要がある。

## 拡張時に検討する条件

次の要件が加わる場合は、集約境界や永続化方式を検討する。

- 会話そのものに状態遷移や強整合性を必要とする業務ルールが追加された場合
- メッセージ編集、論理削除、訂正履歴が正式な要件になった場合
- 外部アカウントと内部ユーザーの関連が認証・認可の境界になった場合
- `conversation_scope` のJSON検索が性能要件を満たさなくなった場合
- プラットフォーム間で共通化できないメッセージ生成規則や状態遷移が追加された場合
