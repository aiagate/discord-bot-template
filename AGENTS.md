# 作業・運用ガイド

## Botの操作（このVM）

以下は2026-09-14に動作確認した構成です。新規環境の設定とDiscord管理コマンドの詳細は
[docs/collective.md](docs/collective.md) を参照してください。

| 用途 | 場所 |
| --- | --- |
| 実行チェックアウト | `/home/aiagate/ghq/github.com/aiagate/discord-bot-template` |
| 実装ブランチ | `codex/maid-goal-usecase-design` |
| 秘密値の読込元 | `/home/aiagate/ghq/github.com/aiagate/discord-bot-template/.env.local` |
| 設定・記憶・作業成果 | `/home/aiagate/.local/share/discord-bot/maid-collective` |
| 既存Bot機能のDB | `/home/aiagate/ghq/github.com/aiagate/discord-bot-template/bot.db` |
| ユーザーサービス | `discord-maid-collective.service` |

データ配下の `config.json` が接続先と実行設定、`master.md` がマスターの方針、
`characters/*.json` が人格です。`collective.sqlite` が活動・記憶・発言の正本で、
`work/<本人ID>/` に作業場所と実行結果を保持します。
確認時の設定は各人の振り返り1時間間隔、会話上限3ターン、作業上限900秒です。
自発的なTimesは全員で一つの会話を共有し、最後の発言から次の会話まで最低1時間空けます。
マスターの発言への返答と作業報告は、この時間制限の対象外です。

### 起動・停止

このVMではユーザーサービスを登録済みです。どのディレクトリからでも操作できます。
起動すると定期処理とDiscord投稿が再開するため、起動依頼がある場合に実行します。

| 操作 | コマンド |
| --- | --- |
| 起動 | `systemctl --user start discord-maid-collective` |
| 停止 | `systemctl --user stop discord-maid-collective` |
| 再起動 | `systemctl --user restart discord-maid-collective` |
| 状態 | `systemctl --user show discord-maid-collective -p ActiveState -p MainPID` |

定義は [deploy/discord-maid-collective.service](deploy/discord-maid-collective.service) です。
停止しても定義は残り、次回も同じ起動コマンドを使います。VM起動時の自動起動は設定しません。
異常終了時は5秒後に再起動しますが、明示的な停止後は再起動しません。

登録し直す場合は、ghq管理のリポジトリで次を実行します。Botは起動しません。

```bash
systemctl --user link "$PWD/deploy/discord-maid-collective.service"
systemctl --user daemon-reload
```

サービスはghq管理のコードと `.env.local`、データ配下の `config.json` を使います。
パスやNodeのバージョンを変えた場合は定義を更新して `daemon-reload` を行います。
コード・設定・人格・方針の変更はBotを再起動すると反映されます。

`.env.local` は `python-dotenv` で読み込みます。`source` や `uv --env-file` は使いません。
マスター宛てWebhookが未設定なら `DISCORD_CHARACTER_WEBHOOK_URLS_JSON` の先頭を使い、
Timesは設定に従って `DISCORD_CHARACTER_TIMES_WEBHOOK_URL` を使います。
秘密値をコマンド引数・文書・ログへ展開しないでください。

### 状態・ログの確認

```bash
systemctl --user show discord-maid-collective.service \
  -p LoadState -p ActiveState -p SubState -p MainPID -p NRestarts
```

稼働中は `active/running`、停止後は `inactive/dead` と `MainPID=0` を確認します。
`LoadState=not-found` の場合はサービスを登録してください。
プロセスの稼働だけではDiscord接続や作業進行を判断できません。保存状態も確認します。

```bash
/home/aiagate/.local/bin/uv run --frozen \
  --project /home/aiagate/ghq/github.com/aiagate/discord-bot-template python - <<'PY'
import json
import sqlite3
from collections import Counter
from pathlib import Path
from app.infrastructure.collective.codex_process import process_start

root = Path("/home/aiagate/.local/share/discord-bot/maid-collective")
db = sqlite3.connect(f"file:{root}/collective.sqlite?mode=ro", uri=True)
try:
    for kind in ("activities", "turns", "speeches", "parts"):
        records = [json.loads(row[0]) for row in db.execute(
            "SELECT body FROM records WHERE kind = ?", (kind,)
        )]
        print(kind, dict(Counter(row["status"] for row in records)))
        for row in records:
            if row["status"] in {"running", "retry", "held", "unknown", "rejected"}:
                print(" ", row["id"], row["status"])
finally:
    db.close()
for path in root.glob("work/*/runs/*/process.json"):
    record = json.loads(path.read_text())
    if process_start(record["pid"]) == record["start"]:
        print("Live work process:", record["pid"], path.parent)
PY
```

`running` は未完了の記録でもあるため、生存の証拠にはなりません。
`process.json` のPIDと開始時刻を実プロセスと照合します。停止後は
`Live work process` が出ないことを確認してください。
起動確認ではDiscordの接続と既存の投稿・投稿IDを照合し、依頼のないテスト投稿はしません。

ログが必要な場合は対象期間を絞ります。次の例はWebhookトークンを伏せます。
他のAPIキーやBotトークンも含まれていないか確認してから共有してください。

```bash
journalctl --user -u discord-maid-collective.service \
  --since '10 minutes ago' --no-pager |
  /home/aiagate/.local/bin/uv run --frozen \
    --project /home/aiagate/ghq/github.com/aiagate/discord-bot-template python -c '
import re
import sys
print(re.sub(
    r"(https://[^/\s]+/(?:api/)?webhooks/\d+/)[A-Za-z0-9_.-]+",
    r"\1[REDACTED]", sys.stdin.read(),
), end="")
'
```

### 停止時の確認

再起動前は作業の有無を確認し、完了を待てる場合は待ちます。
停止依頼ではサービスを停止し、`MainPID=0` と上記の子プロセス終了を確認します。
停止には最大120秒かかります。`kill -9` やロックファイル削除を通常手順にしないでください。
SIGINTによる終了コード130は、サービス定義で正常停止として扱います。

Botの停止は活動の取消しではありません。状態と成果は残り、次回起動時に復旧処理が走ります。
特定の活動を止める場合は、Bot稼働中にマスターが `!maid stop <活動ID>` を送ります。
マスターの `!maid` で活動と配信確認の対象を確認できます。

### 復旧・バックアップ

- バックアップは停止と子プロセス終了を確認後、データディレクトリ全体と既存Botの `bot.db` を保存します。
  `collective.sqlite` だけでなく、人格・方針・記憶投影・作業ファイル・実行結果も保全してください。
- 未完了作業は `work/<本人ID>/runs/*/` の `result.json`、`observations.jsonl`、`process.json` を確認します。
  保存済み成果がある場合は適用が保留されていないか調べ、同じ外部操作を無条件に繰り返しません。
- 成否不明の配信は自動再送しません。既知の投稿IDで `!maid confirm <断片ID> <投稿ID>` を使います。
  明確に拒否された配信は原因解消後に `!maid retry <断片ID>` で再試行できます。
- `held`、`blocked` は理由と入力・結果を照合してから対応します。DBの直接補正が必要なら
  先にバックアップし、元の結果と補正理由を残します。完了条件を緩めて通過させないでください。

## 開発ルール

### 設計と変更範囲

- 各要素について「無いと何が困るか」を箇条書きで確認し、必要なものだけを積み上げます。
  SOLID・YAGNI・KISSの目的に照らし、必要性を説明できない複雑性は削除候補にします。
- 既存のパターンと依存方向に従います。配置前に、どこからどこへ依存してよいかを明示してください。
  アプリケーション境界のインターフェースは `src/app/contracts/ports`、
  共有DTO・イベントトピック・ペイロードビルダーは `src/app/contracts/messages` に置きます。
  `domain/interfaces` はドメイン固有の抽象に限定し、共有境界型を `usecases` に逃がしません。
- 変更は目的を達成する最小限にし、不要になった旧実装は残さず削除します。
- フレームワークやライブラリの機能を変更する際は、最新の公式ドキュメントをWeb検索で確認します。
- 永続的な文章・コメントはAGYに添削を依頼し、返答と差分を確認します。
  サブエージェントはハングしていない限り中断や催促をせず待ちます。

### パッケージ・コード品質

- パッケージ管理は `uv` のみ。追加は `uv add package`、実行は `uv run tool`、
  開発依存の更新は `uv add --dev package --upgrade-package package` を使います。
- `pip`、`uv pip install`、`@latest` 構文、依存追加のための `pyproject.toml` 直接編集は禁止です。
- すべてのコードに型ヒント、公開APIにDocstringを付けます。関数は小さく、単一責務にします。
- Pythonは最大88文字、インポートを整列し、未使用のインポートを削除します。
  長い文字列は括弧で囲み、関数呼び出しとインポートは適切に改行します。
- `None` と文字列の型を明示的に絞り込みます。型エラーは前後の文脈と関数シグネチャも確認してください。

### 検証

フォーマット後に型・Lint・テストを確認します。CI失敗もこの順で直します。

```bash
uv run --frozen ruff format .
uv run --frozen pyright
uv run --frozen ruff check .
uv run --frozen pytest
```

- Ruffの自動修正は `uv run --frozen ruff check . --fix` を使います。
- 新機能にはテスト、バグ修正には回帰テストを追加し、境界条件とエラー処理も検証します。
- 非同期テストは `@pytest.mark.anyio` と `tests/conftest.py` の
  `anyio_backend` fixture（`asyncio` バックエンド）を使います。
  anyioのmarkが見つからない場合は `PYTEST_DISABLE_PLUGIN_AUTOLOAD="" uv run --frozen pytest` を試します。
- Pyrightが成功していれば、バージョン更新の警告は無視して構いません。
- コミット時のpre-commit設定は `.pre-commit-config.yaml` を正とします。
  Ruff更新ではPyPIのバージョンを確認し、設定の `rev` を更新して最初にコミットします。

### Git

- リポジトリは `ghq` で管理し、新規取得は `ghq get <URL>` を使います。
- 原則1依頼1PR・1PR1コミット。大きすぎる変更は分割を提案します。
- コミット前に `git status` を確認し、追加修正はamendします。
  作業をリモートへ公開し、pushには `git push --force-with-lease` を使います。
- ユーザー報告の修正・追加には `Reported-by:<ユーザー名>`、
  Issue関連には `Github-Issue:#<番号>` のトレーラーを付けます。
  例: `git commit --trailer "Reported-by:aiagate"`。
- `co-authored-by` 等の記載、コミットメッセージやPRでの使用AIツールへの言及は禁止です。
- 原則に反した作業が見つかった場合は報告し、修正してください。
