# メイド集団の起動と確認

通常の発言、Timesの会話、定期的な振り返りから、本人が仕事を開始します。
会話はGemini、作業はCodex App Server、発言はキャラクター名のWebhookを使います。
既存のテンプレート機能とDBはそのまま利用できます。

## 設定

Linux、Python 3.13、`uv`、`ghq`、認証済みのCodexとAGYが必要です。
人格とマスターの方針のひな型を生成します。既存ファイルは上書きしません。

```bash
uv sync --frozen
uv run --frozen python -m app.presentation.collective --root ./data
```

`data/master.md` に支援する業務・達成条件・任せる範囲を書きます。
`data/characters/*.json` で人格とアイコンURLを設定し、使わない本人の設定は外します。

次の内容を `data/config.json` として保存し、IDとパスを実環境に置き換えます。
チャンネルは同じサーバー内の異なるテキストチャンネルを指定します。

```json
{
  "root": "/absolute/path/to/data",
  "guild_id": 1,
  "master_id": 2,
  "master_channel_id": 3,
  "times_channel_id": 4,
  "agy_skill": "/absolute/path/to/agy-worker/SKILL.md",
  "settings": {
    "reflection_seconds": 3600,
    "times_interval_seconds": 3600,
    "turn_timeout": 900,
    "max_activity_runs": 24,
    "max_round": 3
  }
}
```

環境変数に `COLLECTIVE_CONFIG`（設定ファイルのパス）、`DISCORD_BOT_TOKEN`、
`GEMINI_API_KEY`、`MAID_MASTER_WEBHOOK_URL`、`MAID_TIMES_WEBHOOK_URL` を設定し、
`uv run --frozen start-bot` で起動します。秘密値を設定JSONや記憶に書く必要はありません。
DiscordのMessage Content Intentを有効にし、Botに両チャンネルの閲覧と履歴取得を許可します。
起動時にWebhookの所属チャンネルとモデルの上限を確認します。

トップレベルの `gemini_model`、`codex_model`、`max_output_tokens`、`token_margin` は設定で変更できます。
Codexから振り返りを始める場合は `settings.reflection_lane` を `"work"` にします。
未登録の活動については読取りと提案に限定し、開始を保存した後に実作業へ進みます。
設定とマスターの方針を変更したらBotを再起動します。

自発的なTimesは全員で一つの会話を共有し、最大 `max_round` ターンで終えます。
最後の発言から `times_interval_seconds` 秒は別の自発的な会話を始めません。
各人の振り返り・記憶・作業は継続し、マスターの発言への返答と作業報告は待たせません。
話題は実際の依頼・記憶・確認済みの出来事に基づき、架空の飲食や動作、既出の言い換えを避けます。

このVMの常駐起動には、登録済みの `systemctl --user start discord-maid-collective` を使います。
停止・再起動・再登録は [AGENTS.md](../AGENTS.md) を参照してください。
マスター宛てWebhookの環境変数を省略した場合は、既存の
`DISCORD_CHARACTER_WEBHOOK_URLS_JSON` 配列の先頭を使います。

## 継続と復旧

`data/collective.sqlite` が活動・原記録・記憶・発言の正本です。
`data/work/<本人ID>/` に同じ本人の作業場所を保ち、記憶を実行前に投影します。
バックアップはBot停止後、データディレクトリ全体を保存します。
別ブランチで稼働したDB・作業場所は自動移行しません。

作業は全体で一件ずつ進め、会話と配信は独立して動きます。
再起動時は保存済みの結果を適用し、結果不明の作業はプロセス終了を確認してから
実状態の確認へ戻します。終了を確認できない間は作業枠を保持します。

普段の訂正・停止・再開は通常の文章で伝えます。
次の管理操作は、設定したマスターのDiscordアカウントだけが実行できます。

- `!maid`: 活動状態と配信確認が必要な断片を表示。
- `!maid stop <活動ID>`: モデルが応答できない場合も停止を保存。
- `!maid confirm <断片ID> <Discord投稿ID>`: 成否不明の投稿をAPIで照合。
- `!maid retry <断片ID>`: 設定などの原因を解消した後、明確に拒否された配信を再試行。

送信結果が不明なら自動再送しません。同じ宛先の後続投稿も待機します。
既知の投稿IDで本文を照合できれば後続を再開します。投稿の消失だけでは未送信と判定しません。
確実に拒否された送信とモデル呼出しは、設定した回数まで再試行します。
会話API障害でも、保存済み本文の配信と管理停止は利用できます。

## 検証範囲

`uv run --frozen pytest tests/collective` で、実際のSQLiteと作業場所を使って
自発起動、本人別のTimes、訂正・停止、再起動、記憶、配信、入力容量を検証します。
外部サービスの通常テストは代替実装を使い、利用料金やDiscord投稿を発生させません。

設計のA13（実業務の負担軽減）は、マスターによる確認が必要です。
同じ業務範囲で、依頼・説明・監督・成果確認・手直しの時間と介入回数を比較し、
成果が役立ったかを判断します。テスト通過だけではこの条件を達成済みにしません。
