# Gemini Code Assistant Context

常に日本語でやり取りを実施してください
This document provides a comprehensive overview of the `discord-bot-template` project to guide the Gemini code assistant.

## Project Overview

This is a Python project template for creating Discord bots. It is built upon a clean architecture, emphasizing separation of concerns, testability, and maintainability.

The project uses modern Python tools and practices:

- **Package Management**: `uv`
- **Discord API**: `discord.py` library, using the Cogs feature for modular commands.
- **Architecture**: A clean architecture with distinct layers for Domain, Application (Use Cases), and Infrastructure.
- **Dependency Injection**: `injector` library is used to manage dependencies and promote loose coupling.
- **Database**:
  - **ORM**: `SQLModel` for type-safe database interactions.
  - **Migrations**: `Alembic` for managing database schema evolution.
  - **Async Support**: `aiosqlite` for asynchronous database operations.
- **Code Quality**:
  - **Linting & Formatting**: `Ruff`
  - **Type Checking**: `Pyright` in `strict` mode.
  - **Pre-commit Hooks**: Configured in `.pre-commit-config.yaml` to enforce standards before committing.
- **Testing**:
  - **Framework**: `pytest` with `pytest-asyncio` for testing async code.
  - **Coverage**: `pytest-cov` for code coverage analysis.

### Directory Structure

The structure enforces the clean architecture principles:

- `app/`: The main application source code.
  - `__main__.py`: The entry point for the bot.
  - `cogs/`: Discord command modules (Cogs).
  - `domain/`: Core business logic and data structures (Aggregates).
  - `usecases/`: Application-specific business rules.
  - `infrastructure/`: Handles external concerns like database access (Repositories, ORM models) and DI configuration.
  - `container.py`: Dependency Injection container setup.
- `alembic/`: Database migration scripts.
- `tests/`: `pytest` tests for the application.

## Building and Running

All commands should be executed using `uv run`. The project dependencies are managed with `uv`.

### 1. Setup

First-time setup requires creating a virtual environment, installing dependencies, and setting up the database.

1. **Create virtual environment and install dependencies**:

    ```bash
    uv venv
    uv sync
    ```

2. **Install pre-commit hooks**:

    ```bash
    uv run pre-commit install
    ```

3. **Configure environment variables**:
    Copy `.env.example` to `.env.local` and add your `DISCORD_BOT_TOKEN`.

    ```bash
    cp .env.example .env.local
    ```

4. **Run database migrations**:

    ```bash
    uv run alembic upgrade head
    ```

### 2. Running the Bot

To start the Discord bot:

```bash
uv run -m app
```

### 3. Running Tests

Execute the test suite using `pytest`:

```bash
uv run pytest
```

To get a coverage report:

```bash
uv run pytest --cov=app
```

## Development Conventions

- **Architecture**: Adhere to the clean architecture pattern. Business logic should be independent of the framework and infrastructure.
  - Presentation Layer (`cogs`) depends on Application Layer (`usecases`).
  - Application Layer (`usecases`) depends on Domain Layer (`domain`).
  - Infrastructure Layer (`infrastructure`) implements interfaces defined in higher layers (e.g., Repository interfaces).
- **Database**:
  - Define domain models in `app/domain/aggregates`.
  - Define ORM models in `app/infrastructure/orm_models` and keep them separate from domain models.
  - When the database schema changes, generate a new migration: `uv run alembic revision --autogenerate -m "Your migration message"`
- **Code Quality**: All code should pass `Ruff` and `Pyright` checks. Use the pre-commit hooks to ensure this automatically.
  - **Format code**: `uv run ruff format .`
  - **Lint code**: `uv run ruff check . --fix`
  - **Type check**: `uv run pyright`
- **Commits**: Follow conventional commit standards if possible (though not explicitly stated, it's good practice).
- **Dependencies**: Manage all Python dependencies in `pyproject.toml`.
