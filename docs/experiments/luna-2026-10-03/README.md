# 文書改善の再レビュー・独立実装4試行：公開証拠

結論は [REPORT.md](REPORT.md) を参照してください。既知のHTTP不一致は修正しましたが、文書の因果効果・広い汎化・人間レビュー時間の削減は未証明です。

このディレクトリは元の `luna-review-20261003.zip` の公開用サブセットです。原ZIPそのものではありません。生ログ、認証・保存環境の情報、環境依存の採取補助、前回公開資料の重複を除外しました。[PUBLICATION.json](PUBLICATION.json) に全原本ファイルとの対応・ハッシュ・変換・除外理由があります。前回資料は [../luna-2026-10-02/](../luna-2026-10-02/) に保持しています。

公開サブセットのZIPは同じブランチの `docs/experiments/luna-2026-10-03-public.zip`、チェックサムはその `.sha256` ファイルです。ZIP内はこのディレクトリと同一の公開内容です。元の非公開ZIPのサイズ・ハッシュと混同しないでください。

## 再現する

パッチは基準コミット `950058e2d9d2cfac01c3b1f50b5805097c04ab58` へ個別に適用します。実験コードをこの公開ブランチのアプリ本体へ採用したものではありません。

```bash
git clone --branch experiments/luna-review-baseline-20261003 --single-branch \
  https://github.com/aiagate/discord-bot-template.git evidence
EVIDENCE=$(cd evidence/docs/experiments/luna-2026-10-03 && pwd)
git clone https://github.com/aiagate/discord-bot-template.git trial
cd trial
git checkout --detach 950058e2d9d2cfac01c3b1f50b5805097c04ab58
git apply "$EVIDENCE/patches/trial-28-initial.patch"
uv sync --frozen
TEST_DATABASE_URL=sqlite+aiosqlite:// uv run --frozen pytest
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen pyright
uv run --frozen python "$EVIDENCE/checks/team_probe.py" description 2000
uv run --frozen python "$EVIDENCE/checks/team_migration_probe.py" description 2000
```

17/28は `description 2000`、43/59は `tagline 160` です。独立検査は使い捨てSQLiteを使い、失敗・例外・シナリオ未完了時は非ゼロ終了します。チェック数は試行数ではありません。詳細は [checks/README.md](checks/README.md)。

| パッチ | 適用方法 |
| --- | --- |
| docs-candidate.patch | 基準に文書3ファイル16行だけ追加 |
| trial-N-initial.patch | 基準へ単独適用。Nは17/28/43/59。処置文書・開始tracked差分を含む |
| trial-N-correction.patch | 対応するinitialの後にだけ適用。17/59は不要factory引数とDocstring、28/43はDocstringの修正 |
| old-heldout-fixed-full.patch | 旧Teamの修正済み全体版。基準へ単独適用 |
| old-heldout-correction.patch | 前回の ../luna-2026-10-02/patches/heldout-1.patch 適用後に重ねる差分 |
| trial-N-start.patch | 開始tracked差分の証拠。initialへ重ねない |

独立試行同士のパッチを重ねないでください。旧Teamのfull版とcorrection版も併用しません。原本の未追跡保全用メモは合成fixtureで、内容は `User-owned local note. Preserve this file.` と末尾改行です。開始ハッシュはresults/trial-N-start.jsonに残しています。

## 証拠の読み方

- PROTOCOL.md、prompts/：事前の方針・固定課題。文書介入は複合、割付は非無作為、各セルn=1。
- results/comparison.json、independent-validation.json：初回4試行の結果。修正後の成功数を加えていません。
- results/corrected-validation.json：別途修正後の検査。移行未再実行を明記。
- results/*review.md：別担当の設計・修正・レポート監査。完全盲検ではありません。
- results/public-log-summary.json：除外したログから抽出した件数と状態。元ログのハッシュ付きですが、完全な実行過程の監査を代替しません。
- results/patch-replay.json：7適用経路の適用・内容一致確認。7回の追加pytest実行を意味しません。

パッチ15本、独立検査コード3本、基準OpenAPIは原本とバイト同一です。公開用文書のリンク・環境記述調整はPUBLICATION.jsonで区別しています。SHA256SUMSはこの公開ディレクトリ内で `sha256sum -c SHA256SUMS` により検証できます。

## CIと公開範囲

公開時点の `.github/workflows/ci.yml` はmainへのpush／PRのみが対象で、この専用ブランチへのpushでは起動しません。新規実験・PR・main変更・merge・deployは今回の公開作業では行いません。既存の検証結果と、公開用の整合性確認を区別してください。
