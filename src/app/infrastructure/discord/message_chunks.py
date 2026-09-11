"""Split Discord text at paragraph, line or word boundaries."""

import re

DISCORD_MESSAGE_LIMIT = 2000
_FENCE = re.compile(r"^```([^`\n]*)$", re.MULTILINE)


def _units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def split_discord_content(
    content: str, *, limit: int = DISCORD_MESSAGE_LIMIT
) -> tuple[str, ...]:
    """Split text without cutting Unicode code points, reopening fenced code blocks."""
    if limit < 64:
        raise ValueError("Chunk limit must leave room for text and code fences.")
    remaining = content.strip()
    parts: list[str] = []
    fence = ""
    while remaining:
        prefix = f"{fence}\n" if fence else ""
        if _units(prefix + remaining) <= limit:
            parts.append(prefix + remaining)
            break
        budget = limit - _units(prefix) - 4
        end = 0
        units = 0
        for character in remaining:
            width = 2 if ord(character) > 0xFFFF else 1
            if units + width > budget:
                break
            units += width
            end += 1
        window = remaining[:end]
        cut = end
        for separator in ("\n\n", "\n", "。", ". ", " "):
            position = window.rfind(separator)
            if position > 0:
                cut = position + len(separator)
                break
        body = remaining[:cut]
        for match in _FENCE.finditer(body):
            # Bound the reopening marker so even an unusual language label leaves
            # room for content and the loop always makes progress.
            fence = "" if fence else "```" + match.group(1).strip()[:16]
        suffix = "\n```" if fence else ""
        if body.strip():
            parts.append(prefix + body.rstrip() + suffix)
        remaining = remaining[cut:]
    return tuple(parts)
