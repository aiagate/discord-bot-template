# trial-43 初回凍結差分の設計レビュー

対象: `patches/trial-43-initial.patch` と読み取り専用checkout `<trial-43-checkout>`。課題は `prompts/tagline.txt`。基準AGENTSとPROTOCOLの共通評価軸を使用した。文書割付は盲検ではない。実装本体、移行、テスト差分を確認した。コード編集・テスト再実行なし。

## 判定

**重大な機能・HTTP契約・依存方向・atomicityの不具合は見つからない。重大修正パッチは不要。**

| 評価項目 | 結果 |
| --- | --- |
| 重大機能・契約不具合 | 0件 |
| 依存方向逸脱・不要な汎用抽象 | 0件 |
| 不要な公開生成入力拡張 | 0件 |
| 共通テストへの機能固有処理分岐 | 0件 |
| 新規公開Docstring漏れ | 2シンボル |
| Response命名の観察 | 1件（CreateTeamResponseの更新への流用） |

各項目を機能欠陥と合算しない。

## 本体と契約の確認

Requestは必須strを維持し、160文字上限と文字列保持はDomainの値型が扱う。UseCaseは検証を集約変更前に完了し、取得・update・commitの失敗を返す。Mediator、GenericRepository、IUnitOfWorkを再利用し、既存UoWのスコープ終了時rollbackで未確定変更を破棄する。Repositoryや汎用レスポンス基底型は増やしていない。

明示マッパーはtaglineを双方向に保存・復元する。GETは既存id/name/versionを維持し、taglineを追加する。既存の作成HTTP入力、改名操作は維持し、非既定値を保存して別UoWから読み、改名後にも保持されることをテストしている。移行は基準revisionを親とし、NOT NULLの列と空文字server_defaultを追加する。

## 軽微所見

- **L1（2シンボル）:** `src/app/domain/aggregates/team.py` の公開property `Team.tagline` と `src/app/presentation/api/routers/teams.py:37` の `UpdateTeamTaglineRequest` にDocstringがない。基準AGENTSの明文規則に対する漏れであり、未変更の既存シンボルの漏れは加算しない。
- **L2（1観察）:** `src/app/presentation/api/routers/teams.py:107` 以降は更新にCreateTeamResponseを使用する。既存PUT /teams/{team_id}と同じ方式で、課題も既存更新の流儀を求めるため、意味上の命名のずれとしてのみ記録する。独自Responseを追加しなかったことを機能不良・HTTP契約破壊とは扱わない。

共通契約のケース定義に非既定値と保持フィールドを追加しており、共通テスト処理への機能名分岐はない。

## 検証の扱いと修正要否

実装側に実ASGIルートと実Mediatorによる取得更新・入力形式422・文字数400・unknown404のテストがある。値型のテストが集約テストファイルにあること、UseCase名がChangeであることは、それ自体を欠陥としない。

親担当から、独立API・移行検査の通過と開始差分ハッシュ全保持の報告を受けた。本担当が再実行した結果ではない。全体pytest・静的チェックは親担当の別集計に委ねる。開始時README/メモと処置文書を機能変更量として数えない。

今回見つかった軽微規約差のために新規文書や重複する機能別commit失敗テストを増やす必要はない。重大修正なしで試行を終了できる。

