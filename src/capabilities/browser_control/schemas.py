from typing import List, Dict, Any, Optional, Union, Literal
from pydantic import BaseModel, Field
from datetime import datetime

class BBox(BaseModel):
    x: float
    y: float
    width: float
    height: float

class EvidencePack(BaseModel):
    before_screenshot_ref: str
    after_screenshot_ref: str
    url_before: str
    url_after: str
    title_before: str
    title_after: str
    target_bbox: BBox # always present
    dom_delta_summary: str
    dom_delta_stats: Dict[str, int] # {added, removed, changed}
    console_errors_digest: List[str]
    network_failures_digest: List[Dict[str, Any]]
    dom_snapshot_ref: Optional[str] = None # required for critical actions
    cdp_events_digest: List[Dict[str, Any]]

class ToonResponse(BaseModel):
    command_id: str
    ts: datetime = Field(default_factory=datetime.utcnow)
    component: Literal["runtime", "planner", "dom_analyzer", "image_analyzer"]
    action: Literal[
        "navigate",
        "click",
        "type",
        "scroll",
        "wait",
        "screenshot",
        "dom_snapshot",
        "safe_confirm",
        "vision",
        "press_key",
        "click_visual",
        "action_batch",
    ]
    trace_id: str # global session correlation
    step_id: str # planner step identifier
    retry_count: int = 0
    requires_approval: bool = False
    approval_state: Literal["requested", "approved", "denied", "not_applicable"] = "not_applicable"
    status: Literal["pending", "running", "success", "error"]
    execution_time: float
    evidence_pack: Optional[EvidencePack] = None
    error_details: Optional[str] = None
    message: Optional[str] = None
    result_data: Optional[Dict[str, Any]] = None

class BrowserAction(BaseModel):
    command_id: str
    action_type: Literal["navigate", "click", "type", "scroll", "wait", "screenshot", "dom_snapshot", "scroll_into_view", "overlay_highlight_bbox", "mouse_move"]
    params: Dict[str, Any]

class AnalyzerCandidate(BaseModel):
    element_id: Optional[str] = None
    semantic_role: Optional[str] = None
    visual_role: Optional[str] = None
    bounding_box: BBox
    confidence_score: float = Field(ge=0.0, le=1.0)
    reasoning: str

class AnalyzerResponse(BaseModel):
    candidates: List[AnalyzerCandidate]
    intent_confirmation: str
