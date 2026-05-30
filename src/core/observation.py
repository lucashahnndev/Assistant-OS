from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional


def _clip_text(value: Any, limit: int = 240) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


_EVIDENCE_SOURCE_KEYS = (
    "results",
    "items",
    "files",
    "entries",
    "rows",
    "matches",
    "stdout_lines",
    "paths",
)

_EVIDENCE_LABEL_KEYS = (
    "name",
    "path",
    "title",
    "label",
    "text",
    "value",
    "id",
    "url",
)

_EVIDENCE_PREVIEW_LIMIT = 12


def _stringify_evidence_item(item: Any) -> str:
    if isinstance(item, dict):
        for key in _EVIDENCE_LABEL_KEYS:
            value = item.get(key)
            text = str(value or "").strip()
            if text:
                return _clip_text(text, 120)
        try:
            return _clip_text(item, 120)
        except Exception:
            return ""
    if isinstance(item, (list, tuple)):
        parts = [_stringify_evidence_item(part) for part in list(item)[:4]]
        parts = [part for part in parts if part]
        return _clip_text(", ".join(parts), 120)
    return _clip_text(item, 120)


def _singularize_label(label: str) -> str:
    text = str(label or "").strip().lower()
    mapping = {
        "results": "result",
        "items": "item",
        "files": "file",
        "entries": "entry",
        "rows": "row",
        "matches": "match",
        "stdout_lines": "stdout_line",
        "paths": "path",
    }
    return mapping.get(text, text[:-1] if text.endswith("s") else text)


def _extract_evidence_projection(structured_result: Any) -> Dict[str, Any]:
    payload = structured_result if isinstance(structured_result, dict) else {}
    source_key = ""
    source_items: List[Any] = []
    for candidate in _EVIDENCE_SOURCE_KEYS:
        value = payload.get(candidate)
        if isinstance(value, list) and value:
            source_key = candidate
            source_items = list(value)
            break

    if not source_items:
        return {
            "items": [],
            "total_count": int(payload.get("count") or payload.get("total_count") or payload.get("total") or 0),
            "shown_count": 0,
            "truncated": False,
            "item_type": "",
            "source_path": str(payload.get("path") or payload.get("source_path") or payload.get("directory") or payload.get("target_path") or "").strip(),
            "selection_rule": "",
            "warning": "",
        }

    preview_items = [_stringify_evidence_item(item) for item in source_items[:_EVIDENCE_PREVIEW_LIMIT]]
    preview_items = [item for item in preview_items if item]
    total_count = int(payload.get("count") or payload.get("total_count") or payload.get("total") or len(source_items) or 0)
    shown_count = len(preview_items)
    truncated = bool(total_count > shown_count or len(source_items) > shown_count)
    source_path = str(payload.get("path") or payload.get("source_path") or payload.get("directory") or payload.get("target_path") or "").strip()
    item_type = _singularize_label(source_key)
    selection_rule = f"structured_result.{source_key}[]"
    if preview_items and isinstance(source_items[0], dict):
        for key in _EVIDENCE_LABEL_KEYS:
            if key in source_items[0]:
                selection_rule = f"{selection_rule}->{key}"
                break

    warning = ""
    if truncated:
        warning = f"truncated; showing first {shown_count} of {total_count}"

    return {
        "items": preview_items,
        "total_count": total_count,
        "shown_count": shown_count,
        "truncated": truncated,
        "item_type": item_type,
        "source_path": source_path,
        "selection_rule": selection_rule,
        "warning": warning,
    }


def _build_evidence_summary(*, action_name: str, capability: str, evidence: Dict[str, Any]) -> str:
    items = [str(item).strip() for item in list(evidence.get("items") or []) if str(item).strip()]
    shown_count = int(evidence.get("shown_count") or len(items))
    total_count = int(evidence.get("total_count") or shown_count)
    truncated = bool(evidence.get("truncated"))
    source_path = str(evidence.get("source_path") or "").strip()
    item_type = str(evidence.get("item_type") or "item").strip() or "item"
    warning = str(evidence.get("warning") or "").strip()

    parts: List[str] = []
    if action_name:
        parts.append(f"action={action_name}")
    if capability:
        parts.append(f"capability={capability}")
    if source_path:
        parts.append(f"path={source_path}")
    parts.append(f"total={total_count}")
    parts.append(f"shown={shown_count}")
    parts.append(f"item_type={item_type}")
    parts.append(f"truncated={'yes' if truncated else 'no'}")
    if items:
        parts.append("items=" + ", ".join(items))
    if warning:
        parts.append(f"warning={warning}")
    return " | ".join(parts)


def _build_attachment_delivery_summary(delivery: Any) -> str:
    if not isinstance(delivery, dict) or not delivery:
        return ""

    requested = len(delivery.get("requested") or [])
    resolved = len(delivery.get("resolved") or [])
    prepared = len(delivery.get("prepared") or [])
    sent = len(delivery.get("sent") or [])
    errors = len(delivery.get("errors") or [])
    status = str(delivery.get("status") or "").strip() or "unknown"
    bridge = str(delivery.get("bridge") or "").strip()
    confirmed = delivery.get("confirmed")

    parts = [
        f"status={status}",
        f"requested={requested}",
        f"resolved={resolved}",
        f"prepared={prepared}",
        f"sent={sent}",
        f"errors={errors}",
    ]
    if bridge:
        parts.append(f"bridge={bridge}")
    if confirmed is not None:
        parts.append(f"confirmed={'yes' if confirmed else 'no'}")
    return " | ".join(parts)


def _clip_json(value: Any, limit: int = 180) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        text = _clip_text(value, limit)
    return _clip_text(text, limit)


@dataclass(slots=True)
class ActionObservation:
    """
    Structured post-execution observation for the agentic loop.

    This envelope records what happened after a tool/capability run so the next
    reasoning pass can continue, repair, or replan without treating the
    observation itself as a semantic decision.
    """

    action_name: str
    capability: str = ""
    status: str = ""
    success: bool = False
    reason: str = ""
    result_summary: str = ""
    structured_result: Any = field(default_factory=dict)
    error: str = ""
    raw_result_preview: str = ""
    observed_at: str = ""
    observed_turn_id: int = 0
    observed_work_id: str = ""
    source_action: str = ""
    source_args: Dict[str, Any] = field(default_factory=dict)
    freshness_note: str = ""
    evidence_items: List[str] = field(default_factory=list)
    evidence_total: int = 0
    evidence_shown: int = 0
    evidence_truncated: bool = False
    evidence_item_type: str = ""
    evidence_source_path: str = ""
    evidence_selection_rule: str = ""
    evidence_warning: str = ""
    state_changes: Dict[str, Any] = field(default_factory=dict)
    artifacts: Dict[str, Any] = field(default_factory=dict)
    attachment_delivery: Dict[str, Any] = field(default_factory=dict)
    next_step_context: str = ""
    repair_context: Dict[str, Any] = field(default_factory=dict)
    requires_replan: bool = False
    timestamp: str = ""
    work_id: str = ""
    turn_id: int = 0
    source: str = "runtime"

    @classmethod
    def from_execution(
        cls,
        *,
        action_name: str,
        status: str,
        reason: str = "",
        result_summary: str = "",
        structured_result: Any = None,
        error: str = "",
        raw_result_preview: str = "",
        source_args: Optional[Dict[str, Any]] = None,
        state_changes: Optional[Dict[str, Any]] = None,
        artifacts: Optional[Dict[str, Any]] = None,
        attachment_delivery: Optional[Dict[str, Any]] = None,
        next_step_context: str = "",
        repair_context: Optional[Dict[str, Any]] = None,
        requires_replan: bool = False,
        capability: str = "",
        work_id: str = "",
        turn_id: int = 0,
        source: str = "runtime",
    ) -> "ActionObservation":
        normalized_status = str(status or "").strip().lower() or "unknown"
        evidence = _extract_evidence_projection(structured_result)
        summary = str(result_summary or "").strip()
        evidence_summary = ""
        if evidence.get("items"):
            evidence_summary = _build_evidence_summary(
                action_name=action_name,
                capability=capability,
                evidence=evidence,
            )
        if evidence_summary:
            summary = evidence_summary
        if not summary:
            if isinstance(structured_result, dict):
                summary = _clip_text(
                    structured_result.get("summary")
                    or structured_result.get("message")
                    or structured_result.get("text")
                    or structured_result.get("result")
                    or raw_result_preview,
                    240,
                )
            else:
                summary = _clip_text(raw_result_preview, 240)

        error_text = str(error or "").strip()
        if not error_text and normalized_status in {"failure", "error"}:
            error_text = str(reason or "").strip()

        preview = _clip_text(raw_result_preview, 360)
        observed_at = datetime.now(timezone.utc).isoformat()
        observed_turn_id = int(turn_id or 0)
        observed_work_id = str(work_id or "").strip()
        source_action = str(action_name or "").strip()
        source_args_payload = dict(source_args or {}) if isinstance(source_args, dict) else {}
        freshness_note = "fresh_current_turn"
        next_step = str(next_step_context or "").strip()
        if not next_step:
            if normalized_status == "success":
                next_step = "continue_current_plan"
            elif normalized_status == "partial":
                next_step = "review_partial_result"
            elif normalized_status in {"failure", "error"}:
                next_step = "repair_or_replan"
            else:
                next_step = "observe_and_decide"

        repair = dict(repair_context or {})
        if isinstance(structured_result, dict):
            for key in ("error_code", "error", "validation_failures", "retryable", "provider"):
                value = structured_result.get(key)
                if value not in (None, "", [], {}):
                    repair.setdefault(key, value)

        changes = dict(state_changes or {})
        if not changes:
            changes = {
                "action_id": str(action_name or "").strip(),
                "status": normalized_status,
                "reason": str(reason or "").strip(),
            }

        artifacts_payload = dict(artifacts or {})
        attachment_delivery_payload = dict(attachment_delivery or {}) if isinstance(attachment_delivery, dict) else {}
        if not attachment_delivery_payload and artifacts_payload.get("attachments"):
            attachment_delivery_payload = {
                "requested": [],
                "resolved": list(artifacts_payload.get("attachments") or []),
                "prepared": list(artifacts_payload.get("attachments") or []),
                "sent": [],
                "errors": [],
                "bridge": source,
                "source_action": source_action,
                "status": "prepared",
                "confirmed": False,
            }
        return cls(
            action_name=str(action_name or "").strip(),
            capability=str(capability or "").strip(),
            status=normalized_status,
            success=normalized_status == "success",
            reason=str(reason or "").strip(),
            result_summary=summary,
            structured_result=structured_result if structured_result is not None else {},
            error=error_text,
            raw_result_preview=preview,
            observed_at=observed_at,
            observed_turn_id=observed_turn_id,
            observed_work_id=observed_work_id,
            source_action=source_action,
            source_args=source_args_payload,
            freshness_note=freshness_note,
            evidence_items=list(evidence.get("items") or []),
            evidence_total=int(evidence.get("total_count") or 0),
            evidence_shown=int(evidence.get("shown_count") or 0),
            evidence_truncated=bool(evidence.get("truncated")),
            evidence_item_type=str(evidence.get("item_type") or "").strip(),
            evidence_source_path=str(evidence.get("source_path") or "").strip(),
            evidence_selection_rule=str(evidence.get("selection_rule") or "").strip(),
            evidence_warning=str(evidence.get("warning") or "").strip(),
            state_changes=changes,
            artifacts=artifacts_payload,
            attachment_delivery=attachment_delivery_payload,
            next_step_context=next_step,
            repair_context=repair,
            requires_replan=bool(requires_replan or normalized_status in {"failure", "partial", "error"}),
            timestamp=datetime.now(timezone.utc).isoformat(),
            work_id=str(work_id or "").strip(),
            turn_id=int(turn_id or 0),
            source=str(source or "runtime").strip() or "runtime",
        )

    def to_state_summary_update(self) -> Dict[str, Any]:
        attachment_summary = _build_attachment_delivery_summary(self.attachment_delivery)
        requested = self.attachment_delivery.get("requested") if isinstance(self.attachment_delivery, dict) else []
        resolved = self.attachment_delivery.get("resolved") if isinstance(self.attachment_delivery, dict) else []
        prepared = self.attachment_delivery.get("prepared") if isinstance(self.attachment_delivery, dict) else []
        sent = self.attachment_delivery.get("sent") if isinstance(self.attachment_delivery, dict) else []
        errors = self.attachment_delivery.get("errors") if isinstance(self.attachment_delivery, dict) else []
        return {
            "last_observation": self.to_prompt_summary(),
            "last_observation_evidence": self.to_evidence_summary(),
            "last_observation_evidence_count": self.evidence_total,
            "last_observation_evidence_shown": self.evidence_shown,
            "last_observation_evidence_truncated": self.evidence_truncated,
            "last_attachment_delivery": self.attachment_delivery,
            "last_attachment_delivery_summary": attachment_summary or "None",
            "last_attachment_delivery_status": str(self.attachment_delivery.get("status") or "none") if isinstance(self.attachment_delivery, dict) else "none",
            "last_attachment_delivery_requested_count": len(requested) if isinstance(requested, list) else 0,
            "last_attachment_delivery_resolved_count": len(resolved) if isinstance(resolved, list) else 0,
            "last_attachment_delivery_prepared_count": len(prepared) if isinstance(prepared, list) else 0,
            "last_attachment_delivery_sent_count": len(sent) if isinstance(sent, list) else 0,
            "last_attachment_delivery_error_count": len(errors) if isinstance(errors, list) else 0,
            "last_attachment_delivery_confirmed": bool(self.attachment_delivery.get("sent")) if isinstance(self.attachment_delivery, dict) else False,
            "last_observation_status": self.status,
            "last_observation_reason": self.reason,
            "last_observation_requires_replan": self.requires_replan,
            "last_observation_turn_id": self.observed_turn_id or self.turn_id,
            "last_observation_work_id": self.observed_work_id or self.work_id,
            "last_observation_source_action": self.source_action or self.action_name,
            "last_observation_source_args": self.source_args,
            "last_observation_observed_at": self.observed_at or self.timestamp,
            "last_observation_freshness": self.freshness_note or "fresh_current_turn",
        }

    def to_evidence_summary(self) -> str:
        if self.evidence_items:
            preview = ", ".join(self.evidence_items[:_EVIDENCE_PREVIEW_LIMIT])
            if self.evidence_truncated and preview:
                preview = f"{preview} ..."
            parts = [
                f"action={self.action_name}" if self.action_name else "action=unknown",
            ]
            if self.capability:
                parts.append(f"capability={self.capability}")
            if self.evidence_source_path:
                parts.append(f"path={self.evidence_source_path}")
            parts.append(f"total={self.evidence_total or len(self.evidence_items)}")
            parts.append(f"shown={self.evidence_shown or len(self.evidence_items)}")
            parts.append(f"truncated={'yes' if self.evidence_truncated else 'no'}")
            if self.evidence_item_type:
                parts.append(f"item_type={self.evidence_item_type}")
            if preview:
                parts.append(f"items={preview}")
            if self.evidence_warning:
                parts.append(f"warning={self.evidence_warning}")
            return " | ".join(parts)
        return ""

    def to_prompt_summary(self) -> str:
        bits: List[str] = [
            f"action={self.action_name}" if self.action_name else "action=unknown",
            f"status={self.status or 'unknown'}",
        ]
        if self.capability:
            bits.append(f"capability={self.capability}")
        if self.reason:
            bits.append(f"reason={_clip_text(self.reason, 80)}")
        if self.result_summary:
            bits.append(f"summary={_clip_text(self.result_summary, 140)}")
        if self.error:
            bits.append(f"error={_clip_text(self.error, 80)}")
        if self.observed_at:
            bits.append(f"observed_at={_clip_text(self.observed_at, 40)}")
        if self.observed_turn_id:
            bits.append(f"observed_turn={self.observed_turn_id}")
        if self.observed_work_id:
            bits.append(f"work={_clip_text(self.observed_work_id, 40)}")
        if self.source_action:
            bits.append(f"source_action={_clip_text(self.source_action, 48)}")
        if self.source_args:
            bits.append(f"source_args={_clip_json(self.source_args, 120)}")
        if self.freshness_note:
            bits.append(f"freshness={_clip_text(self.freshness_note, 24)}")
        evidence_summary = self.to_evidence_summary()
        if evidence_summary:
            bits.append(f"evidence={_clip_text(evidence_summary, 220)}")
        attachment_summary = _build_attachment_delivery_summary(self.attachment_delivery)
        if attachment_summary:
            bits.append(f"attachment_delivery={_clip_text(attachment_summary, 220)}")
        if self.requires_replan:
            bits.append("replan=yes")
        return " | ".join(bits)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_name": self.action_name,
            "capability": self.capability,
            "status": self.status,
            "success": self.success,
            "reason": self.reason,
            "result_summary": self.result_summary,
            "structured_result": self.structured_result,
            "error": self.error,
            "raw_result_preview": self.raw_result_preview,
            "observed_at": self.observed_at,
            "observed_turn_id": self.observed_turn_id,
            "observed_work_id": self.observed_work_id,
            "source_action": self.source_action,
            "source_args": self.source_args,
            "freshness_note": self.freshness_note,
            "evidence_items": self.evidence_items,
            "evidence_total": self.evidence_total,
            "evidence_shown": self.evidence_shown,
            "evidence_truncated": self.evidence_truncated,
            "evidence_item_type": self.evidence_item_type,
            "evidence_source_path": self.evidence_source_path,
            "evidence_selection_rule": self.evidence_selection_rule,
            "evidence_warning": self.evidence_warning,
            "state_changes": self.state_changes,
            "artifacts": self.artifacts,
            "attachment_delivery": self.attachment_delivery,
            "next_step_context": self.next_step_context,
            "repair_context": self.repair_context,
            "requires_replan": self.requires_replan,
            "timestamp": self.timestamp,
            "work_id": self.work_id,
            "turn_id": self.turn_id,
            "source": self.source,
        }
