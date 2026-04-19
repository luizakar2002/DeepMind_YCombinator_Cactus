from pydantic import BaseModel
from typing import Any, Optional


class BaseEvent(BaseModel):
    event: str
    session_id: str
    timestamp: str


class SessionStartEvent(BaseEvent):
    event: str = "session_start"
    message: str


class TranscriptEvent(BaseEvent):
    event: str = "transcript"
    text: str


class EntitiesEvent(BaseEvent):
    event: str = "entities"
    data: dict[str, Any]


class AlertEvent(BaseEvent):
    event: str = "alert"
    level: str        # "info" | "warning" | "critical"
    category: str     # "red_flag" | "drug_interaction" | "contradiction" | "differential"
    message: str
    detail: Optional[dict[str, Any]] = None


class SummaryEvent(BaseEvent):
    event: str = "summary"
    data: dict[str, Any]


class ErrorEvent(BaseEvent):
    event: str = "error"
    message: str
