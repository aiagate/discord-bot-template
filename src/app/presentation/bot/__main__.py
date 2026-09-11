import json
import logging
import os
import sys
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv
from injector import Injector

from app.application.mediator import ApplicationMediator
from app.contracts.messages.character_prompt import DiscordMaster
from app.contracts.ports import (
    ICharacterResponseGenerator,
    ISpeechPublisher,
    ITimesEpisodeStore,
    ITimesPublisher,
)
from app.domain.characters import CharacterRoster
from app.infrastructure.database import init_db
from app.presentation.bot.cogs.memberships_cog import MembershipsCog
from app.presentation.bot.cogs.message_listener_cog import (
    DiscordMessageListenerCog,
    DiscordResponseDestination,
    DiscordTimesDestination,
)
from app.presentation.bot.cogs.teams_cog import TeamsCog
from app.presentation.bot.cogs.users_cog import UsersCog

logger = logging.getLogger(__name__)
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
PROJECT_ROOT = Path(__file__).resolve().parents[4]
LOG_PATH = PROJECT_ROOT / "log"
LOG_FILENAME = "discord_bot_main.log"
LOG_FORMAT = "[ %(levelname)-8s] %(asctime)s | %(name)-16s %(funcName)-16s| %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
WEBHOOK_URLS_ENV = "DISCORD_CHARACTER_WEBHOOK_URLS_JSON"
TIMES_WEBHOOK_URL_ENV = "DISCORD_CHARACTER_TIMES_WEBHOOK_URL"


def _load_character_webhook_urls() -> tuple[str, ...]:
    """Read the configured JSON webhook URL list."""
    configured = os.getenv(WEBHOOK_URLS_ENV, "").strip()
    if not configured:
        return ()
    try:
        values = json.loads(configured)
    except json.JSONDecodeError as error:
        raise ValueError(f"{WEBHOOK_URLS_ENV} must contain a JSON array.") from error
    if not isinstance(values, list):
        raise ValueError(f"{WEBHOOK_URLS_ENV} must contain a JSON array.")
    urls = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Character webhook URLs must be non-empty strings.")
        urls.append(value.strip())
    if len(urls) != len(set(urls)):
        raise ValueError("Character webhook URLs must be unique.")
    return tuple(urls)


class MyBot(commands.Bot):
    injector: Injector
    mediator: ApplicationMediator

    def __init__(self, command_prefix: str = "!") -> None:
        super().__init__(
            intents=discord.Intents.all(),
            command_prefix=command_prefix,
        )
        self._character_response_generator: ICharacterResponseGenerator | None = None
        self._times_destination: DiscordTimesDestination | None = None
        self._times_store: ITimesEpisodeStore | None = None

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
        injector.binder.bind(discord.Client, to=self)
        self.injector = injector
        self.mediator = injector.get(ApplicationMediator)

    async def load_cogs(self) -> None:
        mediator = self.mediator
        destinations = await self._configure_characters()
        await self.add_cog(TeamsCog(self, mediator))
        await self.add_cog(UsersCog(self, mediator))
        await self.add_cog(MembershipsCog(self, mediator))
        await self.add_cog(
            DiscordMessageListenerCog(
                self,
                mediator,
                ai_response_destinations=destinations,
                times_destination=self._times_destination,
                times_store=self._times_store,
            )
        )

    async def _configure_characters(self) -> tuple[DiscordResponseDestination, ...]:
        """Initialize optional AI resources after the ordinary application is ready."""
        gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
        character_guild_id = os.getenv("DISCORD_CHARACTER_GUILD_ID", "").strip()
        stage = "settings"
        try:
            webhook_urls = _load_character_webhook_urls()
            if not all((gemini_api_key, webhook_urls, character_guild_id)):
                logger.info(
                    "AI responses disabled: Gemini key, webhook URL list and guild ID "
                    "are all required."
                )
                return ()
            if (
                not character_guild_id.isascii()
                or not character_guild_id.isdecimal()
                or len(character_guild_id) > 20
            ):
                raise ValueError("Character guild ID must be a Discord snowflake.")
            from app.application.character_settings import load_character_settings

            master = DiscordMaster(
                os.getenv("DISCORD_CHARACTER_MASTER_USER_ID", "").strip() or None
            )
            override = os.getenv("CHARACTER_DEFINITIONS_PATH", "").strip()
            override_path = (
                Path(override)
                if override
                else PROJECT_ROOT / "characters.override.json"
            )
            if not override_path.is_absolute():
                override_path = PROJECT_ROOT / override_path
            character_settings = load_character_settings(
                override_path if override or override_path.exists() else None
            )
            roster = character_settings.roster
            stage = "Gemini initialization"
            from google import genai
            from google.genai import types

            from app.infrastructure import database
            from app.infrastructure.discord import (
                DiscordWebhookSpeechPublisher,
                DiscordWebhookSpeechPublisherRouter,
            )
            from app.infrastructure.gemini import GeminiCharacterResponseGenerator
            from app.infrastructure.queries.speech_delivery_store import (
                SQLAlchemySpeechDeliveryStore,
            )

            if database._session_factory is None:
                raise RuntimeError("Database must be initialized before AI resources.")
            generator = GeminiCharacterResponseGenerator(
                client=genai.Client(
                    api_key=gemini_api_key,
                    http_options=types.HttpOptions(
                        timeout=20_000,
                        retry_options=types.HttpRetryOptions(
                            attempts=3, initial_delay=0.5, max_delay=2.0
                        ),
                    ),
                ),
                model=os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODEL,
                mcp_servers=character_settings.mcp_servers,
            )
            self._character_response_generator = generator
            stage = "webhook destination validation"
            store = SQLAlchemySpeechDeliveryStore(database._session_factory)
            publishers: dict[str, DiscordWebhookSpeechPublisher] = {}
            destinations: list[DiscordResponseDestination] = []
            for webhook_url in webhook_urls:
                publisher = DiscordWebhookSpeechPublisher(
                    webhook_url,
                    client=self,
                    store=store,
                    master=master,
                )
                scope = await publisher.initialize(character_guild_id)
                if scope.channel_id in publishers:
                    raise ValueError(
                        "Character webhooks must target different channels."
                    )
                publishers[scope.channel_id] = publisher
                destinations.append(
                    DiscordResponseDestination(
                        scope=scope,
                        webhook_id=publisher.webhook_id,
                        is_forum=publisher.is_forum,
                    )
                )
            router = DiscordWebhookSpeechPublisherRouter(publishers)
            stage = "delivery recovery"
            await router.recover_pending()
            self.injector.binder.bind(CharacterRoster, to=roster)
            self.injector.binder.bind(DiscordMaster, to=master)
            self.injector.binder.bind(ICharacterResponseGenerator, to=generator)
            self.injector.binder.bind(ISpeechPublisher, to=router)
            logger.info(
                "AI responses enabled for guild %s in %s webhook destinations",
                character_guild_id,
                len(destinations),
            )

            times_webhook_url = os.getenv(TIMES_WEBHOOK_URL_ENV, "").strip()
            self._times_destination = None
            self._times_store = None
            if times_webhook_url:
                times_stage = "Times destination validation"
                try:
                    from app.infrastructure.discord import DiscordWebhookTimesPublisher
                    from app.infrastructure.queries import SQLAlchemyTimesEpisodeStore

                    times_store = SQLAlchemyTimesEpisodeStore(database._session_factory)
                    times_publisher = DiscordWebhookTimesPublisher(
                        times_webhook_url,
                        client=self,
                        store=times_store,
                        roster=roster,
                        master=master,
                    )
                    character_channel_ids = {
                        dest.scope.channel_id for dest in destinations
                    }
                    times_scope = await times_publisher.initialize(
                        character_guild_id, character_channel_ids
                    )
                    times_stage = "Times delivery recovery"
                    await times_publisher.recover_pending()
                    self._times_destination = DiscordTimesDestination(
                        scope=times_scope,
                        webhook_id=times_publisher.webhook_id,
                    )
                    self._times_store = times_store
                    self.injector.binder.bind(ITimesPublisher, to=times_publisher)
                    self.injector.binder.bind(ITimesEpisodeStore, to=times_store)
                    logger.info(
                        "Times board enabled for guild %s at channel %s",
                        character_guild_id,
                        times_scope.channel_id,
                    )
                except Exception as error:
                    logger.error(
                        "Times board disabled during %s (%s)",
                        times_stage,
                        type(error).__name__,
                    )

            return tuple(destinations)
        except Exception as error:
            logger.error(
                "AI responses disabled during %s (%s)", stage, type(error).__name__
            )
            self._times_destination = None
            self._times_store = None
            if self._character_response_generator is not None:
                try:
                    await self._character_response_generator.aclose()
                except Exception:
                    logger.exception("Could not close disabled AI client")
                self._character_response_generator = None
            return ()

    async def close(self) -> None:
        """Close application resources before closing the Discord client."""
        try:
            await self.remove_cog("Discord Message Listener")
            if self._character_response_generator is not None:
                await self._character_response_generator.aclose()
        finally:
            await super().close()


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


def configure_logging(log_path: Path) -> logging.FileHandler:
    """Configure console and file logging for the application."""
    logging.basicConfig(
        level=logging.DEBUG,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
    )

    log_path = Path(log_path)
    log_path.mkdir(parents=True, exist_ok=True)
    filename = (log_path / LOG_FILENAME).resolve()
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    handler = next(
        (
            existing
            for existing in root_logger.handlers
            if isinstance(existing, logging.FileHandler)
            and Path(existing.baseFilename).resolve() == filename
        ),
        None,
    )
    if handler is None:
        handler = logging.FileHandler(filename=filename, encoding="utf-8")

    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
    if handler not in root_logger.handlers:
        root_logger.addHandler(handler)
    return handler


def main() -> None:
    configure_logging(LOG_PATH)

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
