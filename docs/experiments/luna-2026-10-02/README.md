# 実験成果の読み方・再現方法

まず REPORT.md を参照してください。全6回の最終状態を記録しており、都合の悪い結果も残しています。

- prompts/：実装に使った要件。5回のプロフィール課題は同一
- patches/：各回の実装差分と、2回の同機能再実行で試した文書差分
- checks/：実装側のテストとは別に実行したASGI/APIとMigrationの確認コード
- results/：最終の全体テスト、静的解析、独立チェック、比較集計
- manifest.json：コミット、モデル指定、実行環境、チェック結果、ファイルハッシュ
- next-doc-candidate.md：結果を踏まえた追記候補。これは再実行で未検証

## 差分の扱い

各実装パッチは、固定コミットへそれぞれ単独で適用するためのものです。複数回分を重ねて適用しないでください。

- baseline-1〜3.patch：元の文書を使ったプロフィール実装
- improved-1〜2.patch：文書補強＋プロフィール実装。文書差分を既に含むため、docs-intervention.patchを先に重ねる必要はありません
- heldout-1.patch：Team description実装。開始時に与えた文書変更を実装中に戻したため、最終パッチに文書変更は含まれません
- docs-intervention.patch：試験した文書変更だけを取り出した候補

実装パッチはいずれも未公開の実験結果であり、本番採用前のレビューを置き換えるものではありません。

## 再現例

使い捨ての新しいcheckoutで、次を実行します。通常の開発DBや本番DBを指定しないでください。

```bash
git clone https://github.com/aiagate/discord-bot-template.git trial
cd trial
git checkout --detach 950058e2d9d2cfac01c3b1f50b5805097c04ab58
git apply /path/to/patches/baseline-1.patch
uv sync --frozen
TEST_DATABASE_URL=sqlite+aiosqlite:// uv run --frozen pytest
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen pyright
uv run --frozen python /path/to/checks/profile_probe.py
uv run --frozen python /path/to/checks/migration_probe.py
```

Team課題の場合は heldout-1.patch を使い、最後の2つを team_probe.py と team_migration_probe.py に置き換えます。profile_probe.pyはTeam用のHTTPヘルパーとしても使うため、checks/内の4ファイルは同じディレクトリに置いてください。

プローブは一時ディレクトリ内のSQLite DBを使います。結果JSONのpassed/totalを確認してください。プローブ自身のプロセス終了コード0は、全チェック合格を意味しません。

書き込み可能なuvキャッシュが必要です。必要ならUV_CACHE_DIRとUV_PYTHON_INSTALL_DIRを自分の書き込み可能な場所に設定してください。結果は実験時の依存ロックと環境で得たもので、PostgreSQLや実サービスは検証していません。
