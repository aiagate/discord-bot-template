"""Initialize portable collective state without connecting to Discord."""

import argparse
from pathlib import Path

from app.application.collective_settings import initialize_characters
from app.infrastructure.collective.workspace import atomic_write


def main() -> None:
    """Create missing identity and policy files without replacing existing state."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data"))
    args = parser.parse_args()
    root: Path = args.root.resolve()
    initialize_characters(root)
    policy = root / "master.md"
    if not policy.exists():
        atomic_write(
            policy,
            "# マスターの方針\n\n支援する業務、達成条件、任せる範囲を記入してください。\n",
        )
    print(f"Initialized {root}; configure scope and policy before starting the bot.")


if __name__ == "__main__":
    main()
