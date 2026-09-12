"""Contracts for user-owned Profile and Timeline memory."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True, slots=True)
class UserMemorySource:
    """One immutable raw chat row supplied to memory consolidation."""

    message_id: str
    user_id: str
    platform: str
    author_kind: str
    external_sender_id: str
    content: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class UserMemoryProfile:
    """The durable, user-owned profile view."""

    user_id: str
    summary: str
    traits: tuple[str, ...]
    preferences: tuple[str, ...]
    source_message_ids: tuple[str, ...]
    updated_at: datetime
    confidence: float = 0.0
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class UserTimelineEntry:
    """One durable user-owned episode in the Timeline view."""

    id: str
    user_id: str
    day: str
    title: str
    summary: str
    source_message_ids: tuple[str, ...]
    confidence: float
    occurred_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class UserMemoryContext:
    """Bounded memory context read for one canonical user."""

    profile: UserMemoryProfile | None = None
    timeline: tuple[UserTimelineEntry, ...] = ()


class UserMemoryProfilePatch(BaseModel):
    """Validated profile change proposed by semantic extraction."""

    model_config = ConfigDict(extra="forbid")

    summary: str | None = Field(default=None, max_length=1000)
    traits: list[str] = Field(default_factory=list, max_length=20)
    preferences: list[str] = Field(default_factory=list, max_length=20)
    confidence: float = Field(ge=0.0, le=1.0)
    source_message_ids: list[str] = Field(default_factory=list, min_length=1)
    update_mode: Literal["merge", "replace", "defer"] = "merge"


class UserMemoryTimelinePatch(BaseModel):
    """Validated Timeline episode proposed by semantic extraction."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=1000)
    source_message_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class UserMemorySourceEvaluation(BaseModel):
    """Disposition of one raw source row."""

    model_config = ConfigDict(extra="forbid")

    message_id: str
    disposition: Literal["used", "not_memorable", "deferred"]
    reason: str = Field(default="", max_length=400)


class UserMemoryExtractionRequest(BaseModel):
    """Input sent to the semantic memory extractor."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    user_id: str
    day: str
    raw_logs: list[UserMemorySource] = Field(min_length=1)
    existing_profile: UserMemoryProfile | None = None
    existing_timeline: list[UserTimelineEntry] = Field(default_factory=list)


class UserMemoryExtractionResult(BaseModel):
    """Strict extraction output accepted by the consolidation use case."""

    model_config = ConfigDict(extra="forbid")

    profile_patch: UserMemoryProfilePatch | None = None
    timeline_patches: list[UserMemoryTimelinePatch] = Field(
        default_factory=list, max_length=20
    )
    source_evaluations: list[UserMemorySourceEvaluation] = Field(min_length=1)
