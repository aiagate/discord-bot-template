# 独立受入検証

基準コード `<baseline-checkout>`、同リポジトリのAGENTS.mdと機能追加・APIエラー契約、および固定済みの `prompts/team.txt` / `prompts/tagline.txt` から作成した。モデルの実装パッチとtrialディレクトリは作成・調整中に参照していない。旧実験のprobeを補助として参照し、非ゼロ終了・例外検出・実アプリ登録・独立UoW・OpenAPI比較を改善した。

対象checkoutを作業ディレクトリとして実行する。EVIDENCEは上位READMEの手順で指定する公開資料の絶対パス。

```sh
export UV_CACHE_DIR=/tmp/review-uv-cache
export UV_PYTHON_INSTALL_DIR=/tmp/review-python
uv run --frozen python "$EVIDENCE/checks/team_probe.py" description 2000
uv run --frozen python "$EVIDENCE/checks/team_migration_probe.py" description 2000
```

紹介文の試行は両コマンドの引数を `tagline 160` にする。上限引数が固定要求と異なる場合も失敗する。

`team_probe.py` は実際の公開FastAPI appと登録済みルートをASGIから呼ぶ。使い捨てSQLiteにテーブルを生成し、0文字・Unicode上限・上限超過400・空白改行保持・欠落および各JSON型の422・未知ID404・不正ID400を確認する。作成・改名の既存入力と出力、GETの既存キー、改名後の新属性、独立Injector/UoWでの永続化読込も確認する。Versionは機能追加ガイドの「updateごとに+1」に従って確認する。

保存失敗はSQLiteのBEFORE UPDATEトリガーをABORTさせ、実際のflushにIntegrityErrorを発生させる。基準のGenericRepository→ALREADY_EXISTS→CONFLICT→HTTP409を厳密に確認する。GETと独立UoW、および監査日時を含むDB全列の不変を確認する。これはflush失敗の検証であり、commitのみの失敗を注入したものではない。

`baseline_openapi.json` は基準appから取得した公開仕様。既存endpointとschemaを比較し、新属性のGET追加のみを許容する。$refを解決し、title/description/summary/operationId/tags/example/examples/externalDocsなどの説明メタデータを比較対象から除外する。propertiesの名前は除外しない。required、型、default、validation、HTTP応答などの変更を検出するためであり、文書追加を互換性破壊として扱うためではない。既存component名は維持を要求する。再帰的schemaはこの基準仕様に存在せず、本probeは再帰schemaの汎用比較器ではない。

`team_migration_probe.py` は旧head `7d5f0d6a2b31` に2件の旧行を投入し、upgrade・downgrade・再upgradeで名前・ID・Version・監査日時を保持するか確認する。新属性は空文字。各upgrade後と空DBからの導入後にalembic checkを行う。文字列属性の永続化契約に合わせて新列のNOT NULLも確認する。

全チェックが真で、全シナリオ末尾まで到達した場合だけexit 0。それ以外はexit 1。例外をPROBE_JSONに記録する。早期returnを成功扱いしない。スキップはない。成功したチェック数だけを用いて全体成功と解釈しないこと。

`probe_selfcheck.py` は実装に触れず、両引数・両probeに対して成功、False、早期return、例外の終了コードとJSON出力を検証する。OpenAPIの参照解決・説明変更許容・descriptionというプロパティ名の保持・必須項目変更の検出も確認する。元の非公開成果物では自己検査ログと基準コードの負例ログを保存し、基準コードの両検査でexit 1を確認済み。公開版の要約は `../results/public-log-summary.json` を参照。これらは新機能の成功試験を代替しない。

人間時間の削減量は未測定。
