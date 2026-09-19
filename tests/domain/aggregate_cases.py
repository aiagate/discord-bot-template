"""Explicit samples and persisted fields for each public aggregate."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.domain.aggregates import ChatMessage, Team, TeamMembership, User
from app.domain.value_objects import (
    AuthorKind,
    ChatPlatform,
    DiscordConversationScope,
    DisplayName,
    Email,
    ExternalActorId,
    MembershipId,
    MembershipRole,
    MembershipStatus,
    MessageContent,
    MessageId,
    TeamId,
    TeamName,
    UserId,
    Version,
)

type Aggregate = ChatMessage | Team | TeamMembership | User

CREATED_AT = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
UPDATED_AT = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)


@dataclass(frozen=True)
class AggregateCase:
    restore_values: dict[str, Any]
    changed_values: dict[str, Any]
    id_parameter: str
    state_fields: tuple[str, ...]
    mutable: bool
    invalid_rows: tuple[tuple[str, Any], ...]


AGGREGATE_CASES: dict[type[Aggregate], AggregateCase] = {
    User: AggregateCase(
        restore_values={
            "user_id": UserId.generate().expect("valid ID"),
            "display_name": DisplayName("Alice"),
            "email": Email("alice@example.com"),
            "version": Version(4),
            "created_at": CREATED_AT,
            "updated_at": UPDATED_AT,
        },
        changed_values={"email": Email("other@example.com"), "version": Version(9)},
        id_parameter="user_id",
        state_fields=(
            "id",
            "display_name",
            "email",
            "version",
            "created_at",
            "updated_at",
        ),
        mutable=True,
        invalid_rows=(("id", "invalid"), ("display_name", ""), ("email", "invalid")),
    ),
    Team: AggregateCase(
        restore_values={
            "team_id": TeamId.generate().expect("valid ID"),
            "name": TeamName("Alpha"),
            "version": Version(3),
            "created_at": CREATED_AT,
            "updated_at": UPDATED_AT,
        },
        changed_values={"name": TeamName("Beta"), "version": Version(8)},
        id_parameter="team_id",
        state_fields=("id", "name", "version", "created_at", "updated_at"),
        mutable=True,
        invalid_rows=(("id", "invalid"), ("name", "")),
    ),
    TeamMembership: AggregateCase(
        restore_values={
            "membership_id": MembershipId.generate().expect("valid ID"),
            "team_id": TeamId.generate().expect("valid ID"),
            "user_id": UserId.generate().expect("valid ID"),
            "role": MembershipRole.ADMIN,
            "status": MembershipStatus.LEAVED,
            "version": Version(2),
            "created_at": CREATED_AT,
            "updated_at": UPDATED_AT,
        },
        changed_values={
            "role": MembershipRole.MEMBER,
            "status": MembershipStatus.PENDING,
            "version": Version(7),
        },
        id_parameter="membership_id",
        state_fields=(
            "id",
            "team_id",
            "user_id",
            "role",
            "status",
            "version",
            "created_at",
            "updated_at",
        ),
        mutable=True,
        invalid_rows=(
            ("id", "invalid"),
            ("team_id", "invalid"),
            ("user_id", "invalid"),
            ("role", "invalid"),
            ("status", "invalid"),
        ),
    ),
    ChatMessage: AggregateCase(
        restore_values={
            "message_id": MessageId.generate().expect("valid ID"),
            "platform": ChatPlatform.DISCORD,
            "conversation_scope": DiscordConversationScope("guild", "channel"),
            "external_sender_id": ExternalActorId("sender"),
            "author_kind": AuthorKind.BOT,
            "content": MessageContent.text("original"),
            "occurred_at": CREATED_AT,
        },
        changed_values={"content": MessageContent.text("changed")},
        id_parameter="message_id",
        state_fields=(
            "id",
            "platform",
            "conversation_scope",
            "external_sender_id",
            "author_kind",
            "content",
            "occurred_at",
        ),
        mutable=False,
        invalid_rows=(
            ("id", "invalid"),
            ("platform", "invalid"),
            ("external_sender_id", ""),
            ("author_kind", "invalid"),
            ("content", {"type": "invalid", "payload": {}}),
            (
                "conversation_scope",
                {"platform": "LINE", "kind": "user", "locator": "sender"},
            ),
        ),
    ),
}

TRANSITION_EXEMPTIONS = {
    User: "Email changes accept any valid Email; there is no lifecycle transition guard.",
    Team: "Name changes accept any valid TeamName; there is no lifecycle transition guard.",
    ChatMessage: "Messages are immutable and append-only; they have no state transitions.",
}

VERSION_EXEMPTIONS = {
    ChatMessage: "Append-only messages have no update version or mutable audit timestamps."
}


def aggregate_state(aggregate: Aggregate) -> dict[str, Any]:
    return {
        name: getattr(aggregate, name)
        for name in AGGREGATE_CASES[type(aggregate)].state_fields
    }
