# AI機能分離とコミット再構成の対応メモ

作成日: 2026-08-27

## 目的

LLM、Web検索、長期メモリなどのAI関連機能は
`../agentic-chat-foundation` に残し、`discord-bot-template` を
AI機能に依存しないDiscord Botテンプレートとして整理する。

## 決定

Git履歴からもAI機能を除去する。現在の`main`は書き換え対象とし、
切替前の履歴は保全ブランチとタグで必ず残す。

この方針は既存cloneとPRのコミットSHAを無効にする。既定ブランチを切り替える
作業は、関係者への告知と保全参照のpushが済んだ後に実施する。

## 先に決めること

「コミットを修正する」には、次の2つの異なる目標がある。

1. **現行コードからAI機能を除去する**
   - `main` の履歴は変更せず、削除を通常の新規コミットとして追加する。
   - 既に共有・マージ済みの `main` に対して安全な選択肢。
2. **AI機能をGit履歴からも除去する**
   - 2026-05-26以降の該当コミットを再構成し、force-push が必要になる。
   - 共同利用者、既存PR、参照されているコミットSHAへ影響する。

今回の選択は 2 である。以下の再構成手順を実施する。

## 現時点で確認できた混在箇所

- AI関連の実装は、少なくとも次のコミットで大きく混在している。
  - `23c5fc4` (`2026-05-26`, 配置・構造のリファクタリング)
  - `77ac081` (`2026-05-27`, 型ヒントとチャットイベントpayloadの修正)
- このため、これらのコミットをそのまま `revert` または `drop` すると、
  AI以外の配置変更・型修正・イベント関連の変更まで失う可能性が高い。
- `../agentic-chat-foundation` にはAI、検索、メモリの実装が存在し、作業ツリーも
  clean である。移植元としてではなく、AI側の正本として扱える。
- AI混在前の再構成起点は `82e159d`（PR #41のmerge commit）である。
  その直後の `23c5fc4` はAI機能とChat/LINE/構造変更を一括導入している。
- 後続の `7f52e6d`、`e91481e`、`77ac081` もAI変更と非AI変更を混在させるため、
  原則として丸ごとのcherry-pickはしない。`ac7d436` はAI非依存かを確認後に
  個別に再適用できる。

## 現行コードから除去する対象（棚卸し）

### 削除候補

- 依存関係: `openai`, `google-genai` と、AI機能専用であれば `redis`。
- ports: `ai_service`, `web_search_service`, `memory_*`,
  `search_context_store`。
- messages: `generated_content`, `memory_context`, `retrieved_context`,
  `tool_use`、検索・返信生成だけに使うイベント定義。
- services: GPT/Gemini/Ollama、メモリ保存・検索・統合・embedding・decay、
  検索コンテキストストア。
- use cases: `usecases/memory/*`, `usecases/search/*`,
  `generate_content*` と、返信をAI生成するためだけの保存後イベント処理。
- workerの検索・メモリsleep・返信生成ハンドラーと登録。
- AI機能専用のテスト、PoC、設計文書、環境変数、マイグレーション。

### 残す候補（要件確認が必要）

- Discord、LINE、FastAPI、User/Team/Membership、ドメインモデル、ORM、
  Unit of Work、Alembic。
- EventBusは、AIなしでも非同期ワークフローをテンプレートに含めたい場合のみ残す。
  AI返信生成だけが利用目的なら、関連イベントとRedis/Postgres実装も削除する。
- 受信チャットの永続化は、将来のBot機能の土台として残すか、AI専用機能として
  まとめて外すかを決める。残す場合は、保存後にAI返信を発行する責務を取り除く。

## 現行コードから除去する場合の参考手順

1. `../agentic-chat-foundation` に必要なAI機能が揃っていることを確認し、
   このリポジトリへ戻さない方針を明文化する。
2. 「残す機能」を先に確定する。特にChat保存・EventBus・LINE連携の扱いを決める。
3. AI固有の契約、実装、UseCase、Worker、テスト、PoC、ドキュメントを削除する。
4. `container.py`、エントリーポイント、依存関係、`.env.example`、Composeを整理する。
5. 不要なAlembic migrationは**適用済みDBが存在するなら削除しない**。
   新規migrationで後方互換な削除を行うか、開発専用DBのみなら初期migrationを
   作り直すかを別途判断する。
6. READMEとアーキテクチャ文書を、AIなしの実態へ更新する。
7. `uv lock` を更新し、Ruff、Pyright、pytest、実行起動確認を行う。
8. 変更を意味ごとに分けてコミットする。
   - `refactor: remove AI application boundaries`
   - `refactor: remove AI runtime integrations`
   - `docs: describe non-AI bot template`
   - `test: remove AI scenarios and cover retained chat flow`

## 履歴を再構成する手順（採用）

1. 現行`main`に対して、保全用のannotated tagとリモート追跡用ブランチを作る。
   例: `archive/pre-ai-history-20260827`。この参照は履歴切替後も削除しない。
2. `82e159d`を起点に、置換用ブランチ（例: `rewrite/non-ai-template-history`）を作る。
3. `23c5fc4`から、AIと無関係な変更を論理単位で**手作業により**再適用する。
   候補はChatの永続化、LINE入口、DB migration、ドキュメント構成である。ただし、
   それぞれを残すかは「AIなしテンプレートに必要か」で判断する。
4. `7f52e6d`と`77ac081`から必要な非AI変更だけを再適用する。`e91481e`は
   AIメモリ機能の削除だけを扱うため、新履歴には通常不要である。
5. 新規コミットは「AIなしの機能単位」に分ける。目安は次のとおり。
   - `feat: add persisted chat messages`（残す場合）
   - `feat: add LINE message adapter`（残す場合）
   - `refactor: organize worker handlers`（Workerを残す場合）
   - `build: discover app subpackages`
6. 各コミットで `uv run --frozen ruff check .`、
   `uv run --frozen pyright`、`uv run --frozen pytest` を実行する。
7. 元の `main` と新履歴をdiffし、残すべきDiscord/LINE/API/ドメイン機能が
   欠けていないことを確認する。
8. CIでの検証、クリーンcloneからの`uv sync --frozen`、主要な起動確認を行う。
9. 共同利用者へforce-pushの影響と切替手順を通知してから、既定ブランチを切り替える。
   現`main`を保全参照に残した状態で、新履歴を`main`へforce-pushする。

`git filter-repo` のようなファイルパス一括削除は、AI以外の変更も同じコミットに
含まれるため、このケースには適さない。コミット再構成では、内容を読んで
非AI部分を再適用する方法を選ぶ。

## 完了条件

- `pyproject.toml` とロックファイルにAI SDKが残っていない。
- `src/app`、`tests`、ドキュメント、環境変数にAI・検索・長期メモリへの参照がない。
- 残存するイベントとWorkerが、削除済みのtopicやUseCaseを参照しない。
- 新規DBに対するmigrationと主要な起動コマンドが動作する。
- Ruff、Pyright、pytestがすべて成功する。

## 実施結果

- 2026-08-27に、`82e159d`を基点とする再構成履歴を作成した。
- AI、検索、長期メモリ、AI返信生成の実装・依存関係・テスト・設計資料は、
  新履歴に含めていない。
- AIなしで意味を持つチャット永続化、LINE Webhook、EventBus契約は再適用した。
- 旧履歴は`archive/pre-ai-history-20260827`ブランチおよび
  `pre-ai-history-20260827`タグで保全している。
- 検証結果: Ruff、Pyright、pytest（192件）がすべて成功した。
