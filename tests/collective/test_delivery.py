"""A8-A10: ordered fragments, ambiguous sends, and recovery without rerunning work."""

from typing import cast

import pytest

from app.contracts.messages.collective import Character, Scope, Speech, SpeechPart
from app.contracts.ports.collective import DeliveryResult
from app.infrastructure.collective.webhook import WebhookPublisher
from app.usecases.collective.delivery import Delivery
from app.usecases.collective.runtime import Collective
from tests.collective.test_runtime import start_activity


class PublisherDouble:
    """Return controlled transport outcomes for fixed payloads."""

    def __init__(self) -> None:
        self.outcomes: list[DeliveryResult | Exception] = []
        self.destinations = {
            "master": "https://discord.com/api/webhooks/1/token",
            "times": "https://discord.com/api/webhooks/2/token",
        }
        self.sent: list[SpeechPart] = []
        self.reconciled: list[SpeechPart] = []

    def split(self, speech: Speech) -> list[SpeechPart]:
        """Use the production fragmentation algorithm."""
        return WebhookPublisher.split(cast(WebhookPublisher, self), speech)

    async def send(self, part: SpeechPart, character: Character) -> DeliveryResult:
        """Count each POST-like invocation."""
        self.sent.append(part)
        result = (
            self.outcomes.pop(0)
            if self.outcomes
            else DeliveryResult("sent", str(len(self.sent)))
        )
        if isinstance(result, Exception):
            raise result
        return result

    async def reconcile(self, part: SpeechPart) -> DeliveryResult:
        """Reconciliation never posts another copy."""
        self.reconciled.append(part)
        return DeliveryResult("sent", part.message_id)


def add_speech(
    collective: Collective, key: str, scope: Scope = "master", body: str = "結果です。"
) -> None:
    """Seed a conversationally rendered utterance."""
    with collective.store.transaction() as state:
        state.speeches[key] = Speech(
            id=key,
            character_id="alice",
            scope=scope,
            origin=key,
            body=body,
            status="ready",
        )


@pytest.mark.anyio
async def test_unknown_fragment_blocks_only_its_destination(
    collective: Collective,
) -> None:
    add_speech(collective, "first", body="A" * 4001)
    add_speech(collective, "later")
    add_speech(collective, "peer", "times")
    publisher = PublisherDouble()
    publisher.outcomes = [DeliveryResult("sent", "1"), DeliveryResult("unknown")]
    delivery = Delivery(
        collective.store, publisher, collective.characters, collective.settings
    )
    assert await delivery.step(1)
    assert await delivery.step(2)
    assert await delivery.step(3)
    assert not await delivery.step(4)
    assert [part.destination for part in publisher.sent] == [
        "master:1",
        "master:1",
        "times:2",
    ]
    state = collective.store.read()
    assert state.parts["first/1"].status == "unknown"
    assert state.parts["first/2"].status == "ready"
    delivery.confirm("first/1", "99")
    assert await delivery.step(5)
    assert len(publisher.sent) == 3
    assert publisher.reconciled[0].message_id == "99"
    assert await delivery.step(6)
    assert collective.store.read().speeches["first"].status == "sent"


@pytest.mark.anyio
async def test_rejected_request_retries_fixed_payload_up_to_limit(
    collective: Collective,
) -> None:
    add_speech(collective, "one")
    publisher = PublisherDouble()
    publisher.outcomes = [
        DeliveryResult("rejected", error="rate limit", retry_after=10)
    ] * 3
    delivery = Delivery(
        collective.store, publisher, collective.characters, collective.settings
    )
    assert await delivery.step(1)
    assert not await delivery.step(2)
    assert await delivery.step(11)
    assert await delivery.step(21)
    assert not await delivery.step(31)
    assert collective.store.read().parts["one/0"].status == "held"
    assert {p.body for p in publisher.sent} == {"結果です。"}


@pytest.mark.anyio
async def test_crash_in_send_is_unknown_not_a_new_post(collective: Collective) -> None:
    add_speech(collective, "one")
    publisher = PublisherDouble()
    publisher.outcomes = [TimeoutError()]
    delivery = Delivery(
        collective.store, publisher, collective.characters, collective.settings
    )
    await delivery.step(1)
    with collective.store.transaction() as state:
        state.parts["one/0"].status = "sending"
    delivery.recover()
    assert not await delivery.step(10)
    assert len(publisher.sent) == 1
    with pytest.raises(ValueError):
        delivery.confirm("one/0", "invalid")


@pytest.mark.anyio
async def test_stopped_commitment_is_rerendered_before_delivery(
    collective: Collective,
) -> None:
    activity_id = await start_activity(collective)
    await collective.stop(activity_id, "Stop", 2)
    publisher = PublisherDouble()
    delivery = Delivery(
        collective.store, publisher, collective.characters, collective.settings
    )
    await delivery.step(3)
    assert not publisher.sent
    speech = next(iter(collective.store.read().speeches.values()))
    assert speech.status == "unrendered"
    assert "stopped" in speech.report.uncertainty[0]


@pytest.mark.parametrize(
    "body", ["A" * 4001, "あ" * 4000, "😀" * 2001, "a" * 1300 + "\n" + "b" * 1200]
)
def test_split_keeps_all_text_within_utf16_limit(body: str) -> None:
    publisher = PublisherDouble()
    speech = Speech(id="s", character_id="alice", scope="master", origin="s", body=body)
    parts = publisher.split(speech)
    assert "".join(part.body for part in parts) == body
    assert all(len(part.body.encode("utf-16-le")) // 2 <= 2000 for part in parts)


@pytest.mark.anyio
async def test_operator_can_retry_rejected_payload_but_not_unknown_send(
    collective: Collective,
) -> None:
    add_speech(collective, "saved")
    publisher = PublisherDouble()
    publisher.outcomes = [
        DeliveryResult("rejected", error="Permission missing")
    ] * collective.settings.max_attempts
    delivery = Delivery(
        collective.store, publisher, collective.characters, collective.settings
    )
    for now in range(1, 10, 3):
        await delivery.step(now)
    assert collective.store.read().parts["saved/0"].status == "held"
    delivery.retry("saved/0")
    await delivery.step(20)
    assert collective.store.read().speeches["saved"].status == "sent"
    assert len({part.body for part in publisher.sent}) == 1
    with collective.store.transaction() as state:
        state.parts["saved/0"].status = "unknown"
    with pytest.raises(ValueError, match="definitely rejected"):
        delivery.retry("saved/0")
