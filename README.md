# Autonomous Maid Collective

マスターの状況と目的を理解し、各自の関心と判断を持つ仲間が、必要な支援を自ら見つけ、
実行し、継続するためのプロジェクトです。

設計は次の順に読みます。

1. [目的とハイレベルユースケース](docs/purpose.md): 何ができるようになるか。
2. [ユースケース](docs/use-cases.md): どんな状況で、誰が何を行い、何が残るか。
3. [実現方法](docs/architecture.md): 責務、依存方向、保存と実行の仕組み。
4. [受入条件](docs/acceptance.md): 目的を達成したと判断できる観測結果。
5. [起動と運用](docs/operations.md): 設定、実行、状況確認、Discordとの接続。

[実装改善計画](docs/improvements.md)に、今回の改善の目的・実装範囲・受入条件をまとめています。

旧実装はGit履歴にあります。新しい実行環境は独立した作業ディレクトリを使います。

## 最初の起動

Linux、Python 3.13以上、uvを使用します。対象リポジトリの取得にはGitとghqが必要です。

```bash
uv sync --frozen
uv run --frozen collective init
uv run --frozen collective add '対象の不具合を調べ、修正と検証を行う' \
  --criterion '不具合の原因・修正内容・検証結果を示す' \
  --scope '担当者の作業環境で対象を調査・編集・検証する。公開や送信は含まない。' \
  --repo https://github.com/OWNER/REPO --character noa
uv run --frozen collective run
```

実行にはCodexのログインが必要です。初期状態の報告先は`.collective/messages/`です。
`init --master-file /path/to/master_context.md`で既存の思想・希望を取り込めます。
登録後は追加の発言がなくても実行し、担当者の判断で再確認や引継ぎを行います。

初期の仲間はDorothy、Astra、Noaです。定義は`.collective/characters/`で編集できます。
一つの活動を順次担当し、目的、未完了事項、根拠を引き継ぎます。
各自の`work/<char_id>/`に案内の`AGENTS.md`、個人記憶、リポジトリ、作業資料を持ちます。
同じキャラクターの会話と作業は、その本人の記憶を参照します。

会話の思考、作業、表現は独立した担当です。会話の思考はGeminiとOpenAI APIから選べ、
モデルを変更しても人格・記憶・活動状態を引き継ぎます。
Discordでの通常の会話は作業の完了を待たず、挨拶だけで作業をやり直しません。
Botは耳、Webhookは口として、全発言を本人の名前と任意のアバターで届けます。
提供元とモデルの設定は[起動と運用](docs/operations.md)に記載しています。

## 検証

```bash
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen pyright
uv run --frozen pytest
```

初期版は一台・一人のマスター・順次実行です。並列分担・合流、複数利用者の記憶分離、
外部サービスの常時監視は含めていません。旧版の実行データとは互換性を持たせず、
新しいデータディレクトリで開始します。詳細は[起動と運用](docs/operations.md)を参照してください。
