# tests

このフォルダにはテストコードが含まれています。

- `domain/`: ドメインモデル（集約、値オブジェクト）の単体テスト。
- `usecases/`: ユースケース（アプリケーションロジック）のテスト。
- `infrastructure/`: データベース、リポジトリ、外部サービス連携の統合テスト。
- `presentation/`: 各エントリポイント（API, Bot, Worker）のテスト。
- `conftest.py`: pytestの共通フィクスチャ定義。
