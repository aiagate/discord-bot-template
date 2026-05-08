# API層 実装ガイドライン

本プロジェクトにおけるAPI層（FastAPIなど）の実装方針と設計思想についてまとめた資料です。
新しくAPIエンドポイントを実装する際は、本ガイドラインに従ってください。

## 1. アーキテクチャ上の位置づけ

API層（`src/app/presentation/api`）は、クリーンアーキテクチャにおける **「プレゼンテーション層 (Interface Adapters)」** に位置します。

* **役割**: HTTPリクエストを受け取り、適切な **Use Case** を呼び出し、結果をレスポンスとして返すこと。
* **禁止事項**: API層にビジネスロジックを書いてはいけません。複雑な処理が必要な場合は、必ず Use Case 層以上のロイヤーに実装してください。

### 依存関係

* [OK] `src/app/presentation/api` -> `src/app/usecases` (許可)
* [OK] `src/app/presentation/api` -> `src/app/mediator` (許可)
* [NG] `src/app/presentation/api` -> `src/app/domain` (Use Caseの戻り値としてのDTO参照は許容するが、直接Entityを操作しないこと)
* [NG] `src/app/presentation/api` -> `src/app/infrastructure` (データベース操作などは厳禁)

---

## 2. CommandとQueryの分離 (CQS原則)

本プロジェクトでは、**CQS (Command-Query Separation)** 原則を採用しています。
これにより、書き込み（副作用）と読み込み（参照）の責務を明確に分離します。

### Command (書き込み系: POST, PUT, DELETE)

* **目的**: システムの状態を変更すること。
* **戻り値**: 原則として **リソースのIDのみ** を返します。
  * [NG] 更新後の全データを返す（例: Userオブジェクト丸ごと）
  * [OK] 作成/更新されたUserのIDのみ返す（例: `{"id": "user_123"}`)
* **理由**:
  * 書き込み処理と読み込み処理を疎結合にするため。
  * パフォーマンス最適化（書き込み時に不要な読み込みコストを払わない）。

### Query (読み込み系: GET)

* **目的**: システムの状態を取得すること。
* **戻り値**: 画面表示に必要なデータを返します。
* **理由**: 副作用を持たないため、何度呼んでも安全です。

### 実装例

```python
# [NG] Bad Pattern: 更新処理がデータを返している
@router.post("/teams")
async def create_team(...) -> TeamResponse:
    team = await use_case.execute(...)
    return team  # 作成したチーム情報をそのまま返す

# [OK] Good Pattern: IDのみ返し、必要なら別途GETを呼ぶ
@router.post("/teams")
async def create_team(...) -> CreateTeamResponse:
    team_id = await Mediator.send_async(CreateTeamCommand(...))
    return CreateTeamResponse(id=team_id)
```

---

## 3. レスポンスの設計 (Response DTO)

APIのレスポンスは、必ず **Pydanticモデル (DTO)** でラップしてください。
たとえフィールドが1つだけであっても、プリミティブ型（`str`, `int`）を直接返却してはいけません。

### ルール

* 全てのレスポンスに対し、専用の `Response Model` を定義する。
* プリミティブ型をルートで返さない。

### 理由

1. **拡張性 (Extensibility)**:
    * 将来 `{"id": "...", "message": "Success"}` のようにフィールドを追加したくなった場合、プリミティブ型を返していると型変更（Breaking Change）になりますが、オブジェクトであればフィールド追加のみで済み、クライアントコードを壊しません。
2. **一貫性 (Consistency)**:
    * クライアントは常に「JSONオブジェクトが返ってくる」と期待してパース処理を書くことができます。
3. **ドキュメント化**:
    * Swagger UI (OpenAPI) 上でスキーマが定義され、APIの仕様が明確になります。

### 実装例

```python
# [NG] Bad Pattern: 文字列を直接返す
@router.post("/users")
async def create_user(...) -> str:
    return "user_123"

# [OK] Good Pattern: DTOでラップする
class CreateUserResponse(BaseModel):
    id: str

@router.post("/users")
async def create_user(...) -> CreateUserResponse:
    return CreateUserResponse(id="user_123")
```

---

## 4. エラーハンドリング

Use Case から返却される `Result` 型 (`Ok` / `Err`) をハンドリングし、適切な HTTP ステータスコードに変換してください。

* **Validation Error** -> 400 Bad Request
* **Not Found** -> 404 Not Found
* **Unexpected / System Error** -> 500 Internal Server Error

例外 (`try-except`) ではなく、`Result` 型の分岐で制御することを推奨します。
