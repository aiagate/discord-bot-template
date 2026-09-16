"""One-attempt Discord webhook transport; credentials stay outside saved payloads."""

from urllib.parse import urlparse

import aiohttp

from app.contracts.messages.collective import Character, Speech, SpeechPart
from app.contracts.ports.collective import DeliveryResult


class WebhookPublisher:
    """Keep configured webhook URLs out of model inputs and persisted speech."""

    def __init__(
        self, session: aiohttp.ClientSession, destinations: dict[str, str]
    ) -> None:
        self.session = session
        self.destinations = destinations
        for url in destinations.values():
            parsed = urlparse(url)
            if (
                parsed.scheme != "https"
                or parsed.hostname != "discord.com"
                or not parsed.path.startswith("/api/webhooks/")
            ):
                raise ValueError("A Discord HTTPS webhook URL is required")

    def split(self, speech: Speech) -> list[SpeechPart]:
        """Split at paragraph or line boundaries and respect the UTF-16 limit."""
        remaining = speech.body or ""
        parts: list[SpeechPart] = []
        while remaining:
            end, units = 0, 0
            for char in remaining:
                size = len(char.encode("utf-16-le")) // 2
                if units + size > 2000:
                    break
                units += size
                end += 1
            if end < len(remaining):
                boundary = remaining.rfind("\n", 0, end)
                if boundary > end // 2:
                    end = boundary + 1
            parts.append(
                SpeechPart(
                    id=f"{speech.id}/{len(parts)}",
                    speech_id=speech.id,
                    index=len(parts),
                    destination=f"{speech.scope}:{urlparse(self.destinations[speech.scope]).path.split('/')[3]}",
                    body=remaining[:end],
                )
            )
            remaining = remaining[end:]
        return parts

    async def send(self, part: SpeechPart, character: Character) -> DeliveryResult:
        """POST once with wait=true; timeouts and server failures remain unknown."""
        url = self._destination(part)
        if url is None:
            return DeliveryResult(
                "rejected", error="Saved destination differs from configuration"
            )
        payload: dict[str, object] = {
            "content": part.body,
            "username": character.name,
            "allowed_mentions": {"parse": []},
        }
        if character.avatar_url:
            payload["avatar_url"] = character.avatar_url
        try:
            async with self.session.post(
                url,
                params={"wait": "true"},
                json=payload,
                allow_redirects=False,
            ) as response:
                if response.status == 429:
                    data = await response.json()
                    return DeliveryResult(
                        "rejected",
                        error="Discord rate limit",
                        retry_after=float(data.get("retry_after", 1)),
                    )
                if 400 <= response.status < 500:
                    return DeliveryResult(
                        "rejected", error=f"Discord HTTP {response.status}"
                    )
                if response.status != 200:
                    return DeliveryResult(
                        "unknown", error=f"Discord HTTP {response.status}"
                    )
                value = await response.json()
                message_id = value.get("id")
                if isinstance(message_id, str) and message_id.isdecimal():
                    return DeliveryResult("sent", message_id)
                return DeliveryResult(
                    "unknown", error="No message ID in delivery response"
                )
        except (aiohttp.ClientError, TimeoutError):
            return DeliveryResult("unknown", error="Discord transport outcome unknown")

    async def reconcile(self, part: SpeechPart) -> DeliveryResult:
        """A missing message does not prove that the original send failed."""
        if part.message_id is None:
            return DeliveryResult("unknown", error="No message ID to reconcile")
        destination = self._destination(part)
        if destination is None:
            return DeliveryResult(
                "unknown",
                part.message_id,
                "Saved destination differs from configuration",
            )
        url = destination.split("?", 1)[0] + f"/messages/{part.message_id}"
        try:
            async with self.session.get(url, allow_redirects=False) as response:
                if response.status == 200:
                    value = await response.json()
                    if (
                        value.get("id") == part.message_id
                        and value.get("content") == part.body
                    ):
                        return DeliveryResult("sent", part.message_id)
                return DeliveryResult(
                    "unknown", part.message_id, "Could not confirm the fixed payload"
                )
        except (aiohttp.ClientError, TimeoutError):
            return DeliveryResult(
                "unknown", part.message_id, "Reconciliation unavailable"
            )

    def _destination(self, part: SpeechPart) -> str | None:
        scope, _, webhook_id = part.destination.partition(":")
        url = self.destinations.get(scope)
        if url is None or urlparse(url).path.split("/")[3] != webhook_id:
            return None
        return url
