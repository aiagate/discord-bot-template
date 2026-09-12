"""Persistent character work and executor events."""

from dataclasses import dataclass
from typing import Literal

WorkStatus = Literal["queued", "running", "completed", "stopped", "failed", "paused"]


@dataclass(frozen=True, slots=True)
class WorkArtifacts:
    """Identity and verification summary of an immutable result archive."""

    revision_id: str
    sha256: str
    size: int
    file_count: int
    summary: str


@dataclass(frozen=True, slots=True)
class WorkAttachment:
    """Verified attachment bytes, independent of the messaging platform."""

    filename: str
    data: bytes


@dataclass(frozen=True, slots=True)
class WorkCommandEvidence:
    """Observed command outcome, rather than a model's claim about a test."""

    command: str
    exit_code: int | None
    output: str


@dataclass(frozen=True, slots=True)
class CharacterWork:
    """One owner's task in one Discord conversation."""

    id: str
    guild_id: str
    channel_id: str
    owner_id: str
    character_id: str
    prompt: str
    last_message_id: str
    status: WorkStatus = "queued"
    thread_id: str | None = None
    cwd: str | None = None
    summary: str = ""
    result: str = ""
    linked: bool = True
    artifacts: WorkArtifacts | None = None


@dataclass(frozen=True, slots=True)
class WorkEvent:
    """An executor update, with session identity emitted before execution."""

    kind: Literal["session", "progress", "completed", "stopped"]
    text: str = ""
    thread_id: str | None = None
    cwd: str | None = None
    artifacts: WorkArtifacts | None = None


class CharacterWorkError(Exception):
    """A work operation failed without exposing provider or host details."""
