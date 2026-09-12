# Discordから依頼するキャラクター作業

登録済みの全キャラクターに調査・コーディング・文書作成・検証を依頼できます。各自の性格や口調に加え、キャラクター固有の作業方針も引き継ぎ、依頼に応じて必要な作業を選びます。Codex Python SDK経由で作業ごとにApp Serverを起動します（Geminiの設定は不要）。

## 有効化

Linux・Git環境で、Botの依存関係をインストールします。

```bash
uv sync --frozen --extra codex
```

`.env`を設定します（IDはDiscordの開発者モードで取得）。作業ルートはBotリポジトリ外の絶対パスを指定してください。

```dotenv
CODEX_WORK_ROOT=/srv/character-work
CODEX_WORK_USER_IDS=345678901234567890
# 任意。全員の作業元となる既存Gitリポジトリ（空なら独立フォルダで作業）
CODEX_WORK_REPOSITORY=/srv/repositories/example
# 任意（未指定時はCodex既定モデル）
CODEX_WORK_MODEL=gpt-5.6-luna
# 任意（none / low / medium / high / xhigh / max、未指定時はCodex既定値）
CODEX_WORK_REASONING_EFFORT=max
# 制限時間（秒、既定1200）
CODEX_WORK_TIMEOUT_SECONDS=1200
```

作業は通常、`DISCORD_CHARACTER_GUILD_ID` と
`DISCORD_CHARACTER_WEBHOOK_URLS_JSON` を共用します。Webhookの送信先チャンネルが
作業チャンネルとして自動的に選ばれます。
別のサーバーまたは報告先を使う場合だけ、`CODEX_WORK_GUILD_ID` と
`CODEX_WORK_WEBHOOK_URLS_JSON` を追加してください。

作業に使う各親チャンネル（テキストまたはフォーラム）にWebhookを1つ設定します。
Webhookの送信先親チャンネルと配下のスレッドが自動的に作業対象チャンネルになります。
既存環境との互換や対象チャンネルの絞り込みを行う場合だけ、
`CODEX_WORK_CHANNEL_IDS`（カンマ区切り、任意）を追加指定できます。

ホストのファイルとネットワークへアクセスできる作業を受け付けるため、依頼ユーザーを
`CODEX_WORK_USER_IDS`にカンマ区切りで明示指定します（作業を有効にする場合は必須）。
DM・Bot・Webhookからの依頼は受け付けません。

進捗・完了報告は担当者の名前とアイコンで送信します。名前・アイコンは既存の
キャラクター定義から取得します。Webhook設定だけでも利用でき、Geminiのキーは不要です。

ホストのCodex CLIで、専用の`CODEX_HOME`へログインします（認証の詳細は[公式ガイド](https://learn.chatgpt.com/docs/auth)を参照）。

```bash
mkdir -p /srv/character-work/codex
CODEX_HOME=/srv/character-work/codex codex -c 'cli_auth_credentials_store="file"' login --device-auth
```

※ `CODEX_HOME`は設定したルートの`codex`サブディレクトリに合わせ、`config.toml`は置かないでください（権限・環境変数はBotが管理します。実行にはSDK同梱CLIが使用されます）。

Botを起動します（既存セッションがあれば先に停止）。通常会話も使う場合は`--extra ai`も併用します。

```bash
screen -dmS discord-bot uv run --frozen --extra codex start-bot
```

`CODEX_WORK_ROOT`が未設定または設定不備の場合、作業機能は無効化され通常Botのみ起動します。

## 使い方

対象チャンネルでキャラクター名を呼ぶか、コマンドで開始します。どのキャラクターも全種類の作業を行えます。

```text
Dorothy、公式資料を調べて手順書を作って
Mira、仮説を検証するPythonコードを書いて
Lilia、READMEのセットアップ手順を修正して
Noa、公式資料を比較して調査メモを作って
```

開始後、同一チャンネルで依頼者が送る通常発言は作業への追加指示（進行中は指示追加、完了・中断後はセッション再開）になります。

| コマンド | 動作 |
| --- | --- |
| `!work キャラクター名 依頼` | 指定したキャラクターで新しい作業を開始 |
| `!work status` | 状態と直近の進捗を表示 |
| `!work stop` | 中止（追加指示で再開可能） |
| `!work result` | 保存済みの最新成果を取得 |
| `!work chat` | 中止し、通常発言をキャラクター会話に戻す |

操作は同一チャンネルの依頼者本人のみ有効です。成果はWebhookからチャンネル内に公開されます。
完了時は成果ZIPを添付し、1700文字を超える報告本文はテキストファイルとしても添付します。
`!work chat`実行後は過去作業へ再接続できないため、必要な成果は事前に取得してください。

## 成果ZIPと検証

ZIPの`files/`に実ファイル、`report.md`に最終報告、`manifest.json`にファイル一覧・SHA-256・構文検査・実行コマンド記録を保存します。独立フォルダでは作業場所内のファイル、Git worktreeでは変更・未追跡ファイルを収集し、削除は一覧に記録します。全員に、調査した場合は出典付きのメモを`work-report.md`へ保存するよう指示します。

Botが直接検証するのは、ファイルの整合性とPython/JSON/TOMLの構文です。動作テストはCodexが作業環境内で実行したコマンドの終了コードと出力を記録します（最大100件、各出力の末尾4000文字）。構文エラー・非0終了・終了コード不明も報告に表示し、モデルの文章だけでは検証済みと判定しません。

添付・収集の上限は以下のとおりです。

- **成果収集**: 候補最大1000件（超過時はエラー）、添付最大100ファイル、1ファイル2MiB・実ファイル合計6MiB、成果ZIP全体で8MiBまで。
- **除外対象**: `.env*`・秘密鍵・管理情報（`.git`、`.codex`等）・キャッシュ（`node_modules`、`__pycache__`等）、シンボリックリンク・ハードリンク・特殊ファイル。除外理由は`manifest.json`に記録されます。
- **Discord送信**: 成果ZIPと長文の報告本文を添付します。各添付はサーバーのファイルサイズ上限も確認します。

成果ZIPは送信前に`artifacts/<作業ID>/<依頼メッセージID>.zip`へ保存します。Webhook送信に失敗しても`!work result`でハッシュ照合して再取得できます。作業場所が変更・削除されても保存済みZIPの内容は変わりません。

## 作業場所と制約

- **作業場所**: `workspaces/<キャラクターID>/<作業ID>`。リポジトリ設定時は、その`HEAD`から`codex/<キャラクターID>-<作業ID>`ブランチのworktreeを作ります（開始時点では元の未コミット変更を含みません）。未設定時は全員が独立フォルダを使い、調査もコード作成も可能です。既存の作業を再開するときは同じ場所を使います。
- **管理データ**: 作業記録は`tasks/`、Codex認証・会話は`codex/`に保存されます。フルアクセスのため、作業からホスト上の別パスも操作できます。
- **実行上限**: Bot全体で同時2件まで（同一チャンネル・依頼者は1件ずつ、単一プロセス運用）。1回は既定20分、検索・コマンド実行・ファイル編集の合計で最大100回です。
- **再起動時の挙動**: Bot再起動時に実行中タスクは中断状態（paused）になります。自動では動かず、明示的な追加指示で手動再開します。
- **実行権限**: 作業用Codexの`discord-work`プロファイルは、ホストのファイルシステムを読み書きでき、シェルからのネットワーク通信も許可します。これによりGitのコミット・Push、依存関係のダウンロード、任意のファイル編集を実行できます。承認は`deny_all`で、確認待ちにはなりません。Botの認証情報と親プロセスの環境変数は継承せず、成果収集時には`.env*`や秘密鍵などを添付対象から除外します。作業を受け付けるユーザーと報告先Webhookは必ず限定してください。
- **成果の反映**: 成果や作業場所は自動削除されません。生成された変更はホスト側でレビューして取り込んでください。

詳細は[Codex SDK](https://learn.chatgpt.com/docs/codex-sdk)および[Permissions](https://learn.chatgpt.com/docs/permissions)を参照してください。
