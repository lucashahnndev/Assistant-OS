import time
import uuid
from typing import Any, Dict, List


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


class SignalConfidenceEngine:
    """
    Phase-1 learning signal confidence model.
    Observe-only mode: scores/flags signals but does not auto-apply policy patches.
    """

    VERSION = "signal_confidence.v1"
    MODE = "observe_only_no_auto_patch"

    BASE_WEIGHTS = {
        "explicit": 0.92,
        "behavioral": 0.66,
        "contextual": 0.58,
        "implicit": 0.48,
    }

    def assess(self, signal: Dict[str, Any], history: List[Dict[str, Any]]) -> Dict[str, Any]:
        now = float(time.time())
        signal_type = str(signal.get("signal_type") or "implicit").strip().lower()
        base = float(self.BASE_WEIGHTS.get(signal_type, 0.5))
        normalized_value = self._normalize_value(signal.get("value"))
        signal_name = str(signal.get("signal_name") or "").strip().lower()
        source = str(signal.get("source") or "").strip().lower()
        created_at = float(signal.get("created_at") or now)
        age_hours = max(0.0, (now - created_at) / 3600.0)

        same_name = [
            h for h in (history or [])
            if str(h.get("signal_name") or "").strip().lower() == signal_name
        ]
        if same_name:
            same_value_count = sum(
                1 for h in same_name if self._normalize_value(h.get("value")) == normalized_value
            )
            conflict_count = max(0, len(same_name) - same_value_count)
            consistency_ratio = float(same_value_count / max(1, len(same_name)))
        else:
            same_value_count = 0
            conflict_count = 0
            consistency_ratio = 1.0

        context_similarity = self._context_similarity(signal, same_name)
        repetition_boost = 1.0 + min(5, same_value_count) * 0.06
        consistency_factor = 0.7 + (0.3 * consistency_ratio)
        context_factor = 0.8 + (0.2 * context_similarity)
        recency_factor = _clamp(1.0 / (1.0 + (age_hours / 48.0)), 0.7, 1.0)
        conflict_penalty = _clamp(1.0 - (conflict_count * 0.1), 0.55, 1.0)
        source_boost = 1.08 if source in {"explicit_user_command", "user_feedback"} else 1.0

        confidence = base
        confidence *= repetition_boost
        confidence *= consistency_factor
        confidence *= context_factor
        confidence *= recency_factor
        confidence *= conflict_penalty
        confidence *= source_boost
        confidence = _clamp(confidence)

        reliability_flag = "high" if confidence >= 0.82 else ("medium" if confidence >= 0.60 else "low")
        eligible_patch_recommendation = (
            confidence >= 0.84 and same_value_count >= 3 and conflict_count <= 1 and signal_type != "contextual"
        )

        return {
            "assessment_id": f"sigas_{uuid.uuid4().hex[:10]}",
            "signal_id": str(signal.get("signal_id") or ""),
            "signal_name": signal_name,
            "signal_type": signal_type,
            "confidence_score": round(confidence, 4),
            "weight": round(base, 4),
            "decay": round(1.0 - recency_factor, 4),
            "reliability_flag": reliability_flag,
            "consistency_ratio": round(consistency_ratio, 4),
            "repetition_count": int(same_value_count),
            "conflict_count": int(conflict_count),
            "context_similarity": round(context_similarity, 4),
            "mode": self.MODE,
            "eligible_patch_recommendation": bool(eligible_patch_recommendation),
            "patch_recommendation": self._build_recommendation(signal, confidence) if eligible_patch_recommendation else None,
            "engine_version": self.VERSION,
            "created_at": now,
        }

    @staticmethod
    def _normalize_value(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if value is None:
            return "null"
        return str(value).strip().lower()

    def _context_similarity(self, signal: Dict[str, Any], history: List[Dict[str, Any]]) -> float:
        if not history:
            return 1.0
        ctx = signal.get("context") if isinstance(signal.get("context"), dict) else {}
        domain = str(signal.get("source_domain") or ctx.get("domain") or "").strip().lower()
        event_type = str(ctx.get("event_type") or "").strip().lower()
        matched = 0
        for h in history:
            h_ctx = h.get("context") if isinstance(h.get("context"), dict) else {}
            h_domain = str(h.get("source_domain") or h_ctx.get("domain") or "").strip().lower()
            h_event_type = str(h_ctx.get("event_type") or "").strip().lower()
            domain_match = bool(domain) and domain == h_domain
            event_match = bool(event_type) and event_type == h_event_type
            if domain_match or event_match:
                matched += 1
        return float(matched / max(1, len(history)))

    @staticmethod
    def _build_recommendation(signal: Dict[str, Any], confidence: float) -> Dict[str, Any]:
        signal_name = str(signal.get("signal_name") or "").strip().lower()
        user_id = str(signal.get("user_id") or "")
        if signal_name == "delivery_failure":
            return {
                "target": "channel_policy",
                "reason": "Frequent delivery failures observed.",
                "proposal": {"fallback_allowed": True},
                "user_id": user_id,
                "confidence": round(confidence, 4),
            }
        if signal_name == "delivery_success":
            return {
                "target": "channel_policy",
                "reason": "Consistent successful delivery pattern.",
                "proposal": {"prefer_last_success_channel": True},
                "user_id": user_id,
                "confidence": round(confidence, 4),
            }
        return {
            "target": "timing_policy",
            "reason": "Signal trend reached confidence threshold.",
            "proposal": {"review_required": True},
            "user_id": user_id,
            "confidence": round(confidence, 4),
        }
