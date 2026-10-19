import logging
import os
import sys

from discord.ext import commands
from injector import Injector

from app.application.mediator import ApplicationMediator
from app.environment import load_environment
from app.infrastructure.database import init_db
from app.presentation.bot.cogs.dm_response_cog import DirectMessageResponseCog
from app.presentation.bot.cogs.memberships_cog import MembershipsCog
from app.presentation.bot.cogs.teams_cog import TeamsCog
from app.presentation.bot.cogs.users_cog import UsersCog
from app.presentation.bot.intents import create_bot_intents


class MyBot(commands.Bot):
    injector: Injector
    mediator: ApplicationMediator

    def __init__(self, command_prefix: str = "!") -> None:
        super().__init__(
            intents=create_bot_intents(),
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
