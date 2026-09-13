# 起動と運用

## データとログイン

`uv sync --frozen`後、`collective init`で独立したデータディレクトリを作る。
すべてのコマンドで`--root /absolute/path`を指定できる。省略時は`.collective/`。
個人情報と実行記録はGit管理外に置く。
旧版の活動・通知形式は移行しない。旧データを残したまま、
`collective --root /absolute/path/to/new-data init`で別の保存先を作り、以後も同じ`--root`を指定する。

Codex CLIでログイン済みの利用者は、その認証を利用する。専用認証を使う場合は
実行環境で`CODEX_HOME`を指定してからログインする。
SDKと認証の仕様は[公式ガイド](https://learn.chatgpt.com/docs/codex-sdk)を参照する。
`--model`または`COLLECTIVE_CODEX_MODEL`で作業モデルを選べる。省略時はCodexの設定に従う。

| 保存先 | 内容 |
| --- | --- |
| `master.md` | マスターの思想と希望。直接編集できる |
| `characters/*.json` | 名前、価値観・関心、話し方、任意の`avatar_url`。直接編集できる |
| `state.sqlite3` | 活動・原文・判断、配信待ちの報告、Discordの宛先・送信試行・確認結果 |
| `evidence/*.md` | 原文・観測・実行結果・判断の閲覧用ファイル |
| `work/<char_id>/AGENTS.md` | 作業環境の案内。初回だけ作成し、以後の編集を保持 |
| `work/<char_id>/memory/*.md` | 本人が整理した理解・経験と、共有の原記録への参照 |
| `work/<char_id>/repos/` | 本人の対象リポジトリ。ghqのホスト・所有者・リポジトリ名の階層 |
| `work/<char_id>/tasks/<活動ID>/` | 必要な資料・成果物と、今回の`context.json` |
| `messages/*.md` | ローカルに配信した報告 |

`state.sqlite3`の原記録から未反映のMarkdownを再生成できる。
記憶は必要な時に通常のファイル操作で探し、要約だけで不十分なら根拠を読む。
記憶への更新は実行結果と一緒に確定し、書込み失敗時は次回再試行する。
ファイルを手で訂正した場合は`note`にも訂正を伝えると、原文と再判断の契機を残せる。
本人の作業環境がCodexの起動場所と書込み範囲になる。一時ファイルとキャッシュもそこへ置く。
引継ぎ先には独立した作業環境を用意し、送り手の成果物は判断記録に残した参照から確認する。

## 操作

`add`は活動IDを返す。以下の`ACTIVITY_ID`はそのIDに置き換える。
`add --repo URL`で対象を指定でき、複数ある場合は繰り返す。
Gitと[ghq](https://github.com/x-motemen/ghq#installation)をPATHに用意する。
実行前に基盤が`GHQ_ROOT=work/<char_id>/repos`で取得する。既存の作業ツリーは更新せず、
未コミットの変更を保持する。取得に失敗した場合は記録して再試行し、Codexの作業を始めない。
既存のローカルリポジトリを範囲に書くだけでは、そこへの書込みは許可されない。

```bash
uv run --frozen collective status
uv run --frozen collective history ACTIVITY_ID
uv run --frozen collective pending
uv run --frozen collective say ACTIVITY_ID 'こんにちは'
uv run --frozen collective note ACTIVITY_ID '前提を訂正します。対象はAです。'
uv run --frozen collective observe ACTIVITY_ID '対象の資料が更新された。' --key source-event-1
uv run --frozen collective stop ACTIVITY_ID
uv run --frozen collective resume ACTIVITY_ID --budget 10
uv run --frozen collective run --once
```

`say`は通常の会話。`note`は作業へ直接届ける原文、`observe`は観測情報。
同じ`--key`の入力は重複登録しない。
観測情報だけでは、返答待ち・停止・達成済み・予算超過の活動を再開しない。
停止済み・達成済みの活動を再開するには`resume`を使う。

一活動の初期予算は24回、各回の制限時間は1200秒、各回の操作上限は80回。
`add --budget`、`run --timeout`で変更できる。予算超過は達成と区別し、明示的な追加まで待つ。
これは呼出し回数と時間の上限であり、金額の厳密な上限ではない。

`run`は一データディレクトリにつき一つだけ起動する。途中で終了した場合は、同じ
コマンドで再開する。結果不明の試行を記録し、担当者に実際の状態の再確認を要求する。
停止要求と入力の更新は実行中も受け付け、通常1秒以内に中断を要求する。
既に外部へ反映した操作の取消しや、外部操作の厳密な一回実行は保証しない。

## 会話の思考担当と表現担当

会話の思考担当は、提供元とモデル名を独立して選べる。

| 設定 | 内容 |
| --- | --- |
| `COLLECTIVE_CONVERSATION_PROVIDER` | `gemini`（省略時）または`openai` |
| `COLLECTIVE_CONVERSATION_MODEL` | 会話の思考用モデル。構造化出力に対応するモデルを指定 |
| `GEMINI_API_KEY` | Geminiの会話・表現に使う認証 |
| `OPENAI_API_KEY` | OpenAI APIの会話に使う認証。Codex CLIのログインとは別 |
| `COLLECTIVE_GEMINI_MODEL` | 表現用モデル。省略すると元の発言内容を配信 |

会話の提供元がGeminiで会話用モデルを省略した場合は、表現用モデル設定を使う。
提供元を交換しても人格、マスターの思想、対話、本人の記憶と活動状態は引き継ぐ。
会話担当は作業を実行せず、返答内容と必要な活動への要求を決める。

`GEMINI_API_KEY`と`COLLECTIVE_GEMINI_MODEL`を設定すると、保存済みの内容をGeminiが
キャラクターの言葉に整える。
作業結果は毎回保存し、明示的な発言要求のある内容だけを配信する。質問と完了は発言必須。
表現生成に失敗した場合は、内容・理由・根拠・未確認事項・質問を含む代替文を使う。
作業の状態・成果・次回実行は維持する。
表現担当には作業Tool、MCP、個人の会話履歴や記憶を渡さない。

基盤が観測した設定の有無、接続・Webhook検証・表現・配信・会話の直近の結果は、時刻と出典を付けて
判断入力へ渡す。認証値は含めず、未観測は不明とする。過去の成功は現在の接続保証ではない。

## Discordを窓口にする

Discord Developer PortalでMessage Content Intentを有効にし、Botに対象チャンネルの
閲覧・履歴閲覧を許可する。Botは受信、Webhookは全発言の送信を担当する。
対象チャンネルに作成したWebhookのURLを`DISCORD_WEBHOOK_URL`、Botの認証を
`DISCORD_BOT_TOKEN`へ設定する。Webhookの作成・一覧取得は実行時には行わない。
設定値はGitに含めず、モデルにも渡さない。

```bash
uv run --frozen collective discord --activity ACTIVITY_ID \
  --channel-id CHANNEL_ID --master-id MASTER_USER_ID
```

通常発言は会話担当に届け、挨拶や質問だけでは指定活動を中断・再実行しない。
依頼・訂正・停止・再開の意思が含まれる場合だけ、指定活動へ反映する。
活動の新規作成は`add`で行う。会話から扱う活動は`--activity`で指定した一つ。
`!status`、`!stop`、`!resume`で状態確認・停止・再開できる。
操作の応答もWebhookから送る。停止は配信を待たず反映し、応答は定型文のまま保存・再配信する。
同じデータディレクトリの全発言を一つのWebhookから送り、投稿者名とアバターで仲間を識別する。
`characters/*.json`の`avatar_url`には公開画像のHTTP(S) URLを指定でき、省略時はWebhookの既定画像を使う。
Bot・Webhook・別ユーザーの発言は受け付けない。

スレッドへ送る場合は`--channel-id`に投稿スレッドID、その親のWebhookをURLに指定する。
起動時と送信前に両者の対応を検証する。初回にサーバー・送信先・WebhookのIDを固定するため、
別の組合せで使う場合は新しいデータディレクトリを用意する。同じWebhookのトークン更新は可能。

Discord配信は送信前の試行と、送信確認のID・本文・時刻を保存する。途中で終了した場合は
試行時刻以降の履歴をWebhook IDと通知マーカーで照合し、確認できた発言を再送しない。
確認できない試行は未送信一覧に保持して履歴の確認を続け、自動再送しない。
`pending`で通知IDと試行を確認できる。`attempt`がnullなら未試行、試行があり`receipt`がnullなら
送信結果が未確認。実際のチャンネルも確認する。未確認の間も他の通知・作業は継続する。
明確に拒否されたリクエストは、設定や権限の修正後に再試行できる。
長文は冒頭と全文添付で届け、メンションは無効にする。
ローカル報告は同じIDのファイルを置き換えるため、配信確認前の終了でも重複しない。
Discordを使う場合は`run`を別に起動しない。`discord`コマンドが実行と配信の両方を動かす。
Discordに紐付けた保存先では`run`を拒否し、通知がローカル配信で消費されることを防ぐ。
責務と受入条件は[Webhook配信設計](discord-delivery.md)を参照する。

## 検証の範囲

状態遷移・記憶・配信と外部SDKの契約は自動テストで確認する。
実際のCodexでも、記憶の読み取り、コマンド実行、成果作成、失敗後の再試行と達成を確認した。
Geminiの表現と従来のBot配信は稼働時の送信記録で確認した。
今回のWebhook配信はテストダブルで検証する。実Discordへの送信とは区別する。
会話の両提供元の契約と設定切替はテストダブルで検証する。
実際のGeminiでは、挨拶・作業への追加依頼・停止の判断と表現生成をローカル配信で確認した。
日常的な支援の有用性は、実際の支援対象で運用し、不要な活動・誤った達成・訂正の反映を評価する。
