import logging
import os
import sys
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv
from injector import Injector

from app.bot.cogs import chat_cog, memberships_cog, teams_cog, users_cog


class MyBot(commands.Bot):
    def __init__(self, command_prefix: str = "!") -> None:
        super().__init__(
            intents=discord.Intents.all(),
            command_prefix=command_prefix,
        )

    async def setup_hook(self) -> None:
        injector = await self._setup_dependencies()
        await self.load_cogs()

        # Initialize AI Agent (Caching etc.)
        from app.domain.interfaces.ai_service import IAIService

        ai_service = injector.get(IAIService)
        await ai_service.initialize_ai_agent()

        self.bg_tasks = set()

        # Initialize Event Bus
        from app.bot.cogs.brain_cog import BrainCog
        from app.domain.interfaces.event_bus import IEventBus

        event_bus = injector.get(IEventBus)

        # Start Event Bus task
        t_bus = self.loop.create_task(event_bus.start())
        self.bg_tasks.add(t_bus)
        t_bus.add_done_callback(self.bg_tasks.discard)

        # Load BrainCog with EventBus
        await self.add_cog(BrainCog(self, event_bus))

    async def _setup_dependencies(self) -> "Injector":
        """Initialize database and dependencies."""
        from injector import Injector

        from app import container
        from app.core.mediator import Mediator
        from app.infrastructure.database import init_db

        db_url = os.getenv("DATABASE_URL")
        # Ensure we have a DB URL, can fallback to sqlite for local dev if not strictly postgres for bot part,
        # but implementation plan requires postgres.
        if db_url is None:
            # Fallback or error? Plan says "Requires running Postgres".
            # Assuming environment is set up.
            raise ValueError("DATABASE_URL environment variable is not set")

        init_db(db_url, echo=True)

        # Initialize Mediator with dependency injection container
        injector = Injector([container.configure])
        Mediator.initialize(injector)

        return injector

    async def load_cogs(self) -> None:
        await self.load_extension(chat_cog.__name__)
        await self.load_extension(teams_cog.__name__)
        await self.load_extension(users_cog.__name__)
        await self.load_extension(memberships_cog.__name__)


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
