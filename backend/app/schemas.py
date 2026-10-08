from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StateChange(StrictModel):
    kind: Literal["flag_set", "relation_delta"]
    key: str = Field(max_length=60)
    value: int = Field(ge=-2, le=2)


class Action(StrictModel):
    type: Literal["option", "text"]
    value: str = Field(min_length=1, max_length=500)


class TurnRequest(StrictModel):
    parent_node_id: str
    action: Action


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
