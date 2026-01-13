"""SystemInstructionId value object."""

from dataclasses import dataclass

from app.domain.value_objects.base_id import BaseId


@dataclass(frozen=True)
class SystemInstructionId(BaseId):
    """Unique identifier for a System Instruction."""

    pass
