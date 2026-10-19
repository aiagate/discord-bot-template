"""Shared environment loading for every process entry point.

すべてのエントリポイント（Bot / API / Worker / LINE / Alembic）がこの
モジュールを介して環境変数を読み込む。

優先順位（高い方から）:

1. 既に設定されたプロセス環境変数（外部提供分は絶対に上書きしない）
2. プロジェクトルートの ``.env.local``（開発環境用）
3. プロジェクトルートの ``.env``（フォールバック）

読み込みは「明示的に解決したプロジェクトルート」のみを対象とし、
現在の作業ディレクトリやその親ディレクトリは探索しない。
"""

from pathlib import Path

from dotenv import load_dotenv

__all__ = ["load_environment", "resolve_project_root"]

_ENV_FILE_NAME = ".env"
_ENV_LOCAL_FILE_NAME = ".env.local"


def resolve_project_root() -> Path:
    """Return the explicitly resolved project root directory.

    Returns:
        Path: ``src/app/environment.py`` から導くプロジェクトルート。
        カレントディレクトリには依存しない。
    """
    # src/app/environment.py -> src/app -> src -> project root
    return Path(__file__).resolve().parents[2]


def load_environment(root: Path | None = None) -> None:
    """Load ``.env.local`` and ``.env`` from the given root directory.

    ``.env.local`` を先に読み、続いて ``.env`` を ``override=False`` で
    読み込むことで「プロセス環境 > .env.local > .env」の優先順位を実現する。
    存在しないファイルは無視される。

    Args:
        root: env ファイルを読み込むディレクトリ。
            ``None`` の場合は :func:`resolve_project_root` を使用する。
    """
    project_root = resolve_project_root() if root is None else root

    # .env.local を先に読み、その後 .env で欠落キーのみを補う。
    local_env = project_root / _ENV_LOCAL_FILE_NAME
    if local_env.is_file():
        load_dotenv(local_env, override=False)

    base_env = project_root / _ENV_FILE_NAME
    if base_env.is_file():
        load_dotenv(base_env, override=False)
