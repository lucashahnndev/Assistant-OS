from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ProviderResult(BaseModel):
    ok: bool = True
    raw_text: str = ""
    parsed: Optional[Dict[str, Any]] = None
    provider_name: str = ""
    model: str = ""
    error_type: str = ""
    error_code: str = ""
    trace_id: str = ""
    attempt_id: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)

