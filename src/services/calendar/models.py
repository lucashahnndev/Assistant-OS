from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid
import time
import re
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from config.manager import ConfigManager


def _calendar_limits() -> tuple[int, int, int]:
    cfg = ConfigManager().get_capability_config("calendar") or {}
    title_max = int(cfg.get("title_max_length", 72))
    details_max = int(cfg.get("description_max_length", 4000))
    short_id_len = int(cfg.get("short_id_length", 10))
    title_max = max(8, min(200, title_max))
    details_max = max(128, min(20000, details_max))
    short_id_len = max(6, min(20, short_id_len))
    return title_max, details_max, short_id_len


def _derive_short_id(event_id: str, length: int) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "", str(event_id or "")).lower()[:length]


class CalendarEvent(BaseModel):
    model_config = ConfigDict(extra='ignore', validate_assignment=True)
    
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    short_id: str = ""
    user_id: str
    title: str
    start_time: float
    end_time: float
    description: Optional[str] = None
    timezone: str = Field(default_factory=lambda: ConfigManager().get_timezone())
    status: str = "scheduled" # scheduled, cancelled, completed
    reminders: List[int] = Field(default_factory=list)
    location: Optional[str] = None
    source: str = "internal"
    external_provider: Optional[str] = None
    external_event_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    sync_state: str = "synced" # synced, review_required, conflicted

    @field_validator("start_time", "end_time", mode='before')
    @classmethod
    def validate_timestamp(cls, v: Any) -> float:
        if isinstance(v, datetime):
            return v.timestamp()
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v).timestamp()
            except ValueError:
                return float(v)
        return float(v)

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, v: Any) -> str:
        text = " ".join(str(v or "").split()).strip()
        if not text:
            text = "Evento"
        title_max, _, _ = _calendar_limits()
        return text[:title_max]

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        text = str(v).strip()
        if not text:
            return None
        _, details_max, _ = _calendar_limits()
        return text[:details_max]

    @field_validator("short_id", mode="before")
    @classmethod
    def normalize_short_id(cls, v: Any) -> str:
        _, _, short_id_len = _calendar_limits()
        return _derive_short_id(str(v or ""), short_id_len)

    @model_validator(mode="after")
    def ensure_short_id(self):
        _, _, short_id_len = _calendar_limits()
        if not self.short_id:
            self.short_id = _derive_short_id(self.event_id, short_id_len)
        if not self.short_id:
            self.short_id = _derive_short_id(uuid.uuid4().hex, short_id_len)
        return self

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CalendarEvent":
        return cls.model_validate(data)
