# LLM入力コンテキストの確認（2026-09-12）

キャラクター選定・通常応答・Times・Codex作業の入力生成処理と、ローカルの保存ログを確認した。
Timesには、UTCの投稿時刻を日本時間へ換算して答えた記録があった。
以下は実装上の確認結果であり、形式間の回答精度を比較する評価は行っていない。

| 対象 | 確認結果と対応 |
| --- | --- |
| 投稿・履歴・キャラクター記憶の日時 | UTCをそのまま渡していた。共有の `prompt_datetime` で `2026-09-12 16:12:36 JST` のように秒単位で表示する。保存値・検索カーソルのUTCと小数秒は維持する。 |
| 選定用の記憶要約・Timesの過去投稿 | 日時が欠けていた。要約には `memory_summary_observed_at`、Timesには `created_at` をJSTで添える。後者はエピソード作成日時で、投稿の送信時刻ではない。日時不明は `null` とする。 |
| 「今日」「昨日」などの相対表現 | 今回の投稿日時を会話の基準とし、過去の本文・記憶の相対表現はその投稿・記憶の日時で解釈するよう指示する。本文自体は書き換えない。 |
| Discord固有の記法 | 本文の `<t:UNIX秒:R>`、ユーザー・チャンネル・ロールのIDメンションは未展開。Unix秒の換算や、履歴にないIDの名前の特定をモデルへ任せている。確認した保存ログには出現しなかった。利用時は原文を保ち、JST日時や取得済みの表示名を別に添えるのが改善候補。 |
| 添付・埋め込み | 埋め込みのタイトル・説明・フィールドは文字列化するが、添付画像・ファイルやDiscordネイティブの投票は入力対象外。これらを指す質問には必要な情報が届かない。形式変更だけでなく、取得・入力対応が必要。 |
| Codex作業 | これまでは共通のキャラクター口調・担当だけを渡していた。キャラクター固有の作業方針を定義し、実作業の判断と完了報告へ渡す。 |
| JSON・識別子・並び順 | 日本語は `ensure_ascii=False` で保持し、本文を二重JSON化していない。履歴は古い順、今回の投稿は末尾に置く。投稿者名・種別・返信先を別項目で渡す。IDは照合に必要なため残す。JSON自体を置き換える根拠は今回見つからなかった。 |

実装箇所:

- [共有変換](../../src/app/contracts/messages/character_prompt.py)
- [選定・通常応答](../../src/app/usecases/chat/generate_character_response.py)
- [Times](../../src/app/usecases/chat/generate_times_episode.py)
- [Discord本文の取り込み](../../src/app/presentation/bot/cogs/message_listener_cog.py)
- [Codex作業](../../src/app/usecases/chat/character_work.py)
- [Codex完了報告](../../src/app/infrastructure/gemini/work_reviewer.py)

日時変換には標準ライブラリの `astimezone` を使う。
[Python datetime](https://docs.python.org/3/library/datetime.html#datetime.datetime.astimezone)

構造を明確にし、曖昧な項目を説明するという公式の指針を踏まえ、既存JSONの項目と指示を補った。
[Geminiのプロンプト指針](https://ai.google.dev/gemini-api/docs/prompting-strategies)

Discordは時刻をUnix秒の専用記法で、メンションをIDで表す。
[Discordのメッセージ記法](https://docs.discord.com/developers/reference#message-formatting)
