"""Small deterministic task domain for the Week 23 deployment lab."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


ShortMessage = Annotated[str, StringConstraints(min_length=1, max_length=256)]


class EchoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: ShortMessage


class SumInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    numbers: list[int] = Field(min_length=1, max_length=16)


class EchoCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["echo"]
    input: EchoInput


class SumCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["sum"]
    input: SumInput


TaskCommand = Annotated[EchoCommand | SumCommand, Field(discriminator="operation")]


def execute(command: TaskCommand) -> dict[str, str | int]:
    """Return a deterministic result for one validated synthetic task."""
    if isinstance(command, EchoCommand):
        return {"message": command.input.message}
    return {"total": sum(command.input.numbers)}
