import logging
import os
import sys
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv
from injector import Injector

from app.bot.cogs.dm_response_cog import DirectMessageResponseCog
from app.bot.cogs.memberships_cog import MembershipsCog
from app.bot.cogs.teams_cog import TeamsCog
from app.bot.cogs.users_cog import UsersCog


class MyBot(commands.Bot):
    injector: Injector

    def __init__(self, command_prefix: str = "!") -> None:
        super().__init__(
            intents=discord.Intents.all(),
            command_prefix=command_prefix,
        )

    async def setup_hook(self) -> None:
        await self._init_database()
        await self.load_cogs()

    async def _init_database(self) -> None:
        """Initialize database connection and create tables."""

        from flow_med import Mediator

        from app import container
        from app.infrastructure.database import init_db

        db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./bot.db")
        init_db(db_url, echo=True)

        # Initialize Mediator with dependency injection container
        injector = Injector([container.configure])
        self.injector = injector
        Mediator.initialize(injector)

    async def load_cogs(self) -> None:
        await self.add_cog(TeamsCog(self))
        await self.add_cog(UsersCog(self))
        await self.add_cog(MembershipsCog(self))
        await self.add_cog(DirectMessageResponseCog(self))


def load_environment() -> None:
    """Load environment variables from .env files."""
    # プロジェクトルートディレクトリを取得
    # app/bot/__main__.py -> app/bot/ -> app/ -> root
    root_dir = Path(__file__).parent.parent.parent

    # .env.local が存在すれば優先的に読み込む（開発環境用）
    env_local = root_dir / ".env.local"
    if env_local.exists():
        load_dotenv(env_local)
        return

    # .env ファイルを読み込む（本番環境用）
    env_file = root_dir / ".env"
    if env_file.exists():
        load_dotenv(env_file)


def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format=(
            "[ %(levelname)-8s] %(asctime)s | %(name)-16s %(funcName)-16s| %(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 環境変数を読み込む
    load_environment()

    # Bot トークンを取得
    token = os.getenv("DISCORD_BOT_TOKEN")
    if token is None:
        logging.error("DISCORD_BOT_TOKEN environment variable is not set")
        logging.error("Please set it in .env.local or .env file")
        sys.exit(1)

    bot = MyBot()
    bot.run(token)


if __name__ == "__main__":
    main()
