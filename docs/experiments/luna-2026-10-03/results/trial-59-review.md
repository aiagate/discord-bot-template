# trial-59 初回凍結差分の設計レビュー

対象: `patches/trial-59-initial.patch` と読み取り専用checkout `<trial-59-checkout>`。`prompts/tagline.txt`、基準AGENTS、PROTOCOLの事前評価軸を参照。レビュー担当による実行・コード編集なし。文書割付は盲検ではない。

## 判定と修正要否

**重大な機能・HTTP契約・依存方向・atomicityの不具合は見つからない。重大不具合の修正パッチは不要。** 不要な生成API拡張を1件、軽微なDocstring漏れを2シンボル、命名上の観察を1件記録する。これらを機能欠陥と合算しない。

| 評価軸 | 静的レビュー結果 |
| --- | --- |
| 主要機能・HTTP契約 | 重大所見なし。必須strをRequest、160文字上限をDomainで検証し、既存Mediator経由でエラーを変換する。GETはid/name/versionを維持してtaglineを追加する。 |
| 永続化・移行 | 追加値を明示マッパーの両方向で扱い、移行は旧行を空文字にする。新生成の既存呼び出しも空文字。 |
| 失敗時の確定防止 | 入力検証→取得→集約変更→update→commitの順で、各Errを伝播。既存UoWのrollbackを利用する。 |
| 依存・既存機構の利用 | Domainの外向き依存追加なし。Mediator、GenericRepository、IUnitOfWorkを再利用。新しいRepositoryや汎用抽象なし。 |
| 不要な生成入力拡張 | 1件。Team.formにtagline任意引数を追加。下記参照。 |
| 共通テストの機能固有分岐 | 0件。既存パラメーター表へchange_taglineのケースを追加しただけで、if等の処理分岐は増やしていない。 |
| 公開Docstring | 新規公開シンボル2件で漏れ。Team.tagline、UpdateTeamTaglineRequest。 |
| 命名 | CreateTeamResponseを更新へ流用。既存更新操作を模倣したもので、機能不良とはしない。 |

## 非重大の設計所見

**D1: Team.formのtagline引数は課題に不要な生成契約の拡張。** `src/app/domain/aggregates/team.py:44` は、既存のform(name)に空文字既定のtagline引数を追加し、その値を新規Teamへ渡す。既存HTTP作成入力と既存の呼び出し挙動は維持されているが、新たに非空tagline付き生成を公開する必要は課題から導けない。復元にはrestoreがあり、更新にはchange_taglineがあるため、機能達成のための必須変更ではない。採用時には引数を元へ戻すことを推奨するが、事前PROTOCOLの「重大な再現可能不具合の修正」対象としては数えない。重大機能欠陥は0、不要拡張は1として別集計する。

## 軽微所見

- **L1（2シンボル）:** `src/app/domain/aggregates/team.py:76` の公開property `Team.tagline` と `src/app/presentation/api/routers/teams.py:37` の `UpdateTeamTaglineRequest` にDocstringがない。基準AGENTSの明文規則に対する漏れ。既存の未変更シンボルの漏れは加算しない。
- **L2（1観察）:** `src/app/presentation/api/routers/teams.py:107` 以降は更新にCreateTeamResponseを使う。既存PUT /teams/{team_id}も同じ型を使い、課題は既存更新の流儀を求めるため、命名の意味上のずれとして記録するのみ。独自Response型を作らなかったことを契約破壊とは判定しない。

`tests/domain/test_aggregate_contracts.py:88` 付近のchange_tagline追加は、既存のchange_email/change_nameと同じデータ駆動ケースである。共有テストファイルに変更があるという理由だけで機能固有分岐と採点してはいけない。

## 検証証拠の境界

親担当から独立ASGI/API 103件通過の報告を受けた。これは本レビュー担当の独立実行ではない。migration/full pytest/static checks、開始差分ハッシュの結果は親担当の別集計に委ねる。パッチのREADME追記は事前に置かれた差分であり、機能変更量には算入しない。untrackedメモ保持も最終パッチの有無だけでは判定しない。

機能用commit失敗テストがないこと、APIテストがルータ直接呼び出し中心であることは確認したが、今回の制御フローに重大欠陥は見つからず、独立ルート検査も別途行われている。全層への同型テスト追加を要求しない。
