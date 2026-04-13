
# 外部API連携パターン

このドキュメントでは、外部APIとの連携機能を実装する際のアーキテクチャパターンについて解説します。
プロジェクトの設計思想である **Clean Architecture** に基づき、ビジネスロジックが特定の外部サービスの仕様に依存しないように設計します。

## 設計方針：3層分離

外部API連携は以下の3つの層に分離して実装します。

| 層 (Layer) | 役割 | 格納ディレクトリ例 | 実装内容 |
| :--- | :--- | :--- | :--- |
| **Domain** | **抽象化 (Interface)** | `app/domain/interfaces/` <br> または `app/domain/services/` | 「何ができるか」という契約（インターフェース）のみを定義します。外部APIの都合（URLや認証方式など）は含めません。 |
| **Infrastructure** | **実装 (Implementation)** | `app/infrastructure/external/` <br> または `app/infrastructure/services/` | 実際の外部APIを呼び出すコード (`httpx` や `requests` を利用) を書きます。Domain層のインターフェースを実装します。 |
| **UseCase** | **利用 (Consumer)** | `app/usecases/...` | インターフェースを通して機能を利用します。具体的なクラス名（実装）は知らずに利用します。 |

---

## 実装例

映画情報を外部APIから取得する機能を例に説明します。

### 1. Domain層: インターフェース定義

まず、「何が欲しいのか」を定義します。ここでは HTTPクライアントの実装などの詳細は隠蔽します。

**ファイル:** `app/domain/interfaces/movie_service.py`

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from flow_res import Result

@dataclass
class MovieData:
    title: str
    year: int

class IMovieService(ABC):
    @abstractmethod
    async def get_movie_details(self, movie_id: str) -> Result[MovieData, str]:
        """映画の詳細情報を取得する抽象メソッド"""
        pass
```

### 2. Infrastructure層: 実装

次に、実際に外部APIを叩くコードを書きます。ここでAPIキーやエンドポイントのURLなどの詳細を扱います。
`IMovieService` を継承して実装します。

**ファイル:** `app/infrastructure/services/tmdb_movie_service.py`

```python
import httpx
from app.domain.interfaces.movie_service import IMovieService, MovieData
from flow_res import Result, Ok, Err

class TmdbMovieService(IMovieService):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.themoviedb.org/3"

    async def get_movie_details(self, movie_id: str) -> Result[MovieData, str]:
        # ここで具体的な外部API通信を行う
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/movie/{movie_id}",
                params={"api_key": self.api_key}
            )

        if response.status_code == 200:
            data = response.json()
            # 外部APIのレスポンスをDomainの型に変換する（腐敗防止層の役割）
            return Ok(MovieData(title=data["title"], year=int(data["release_date"][:4])))
        else:
            return Err(f"API Error: {response.status_code}")
```

### 3. UseCase層: インターフェースの利用

UseCaseは具体的なクラス（`TmdbMovieService`）を知らず、`IMovieService` インターフェースを通して機能を利用します。

**ファイル:** `app/usecases/get_movie_usecase.py`

```python
from app.domain.interfaces.movie_service import IMovieService

class GetMovieUseCase:
    def __init__(self, movie_service: IMovieService):
        # 具象クラスではなく、インターフェースを受け取る（コンストラクタ注入）
        self.movie_service = movie_service

    async def execute(self, movie_id: str):
        # 外部APIの実装が変わっても、このコードは変更不要
        return await self.movie_service.get_movie_details(movie_id)
```

### 4. DIコンテナ設定

アプリケーション起動時に、「`IMovieService` が必要なら `TmdbMovieService` を渡す」という設定を行います。

**ファイル:** `app/container.py`

```python
from app.domain.interfaces.movie_service import IMovieService
from app.infrastructure.services.tmdb_movie_service import TmdbMovieService

class ServiceModule(injector.Module):
    @injector.provider
    def provide_movie_service(self) -> IMovieService:
        # ここで具体的な実装を返す
        # 環境変数からAPIキーを取得するのが一般的
        return TmdbMovieService(api_key="your_api_key")

def configure(binder: injector.Binder) -> None:
    # ... 他の設定 ...
    binder.install(ServiceModule())
```

---

## このパターンのメリット

1. **テスト容易性**: UseCaseのテスト時に、実際のAPIを叩かずに `MockMovieService` などを注入することで簡単にテストができます。
2. **保守性**: 外部APIの仕様変更（例えば v3 から v4 への移行や、別のプロバイダーへの変更）が発生しても、影響範囲を Infrastructure 層のみに閉じ込めることができます。Domain層やUseCase層のコード修正は不要です。
3. **関心の分離**: ビジネスロジックが技術的詳細（HTTP通信、認証など）から分離され、コードが読みやすくなります。
