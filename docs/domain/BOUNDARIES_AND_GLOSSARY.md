# 現行のドメイン境界と用語集

最終更新日: 2026-09-12

この文書は、現在のコードから確認できるモデル境界と前提を記録する。将来の
サービス分割、コアドメインの順位付け、または未確定の業務ルールを先取りして
定義するものではない。

## 現在のモデル境界

### Identity

`User` はアプリケーション内のユーザーを表す集約ルートである。外部サービスが
発行した送信者識別子は `UserId` ではなく、メッセージ側の
`ExternalActorId` として扱う。

### Team membership

`Team` はチームを、`TeamMembership` は一人のユーザーが一つのチームに所属する
一つの enrollment period を表す集約ルートである。

- 新規加入は `ACTIVE`、または承認待ちの `PENDING` の期間を新しく作る。
- 同じ team/user の `PENDING` または `ACTIVE` は同時に一つだけ許可する。
- `leave()` は期間を `LEAVED` に終端化し、その行を履歴として残す。
- 再加入は以前の行を再利用せず、新しい期間と新しいIDを作る。
- 終了状態はドメイン語彙として `MembershipStatus.LEAVED` と表現する。
- `PENDING` から `ACTIVE` への承認条件は集約の `approve()` が保証する。

一意性はアプリケーションの事前確認だけに頼らず、SQLite/PostgreSQLの部分一意
インデックスでも保証する。既存データに現在期間の重複がある場合、前方マイグレー
ションは停止し、データを削除または自動選択しない。

### Messaging history

`ChatMessage` は一件の不変・追記専用メッセージを表す集約ルートである。会話全体を
集約としてロードせず、`ConversationScope` を条件に `IChatHistoryQuery` で読む。
この判断の詳細は [ADR 0001](../adr/0001-chat-message-aggregate-and-conversation-scope.md)
に記録している。

## 用語集

| 用語 | 意味 |
| --- | --- |
| User | アプリケーション内部のユーザー集約 |
| Team | ユーザーが所属できるチーム集約 |
| enrollment period | 一回の加入から退会までを表すMembershipの寿命 |
| Membership | UserとTeamの一つの加入期間。再加入では新しい行になる |
| PENDING | 加入申請中の期間 |
| ACTIVE | 承認済み、または即時加入済みの期間 |
| LEAVED | 終了済みの期間 |
| ConversationScope | Discord/LINE上の会話を一意に特定する値オブジェクト |
| ExternalActorId | 外部メッセージング基盤上の送信者ID |

## 境界と依存方向

- Domainは集約、値オブジェクト、汎用Repository契約だけを持ち、Contractsへ依存しない。
- `IUnitOfWork` と `IChatHistoryQuery` は Application 境界の
  `src/app/contracts/ports/` に置く。
- InfrastructureはSQLAlchemy、ORM、明示的マッピング、セッションライフサイクルを
  担当する。
- チャット履歴Queryは呼び出しごとにsession factoryから読み取りセッションを作り、
  自身で閉じる。書き込み用Unit of WorkのQuery accessorは持たない。
- User、Team、Membership、ChatMessageの永続化変換はInfrastructureの明示的
  マッパーで行う。ドメイン集約のproperty名やprivate fieldの反射には依存しない。

## 前提と未確定事項

- 現在のデプロイ単位は一つのアプリケーションであり、境界を別サービスへ分割しない。
- どの領域がコアドメインかは、このテンプレートでは決定しない。
- Membershipの認可（誰が承認できるか）や退会後の再申請審査など、コードにない規則は
  この文書で補わない。
