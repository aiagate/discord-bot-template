import logging
import os
import sys
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv
from injector import Injector

from app.application.mediator import ApplicationMediator
from app.infrastructure.database import init_db
from app.presentation.bot.cogs.dm_response_cog import DirectMessageResponseCog
from app.presentation.bot.cogs.memberships_cog import MembershipsCog
from app.presentation.bot.cogs.teams_cog import TeamsCog
from app.presentation.bot.cogs.users_cog import UsersCog


class MyBot(commands.Bot):
    injector: Injector
    mediator: ApplicationMediator

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
        from app import container

        db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./bot.db")
        init_db(db_url, echo=True)

        # Initialize Mediator with dependency injection container
        injector = Injector([container.configure])
        self.injector = injector
        self.mediator = injector.get(ApplicationMediator)

    async def load_cogs(self) -> None:
        mediator = self.mediator
        await self.add_cog(TeamsCog(self, mediator))
        await self.add_cog(UsersCog(self, mediator))
        await self.add_cog(MembershipsCog(self, mediator))
        await self.add_cog(DirectMessageResponseCog(self, mediator))
        collective_config = os.getenv("COLLECTIVE_CONFIG")
        if collective_config:
            from app.application.collective_settings import BotCollectiveConfig
            from app.presentation.bot.cogs.collective_cog import CollectiveCog

            config = BotCollectiveConfig.model_validate_json(
                Path(collective_config).read_text()
            )
            config.root = config.root.expanduser().resolve()
            config.agy_skill = config.agy_skill.expanduser().resolve()
            await self.add_cog(CollectiveCog(self, config))


def load_environment() -> None:
    """Load environment variables from .env files."""
    # プロジェクトルートディレクトリを取得
    # app/presentation/bot/__main__.py -> app/presentation/bot/ -> app/presentation/ -> app/ -> src/ -> root
    root_dir = Path(__file__).parent.parent.parent.parent.parent

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
        level=logging.INFO,
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
