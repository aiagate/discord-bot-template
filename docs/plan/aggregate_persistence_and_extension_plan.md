# 集約の永続化と機能追加手順の改善計画

作成日: 2026-09-19。状態: 過去の改善計画文書。

> [!NOTE]
> 本ドキュメントは作成時点での改善計画です。現行の設計および機能・集約の追加手順については、正本ガイドである **[機能追加ガイド（ADDING_FEATURE.md）](../development/ADDING_FEATURE.md)** を参照してください。

3つの課題を、①ORM標準の保存と専用Repositoryの接続、②登録から動作確認までの手順、
③新しい集約にも適用するテスト、の順で解消する。原則として実装・テスト・文書を1PRにまとめる。

## 現状の確認

- [GenericRepository](../../src/app/infrastructure/repositories/generic_repository.py)は、
  `add()`では`Session.add()`、Versionなしの`update()`では`merge()`を使う。
  Version付きの更新はテーブルの列を列挙した直接UPDATE、削除は直接DELETEであり、
  関連オブジェクトを処理するORMの保存経路を通らない。
  また、`IntegrityError`発生時にRepository内部で`rollback()`を直接呼び出しており、
  UoW側のトランザクション管理やコミット可否判定と連携できていない。
- [SQLAlchemyUnitOfWork](../../src/app/infrastructure/unit_of_work.py)は
  `GenericRepository`を直接生成する。SessionとRepositoryの寿命は既にUoWで管理しているが、
  専用Repositoryを同じSessionで生成し、型付きで取得する経路がない。
  Repositoryが内部でrollbackした事実をUoWが記録していないため、その後の`commit()`で
  意図しない空コミットや誤った成功判定を許容するリスクがある。
- ORMモデルの読み込みは[パッケージ](../../src/app/infrastructure/orm_models/__init__.py)と
  [Alembic](../../alembic/env.py)、マッパーは[orm_registry.py](../../src/app/infrastructure/orm_registry.py)、
  Handlerは[mediator.py](../../src/app/application/mediator.py)、入口は各Presentationにある。
  [現在の追加手順](../ARCHITECTURE.md#新しい機能集約の追加)（現 [機能追加ガイド](../development/ADDING_FEATURE.md)）は、これらとマイグレーションの確認を一続きには示していない。
- 既存4集約には同一性比較のテストがあり、Membershipには不正な状態遷移のテストもある。
  [マッピングテスト](../../tests/infrastructure/test_domain_mappings.py)は属性を個別に比較している。
  一方、新しい集約で必要な検証を省略したときに検出する仕組みはない。
- ロックファイルの対象はSQLAlchemy 2.0.44、SQLModel 0.0.27、Alembic 1.17.2。
  現行の公式資料を参照しつつ、この計画のためだけに依存バージョンは変更しない。

SQLAlchemy公式は、直接UPDATE/DELETEがORMのUnit of Workによる自動処理を迂回することを説明している。
今回の変更対象は、その経路と集約の保存契約の接続である。
[公式資料: ORM UPDATE/DELETEの注意点](https://docs.sqlalchemy.org/en/20/orm/queryguide/dml.html#important-notes-and-caveats-for-orm-enabled-update-and-delete)

## 各要素がないと何が困るか

- **ORMの関連処理**がないと、子の追加・変更・削除のSQLと実行順をRepositoryごとに管理する必要がある。
  SQLの生成はORMに任せ、ドメインとORMの変換・集約の所有関係は明示する。
- **集約全体のVersion検査**がないと、親を変更せず子だけを変更した操作同士が上書きし合う。
  楽観ロックは削除せず、親のVersionで子を含む保存を保護する。
- **Sessionを共有する専用Repositoryの取得経路**がないと、特殊な検索・保存のたびにUoWを修正したり、
  別トランザクションを誤って作ったりする。生成用の関数を注入する最小の仕組みを設ける。
- **一続きの追加手順と登録確認**がないと、実装済みの機能が起動時や呼び出し時に初めて失敗する。
  重複するモデル読み込みを整理し、責務の異なる登録は手順とテストで結び付ける。
- **共通の確認項目と集約固有の振る舞いテスト**がないと、同一性・復元・拒否時の状態保持に確認漏れが生じる。
  共通化するのは確認方法であり、業務ルール自体を汎用基底クラスに押し込めない。

この段階では、本番でのモジュール自動探索、万能な機能登録DSL、集約の共通基底クラス、
独自の変更追跡機構は追加しない。既存の明示的マッパー、UoW、テストを使って不足を補う。

## 1. 保存方式と専用Repositoryの接続

### 1-1. 既存の保存契約を先に固定する

既存テストを整理し、必要なケースを追加する。SQL発行回数などに依存するモックテストは、
保存結果とエラーを確認するテストに置き換える。

- 新規Versionは0、成功した`update()`ごとに1進む。同じ値で更新する場合の既存挙動も維持する。
- IDと`created_at`を保ち、`updated_at`とVersionを反映した集約を返す。
- 更新・削除の`NOT_FOUND`、`VERSION_CONFLICT`、一意制約競合の`ALREADY_EXISTS`を維持する。
- `ChatMessage`の追記専用制約を維持する。
- Repositoryはflushまでを行い、commitはUoWが行う。未commitの正常終了（早期リターン含む）と例外終了の双方で変更を残さない。
- flush前の事前読み込み（SELECT）で判定した古い入力Version・対象不存在と、
  flush中の同時更新やDB制約違反による失敗を区別する。
  前者の判定だけで無関係の書き込みまで取り消さない。SELECT自体のDBエラーは別途失敗として扱う。

### 1-2. ORMの保存経路に統一する

第一候補は、既存の`to_orm()` / `from_orm()`を維持し、更新に`merge(load=True)`と`flush()`、
削除に読み込んだORMオブジェクトへの`AsyncSession.delete()`と`flush()`を使う方法とする。
新しい汎用マッパーインターフェースを増やす前に、後述の親子テストでこの方式を確認する。

- Versionを持つORMモデルに`version_id_col`を設定する。
  初期Versionは0を維持し、`version_id_generator=False`としてRepositoryが更新成功ごとに親集約のVersionを1増やす（`managed_parent.version = current_version + 1`）方針とする。
  検査用SQLはORMに任せ、直接UPDATEによる独自の競合判定を除去する。
- 渡された集約のVersionと読み込んだ行のVersionを更新・削除の事前読み込み時（`session.get()` または `merge(load=True)` 前）に照合する。
  古い入力Versionが渡された場合はflushを待たずに即座に`VERSION_CONFLICT`を返す。削除時も入力Versionを照合して古いVersionでの削除を拒否する。
  `merge()`には入力の元のVersionを渡し、merge後の管理対象オブジェクトでVersionを進める。
  読み込み後に別トランザクションが更新・削除した競合は、flush時の`StaleDataError`で検出する。
- 子だけの変更でも親のVersionを1進める。子要素のみの追加・変更・削除であっても、親ORMインスタンスのVersion属性を明示的にインクリメントしてdirty状態とし、flush時に親テーブルの楽観ロックUPDATE（`WHERE id = :id AND version = :old_version`）を必ず発行させる。変換・merge・Version設定の途中で意図しないautoflushが起きないよう`session.no_autoflush`ブロックを活用し、明示的なflushで親子をまとめて保存する。
- `update()`は集約全体のスナップショットを受け取る契約とする。
  空の子リストは全削除を意味し、未読み込みの子を空リストとして扱う部分更新には使わない。
- 子のIDを変換時に保持し、所有する子に必要な`save-update`、`merge`、`delete`、`delete-orphan`を設定する。
  別集約への参照には削除の連鎖を設定しない。
- 復元に必要な関連は、ORM側の読み込み設定（`lazy="selectin"`）または専用Repositoryの明示的なSELECT（`selectinload`）で先行して読み込む。
  `AsyncSession`での暗黙的同期I/O（`MissingGreenlet`）を防ぎ、同期的な`from_orm()`が暗黙にDBへアクセスしない設計を徹底する。
- flush中の`StaleDataError`はrollback後に必要な存在確認を行い、対象がなければ`NOT_FOUND`、
  対象があれば`VERSION_CONFLICT`に対応させる。失敗したSessionのまま再問い合わせしない。
  この確認結果はrollback後の観測であり、その後も存在することを保証するものではない。
- flush失敗時（`StaleDataError`や`IntegrityError`等）は同じトランザクションの書き込みを全て取り消す（`rollback()`）。
  UoWに失敗状態（`_is_failed = True`など）を記録し、同一スコープ内での後続`commit()`呼び出しを即座に`Err(RepositoryError)`で拒否する。
  再試行は新しいUoWスコープで行う。rollbackによる変更の破棄と失敗状態の管理を、専用Repositoryでも同じ契約にする。

ORMのVersion機能はflushする行に作用するため、親のVersionを進める処理は集約保存側に必要である。
関係を設定するだけで集約全体の競合検出まで自動化できるとは扱わない。
[公式資料: Version Counter](https://docs.sqlalchemy.org/en/20/orm/versioning.html)、
[merge](https://docs.sqlalchemy.org/en/20/orm/session_state_management.html#merging)、
[Cascade](https://docs.sqlalchemy.org/en/20/orm/cascades.html)、
[AsyncSessionの暗黙I/O](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#preventing-implicit-io-when-using-asyncsession)、
[flush失敗後の処理](https://docs.sqlalchemy.org/en/20/orm/session_basics.html#flushing)

### 1-3. 同じUoWから専用Repositoryを取得する

- UoWの構築時に「RepositoryのPort型 → 現在のSessionから実装を作る関数」の対応を渡す。
  登録は[`src/app/container.py`](../../src/app/container.py)などの組み立て箇所に置き、Sessionを作る責務はUoWに残す。
- 既存の`GetRepository(Entity, IdType)`は維持する。専用Portを受け取り、そのPort型を返す
  `GetCustomRepository(PortType)`を[IUnitOfWork](../../src/app/contracts/ports/unit_of_work.py)と[SQLAlchemyUnitOfWork](../../src/app/infrastructure/unit_of_work.py)に追加する。名称は既存APIとの整合を取る。
  専用メソッドも呼べる型にし、UseCaseで具象Repositoryや`AsyncSession`への依存・castを要求しない。
- 専用Repositoryは同じUoW内で再利用し、スコープ終了時に破棄する。
  未登録Portは黙ってGenericRepositoryに置き換えず、設定不足として明示的に失敗させる。
- CRUDのためだけの専用Repositoryは増やさない。専用の問い合わせや親子の読み込み制御が必要な場合に使う。

完了条件は、汎用と専用Repositoryを同時に使う処理で、成功時に両方がcommitされ、
未commit・例外・flush失敗時には両方が残らないこと。スコープ外の取得は拒否する。

### 1-4. 親子集約で実証する

テスト専用の「注文と明細」に相当する最小モデルを用意する。商品・決済などの業務機能は作らない。
テスト用のORM metadataとマッピング登録は本番の一覧から分離し、Alembicへの混入を防ぐ。

- 親と子を新規保存し、別Sessionで復元できる。
- 同一の保存で子の追加・属性変更・削除を行え、既存の子IDが維持される。空リストも扱える。
- 親の削除で所有する子だけが消え、他の集約は消えない。
- 古いVersionからの更新・削除、および子だけを変更する2つの更新が競合する。
  負けた側の子の追加・変更・削除が残らない。
- 子の制約違反で親・兄弟・同じUoWで先に保存した別集約までrollbackされる。
- UoWを閉じた後も、復元済みの集約をDBアクセスなしで参照できる。

これで`merge()`方式の成立を確認する。成立しない具体的なケースがある場合だけ、
その集約の専用Repositoryで管理中のORMオブジェクトへ明示的に状態を反映する。
対応に必要な差分と理由を記録し、全集約向けの新たな抽象化には直ちに広げない。

## 2. 登録から動作確認までの手順を一本化する

### 2-1. 重複した登録を減らす

- ORMモデルの読み込み元を[`src/app/infrastructure/orm_models/__init__.py`](../../src/app/infrastructure/orm_models/__init__.py)にそろえ、
  Alembicはそのパッケージを読み込む。`env.py`に個々のモデル名を追記する作業をなくす。
- マッパーは既存の`init_orm_mappings()`、Handlerは既存の`_HANDLER_TYPES`を正本とする。
  同じ登録の再初期化は許容し、異なるマッピングによる上書きや重複Handlerは検出する。
- API router、Bot Cog、LINE、Workerの接続はそれぞれの入口で明示する。
  追加する機能が使う入口だけを接続し、全入口の実装を要求しない。

### 2-2. 追加ガイドを正本として用意する

`docs/development/ADDING_FEATURE.md`を追加し、README・ARCHITECTURE・ドメイン実装ガイドからリンクする。
既存文書の追加手順はこのガイドを参照し、同じ手順を複数箇所で保守しない。

ガイドには、既存のTeam機能を追える実ファイルの対応表と、次の順序を載せる。

1. 集約境界、不変条件、状態遷移、永続化の要否を決める。
2. Entity・Value Object・ドメインテストを作る。
3. ORM・マッパーを作り、読み込みとマッピングを登録する。専用Repositoryが必要ならUoWへ登録する。
4. UseCase・Handlerを作り、Handler一覧へ登録する。
5. 必要な入口へ接続し、入口からHandlerまで到達するテストを書く。
6. スキーマ変更があれば使い捨てDBでmigrationを生成・目視確認し、適用と復元を確認する。
7. ドメイン・保存・UseCase・入口の検証、Ruff、Pyrightを実行する。

各段階に「編集先」「登録先」「完了を確認するテスト」を示す。migrationの自動生成結果は
レビューが必要であること、`create_all()`によるテストだけではmigrationを検証できないことも明記する。
[Alembic公式: 自動生成の範囲と限界](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)

### 2-3. 登録漏れをテストで検出する

- アプリ初期化とAlembicのモデル読み込みについて、別プロセスで必要なテーブルがmetadataへ入ることを確認する。
  `tests/conftest.py`の先行importによって漏れが隠れないようにする。
- 公開集約のうち永続化対象にマッピングがあり、必要な型にVersion設定があることを確認する。
- テスト内だけで所定の集約・Handlerモジュールを列挙し、公開一覧・登録一覧との不一致を検出する。
  登録済み一覧だけを検査して「一覧からの脱落」を見逃さないようにする。
  永続化しない集約などの例外は、理由付きで明示する。
- 起動時の重複・不正登録の検出と、代表的な入口からのdispatchを検証する。
  入口の選択そのものは業務判断なので、機械的に全接続を要求しない。

## 3. 新しい集約の確認漏れを見つけやすくする

共通ケースを小さなテストヘルパーとfixtureで提供し、既存4集約へ適用して使い方を示す。
ヘルパーはassertを共有する範囲にとどめ、独自のテストフレームワークは作らない。

| 確認対象 | 必須の検証 | 集約ごとに用意するもの |
| --- | --- | --- |
| 同一性 | 同じ型・同じIDなら属性やVersionが違っても同一。別ID・別の具象型とは異なる | IDと属性を変えた比較用の集約 |
| hashと可変性 | 可変集約のhashは禁止。不変集約は等価性とhashが一致。外部から不変条件を崩せない | 可変・不変の方針、外部に返す値の確認 |
| 状態遷移 | 許可操作が期待状態になり、拒否操作はエラーになって元の状態を保つ | 許可・拒否の遷移表と具体例 |
| 復元 | ID・Version・監査日時・業務属性・子のIDと属性が維持される | 永続化される状態を列挙する比較関数 |
| 復元時の不正状態 | 不正な値や属性の組み合わせを拒否し、黙って初期値や新IDに置き換えない | 現実に禁止している不変条件の反例 |
| 保存 | 別Sessionでの再読み込み、競合、rollback、追記専用などの制約 | 保存方式に応じたケース |

復元の一致をEntity同士の`==`だけで判定しない。状態遷移テストは実装の分岐を写すのではなく、
業務上の許可・拒否を期待値として記述する。生成時だけのルールを過去データの復元に誤適用しない。

公開集約の一覧と共通ケースの対象一覧を照合し、新しい集約にケースがなければCIを失敗させる。
ただし、ケースの存在だけで業務ルールの網羅性が保証されるとはしない。
遷移を持たない集約などは適用外の理由を記録し、レビューでは遷移表と実際の検証内容を確認する。

## 実装順序と完了条件

| 順序 | 主な変更対象 | この段階の完了条件 |
| --- | --- | --- |
| 1 | `tests/infrastructure/`、既存集約テスト | 保存契約と既存挙動が固定され、変更前との差を判定できる |
| 2 | Repository、ORMモデル、UoW、Port、[`src/app/container.py`](../../src/app/container.py) | ORM方式で既存集約と親子モデルが保存でき、汎用・専用Repositoryの原子性を確認できる |
| 3 | ORM読み込み、Alembic環境、登録のテスト | 二重登録を減らし、未登録モデル・Handler・不正登録を検出できる |
| 4 | ドメイン・復元の共通テストと既存4集約 | 新しい集約のテスト対象への追加漏れを検出し、既存の不変条件を維持できる |
| 5 | 追加ガイド、既存文書、CI | ガイドをたどって登録・migration・入口の検証を再現でき、必要なチェックがCIで動く |

ORMのVersion設定変更自体は既存列を利用する想定なので、不要なmigrationは作らない。
DB制約の追加が必要と判明した場合だけ前方migrationを作り、適用済みmigrationは書き換えない。

実装時はまず対象テストを実行し、最後に現行CIと同じチェックを実行する。

```bash
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen pyright
uv run --frozen pytest --cov --cov-report=term-missing
```

DB検証はSQLiteに加えてPostgreSQLでも親子保存・Version競合・一意制約・rollbackを確認する。
SQLiteの別SessionテストだけでPostgreSQLの同時実行まで保証したとは扱わない。
SQLiteでは子の外部キー制約を有効化し、同時実行テストは独立した接続を使う。
PostgreSQLの検証をCIへ追加し、環境がない場合のskipを完了扱いにしない。

migrationを変更する場合は使い捨てDBで、空DBからhead、既存データを持つ旧headから新head、
今回追加分のdowngradeと再upgradeを確認する。metadataとの差分確認には`alembic check`を使い、
自動検出できない制約は個別に検証する。既存履歴の問題を見つけた場合は原因と必要な追加範囲を報告する。

実装・テスト・ガイドは原則1PR。保存基盤と別件の移行不具合などが重なり、レビュー可能な範囲を
超えると判明した場合に限り分割を提案する。Pushする場合は1PR1コミットとし、修正はamendで反映する。
