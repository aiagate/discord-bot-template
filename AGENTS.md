# 開発ガイドライン

## 目的から変更を決める

`docs/purpose.md` → `docs/use-cases.md` → `docs/architecture.md` →
`docs/acceptance.md`の順に確認する。ハイレベルユースケースにはHowを入れない。
変更する挙動が、どの目的とユースケースを実現するのかを説明する。
必要な要素は「無いと何が困るか」で点検する。

旧Discord Botテンプレートとの後方互換性は不要。
モデルのターン終了を支援の達成と同一視しない。人間の新しい発言がなくても、
保存された目的と再確認条件から支援を進められることを維持する。

## 境界

- 入口 → ユースケース → 契約。外部アダプタも契約に依存する。
- 共有型は`src/app/contracts/messages`、外部境界は`src/app/contracts/ports`。
- ユースケースからモデルSDKやDiscordを直接呼ばない。
- 判断と実行、表現、配信の責務を分ける。表現の失敗で作業の保存を取り消さない。
- 記憶の解釈と原資料を分け、出典・訂正・結果不明の試行を追えるようにする。

## 品質と依存管理

uvのみを使う。依存追加・削除は`uv add`・`uv remove`で行い、pipは使わない。
ライブラリの機能を変更するときは最新の公式ドキュメントを確認する。
型ヒント、公開APIのDocstring、88文字以内の行を守る。

```bash
uv run --frozen ruff format .
uv run --frozen ruff check .
uv run --frozen pyright
uv run --frozen pytest
```

非同期テストは`pytest.mark.anyio`を使い、`anyio_backend`でasyncioを選ぶ。
新機能とバグ修正には、目的・失敗・中断・再開を確認するテストを付ける。
anyioのmarkを認識しない環境では`PYTEST_DISABLE_PLUGIN_AUTOLOAD=''`を付ける。
外部モデルのテストダブルと、実サービスで確認した結果を区別して報告する。

## 運用と変更の公開

起動・認証・データ配置・停止は`docs/operations.md`を参照する。
一データディレクトリにつき実行プロセスは一つ。個人設定と実行データをGitに含めない。
元の作業場所や稼働中プロセスをworktreeの変更に巻き込まない。

コミット前に`git status`を確認する。1PR1コミットとし、追加修正はamendする。
リモートへの公開は`git push --force-with-lease`を使う。
ユーザー報告に基づく変更には`Reported-by`、Issue関連なら`Github-Issue`のtrailerを付ける。
共同作者trailerや、変更の作成に使ったツールへの言及をコミット・PRに含めない。

文書やコメントなどの永続的な文章はagy-workに添削を依頼する。
ルートの`AGENTS.override.md`がある場合は後から読み、衝突する項目のみ上書きする。
上書きファイルはGit管理外とし、明示的なユーザー指示は常に優先する。
