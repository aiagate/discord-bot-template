"""Load the optional private context used to personalize the master."""

from pathlib import Path

from app.contracts.messages.character_prompt import MAX_MASTER_CONTEXT_LENGTH


def load_master_context(path: Path | None) -> str | None:
    """Read and validate one UTF-8 master context file."""
    if path is None:
        return None
    if not path.exists():
        raise ValueError(f"Master context file does not exist: '{path}'.")
    if not path.is_file():
        raise ValueError(f"Master context path is not a file: '{path}'.")
    try:
        context = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        raise ValueError(f"Could not read master context file '{path}'.") from error
    if not context:
        return None
    if len(context) > MAX_MASTER_CONTEXT_LENGTH:
        raise ValueError(
            "Master context exceeds the maximum length "
            f"({MAX_MASTER_CONTEXT_LENGTH} characters)."
        )
    return context
