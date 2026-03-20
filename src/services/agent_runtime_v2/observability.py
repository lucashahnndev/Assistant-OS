from __future__ import annotations

import json
import os
import threading
import time
from collections import Counter
from typing import Any, Dict, Optional

from config.manager import ConfigManager


class RuntimeV2Observability:
    """Structured telemetry/events for governance, replay and debugging."""

    def __init__(self, config_manager: Optional[Any] = None) -> None:
        self.config_manager = config_manager or ConfigManager()
        base = getattr(self.config_manager, "base_data_dir", None) or ConfigManager.get_data_dir()
        runtime_cfg = self.config_manager.get("runtime", {}) if hasattr(self.config_manager, "get") else {}
        runtime_cfg = runtime_cfg if isinstance(runtime_cfg, dict) else {}
        v2_cfg = runtime_cfg.get("agent_runtime_v2", {}) if isinstance(runtime_cfg.get("agent_runtime_v2"), dict) else {}
        obs_cfg = v2_cfg.get("observability", {}) if isinstance(v2_cfg.get("observability"), dict) else {}
        self._enabled = bool(obs_cfg.get("enabled", True))

        event_log_cfg = str(obs_cfg.get("event_log", "runtime_v2/governance_events.jsonl") or "runtime_v2/governance_events.jsonl")
        if os.path.isabs(event_log_cfg):
            self._events_path = event_log_cfg
        else:
            self._events_path = os.path.join(str(base), event_log_cfg)
        os.makedirs(os.path.dirname(self._events_path), exist_ok=True)
        self._lock = threading.Lock()
        self._counters = Counter()
        self._last_snapshot: Dict[str, Any] = {}

    @property
    def enabled(self) -> bool:
        return bool(self._enabled)

    def record_execution_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        if not self._enabled:
            return self.snapshot_metrics()
        payload = dict(event or {})
        payload.setdefault("ts", time.time())
        payload.setdefault("event", "runtime_v2_execution")
        status = str(payload.get("result_status", "unknown") or "unknown")
        decision = str(payload.get("policy_decision", "allow") or "allow")

        with self._lock:
            self._counters["events_total"] += 1
            self._counters[f"status:{status}"] += 1
            self._counters[f"policy_decision:{decision}"] += 1
            self._append_jsonl(payload)
            self._last_snapshot = self._snapshot_locked()
            return dict(self._last_snapshot)

    def snapshot_metrics(self) -> Dict[str, Any]:
        with self._lock:
            if not self._last_snapshot:
                self._last_snapshot = self._snapshot_locked()
            return dict(self._last_snapshot)

    def build_replay_payload(
        self,
        *,
        envelope: Dict[str, Any],
        governance: Dict[str, Any],
        action_id: str,
        action_args: Dict[str, Any],
        result_status: str,
        result_reason: str,
        latency_ms: int,
        loop_index: int,
    ) -> Dict[str, Any]:
        policy_decision = governance.get("policy_decision") if isinstance(governance.get("policy_decision"), dict) else {}
        explanation = policy_decision.get("explanation") if isinstance(policy_decision.get("explanation"), dict) else {}
        return {
            "ts": time.time(),
            "loop": int(loop_index),
            "action_id": str(action_id or ""),
            "action_args": dict(action_args or {}),
            "result_status": str(result_status or "unknown"),
            "result_reason": str(result_reason or ""),
            "latency_ms": int(latency_ms),
            "execution_context_envelope": dict(envelope or {}),
            "policy_decision": {
                "decision": str(policy_decision.get("decision", "allow") or "allow"),
                "policy_mode": str(policy_decision.get("policy_mode", "log_only") or "log_only"),
                "explanation_id": str(explanation.get("explanation_id", "") or ""),
                "reason": str(explanation.get("reason", "") or ""),
            },
        }

    def _append_jsonl(self, payload: Dict[str, Any]) -> None:
        with open(self._events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _snapshot_locked(self) -> Dict[str, Any]:
        events_total = int(self._counters.get("events_total", 0))
        success = int(self._counters.get("status:success", 0))
        failure = int(self._counters.get("status:failure", 0))
        deny = int(self._counters.get("policy_decision:deny", 0))
        require_approval = int(self._counters.get("policy_decision:require_approval", 0))
        return {
            "enabled": bool(self._enabled),
            "events_total": events_total,
            "success_total": success,
            "failure_total": failure,
            "deny_total": deny,
            "require_approval_total": require_approval,
            "failure_rate": round((failure / events_total), 4) if events_total else 0.0,
        }
