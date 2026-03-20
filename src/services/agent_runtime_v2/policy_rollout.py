from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

from config.manager import ConfigManager


class PolicyRolloutEngine:
    """Lifecycle and tenant-targeted rollout/rollback for runtime v2 policy."""

    ALLOWED_TRANSITIONS = {
        "draft": {"simulated", "deprecated"},
        "simulated": {"canary", "deprecated"},
        "canary": {"active", "rolled_back", "deprecated"},
        "active": {"deprecated", "rolled_back"},
        "deprecated": set(),
        "rolled_back": set(),
    }

    def __init__(self, config_manager: Optional[Any] = None) -> None:
        self.config_manager = config_manager or ConfigManager()
        base = getattr(self.config_manager, "base_data_dir", None) or ConfigManager.get_data_dir()
        root = os.path.join(str(base), "runtime_v2")
        os.makedirs(root, exist_ok=True)
        self._path = os.path.join(root, "policy_rollouts.json")
        self._lock = threading.Lock()
        self._state = self._load_state()

    def create_draft(self, *, policy_id: str, policy_cfg: Dict[str, Any], created_by: str = "") -> Dict[str, Any]:
        pid = str(policy_id or "").strip()
        if not pid:
            return {"ok": False, "error_code": "INVALID_POLICY_ID"}
        with self._lock:
            if pid in self._state["policies"]:
                return {"ok": False, "error_code": "POLICY_ALREADY_EXISTS"}
            self._state["policies"][pid] = {
                "policy_id": pid,
                "state": "draft",
                "policy_cfg": dict(policy_cfg or {}),
                "created_at": time.time(),
                "updated_at": time.time(),
                "created_by": str(created_by or ""),
                "canary": {},
                "metrics": {},
            }
            self._append_event("created", {"policy_id": pid, "state": "draft"})
            self._save_state()
            return {"ok": True, "policy": dict(self._state["policies"][pid])}

    def mark_simulated(self, *, policy_id: str, simulation_result: Dict[str, Any]) -> Dict[str, Any]:
        return self._transition(
            policy_id=policy_id,
            to_state="simulated",
            patch={"metrics": {"simulation": dict(simulation_result or {})}},
            event="simulated",
        )

    def start_canary(
        self,
        *,
        policy_id: str,
        tenant_ids: Optional[List[str]] = None,
        rollout_percent: float = 0.0,
        qos_classes: Optional[List[str]] = None,
        risk_levels: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        patch = {
            "canary": {
                "tenant_ids": [str(x).strip() for x in (tenant_ids or []) if str(x).strip()],
                "rollout_percent": float(max(0.0, min(100.0, rollout_percent))),
                "qos_classes": [str(x).strip().upper() for x in (qos_classes or []) if str(x).strip()],
                "risk_levels": [str(x).strip().lower() for x in (risk_levels or []) if str(x).strip()],
                "started_at": time.time(),
            }
        }
        return self._transition(policy_id=policy_id, to_state="canary", patch=patch, event="canary_started")

    def promote_active(self, *, policy_id: str, tenant_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        with self._lock:
            current = self._state["policies"].get(str(policy_id or "").strip())
            if not current:
                return {"ok": False, "error_code": "POLICY_NOT_FOUND"}
            state = str(current.get("state", ""))
            if "active" not in self.ALLOWED_TRANSITIONS.get(state, set()):
                return {"ok": False, "error_code": "INVALID_STATE_TRANSITION", "from_state": state, "to_state": "active"}
            current["state"] = "active"
            current["updated_at"] = time.time()
            targets = [str(x).strip() for x in (tenant_ids or []) if str(x).strip()]
            if targets:
                for tenant in targets:
                    self._state["active_by_tenant"][tenant] = str(current["policy_id"])
            else:
                self._state["active_global"] = str(current["policy_id"])
            self._append_event("promoted_active", {"policy_id": current["policy_id"], "tenant_ids": targets})
            self._save_state()
            return {"ok": True, "policy": dict(current), "active_global": self._state.get("active_global", "")}

    def rollback(self, *, policy_id: str, reason: str = "") -> Dict[str, Any]:
        with self._lock:
            pid = str(policy_id or "").strip()
            current = self._state["policies"].get(pid)
            if not current:
                return {"ok": False, "error_code": "POLICY_NOT_FOUND"}
            state = str(current.get("state", ""))
            if "rolled_back" not in self.ALLOWED_TRANSITIONS.get(state, set()):
                return {"ok": False, "error_code": "INVALID_STATE_TRANSITION", "from_state": state, "to_state": "rolled_back"}
            current["state"] = "rolled_back"
            current["updated_at"] = time.time()
            if self._state.get("active_global") == pid:
                self._state["active_global"] = ""
            stale_tenants = [tenant for tenant, active in self._state.get("active_by_tenant", {}).items() if active == pid]
            for tenant in stale_tenants:
                self._state["active_by_tenant"].pop(tenant, None)
            self._append_event("rolled_back", {"policy_id": pid, "reason": str(reason or "")})
            self._save_state()
            return {"ok": True, "policy": dict(current)}

    def evaluate_canary_regression(
        self,
        *,
        policy_id: str,
        metrics: Dict[str, Any],
        thresholds: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        cfg = thresholds or {}
        max_error_rate = float(cfg.get("max_error_rate", 0.2))
        max_latency_increase = float(cfg.get("max_latency_increase", 0.5))
        error_rate = float(metrics.get("error_rate", 0.0) or 0.0)
        latency_increase = float(metrics.get("latency_increase", 0.0) or 0.0)
        should_abort = (error_rate > max_error_rate) or (latency_increase > max_latency_increase)
        if not should_abort:
            return {"ok": True, "abort": False, "metrics": dict(metrics or {})}
        rollback = self.rollback(policy_id=policy_id, reason="canary_regression")
        return {
            "ok": bool(rollback.get("ok")),
            "abort": True,
            "rollback": rollback,
            "metrics": dict(metrics or {}),
            "thresholds": {"max_error_rate": max_error_rate, "max_latency_increase": max_latency_increase},
        }

    def resolve_effective_policy(
        self,
        *,
        tenant_id: str,
        default_policy_cfg: Dict[str, Any],
    ) -> Dict[str, Any]:
        tenant = str(tenant_id or "default").strip() or "default"
        with self._lock:
            tenant_policy_id = str((self._state.get("active_by_tenant") or {}).get(tenant, "") or "")
            if tenant_policy_id:
                policy = self._state["policies"].get(tenant_policy_id)
                if policy and str(policy.get("state")) == "active":
                    return dict(policy.get("policy_cfg", {}) or {})

            for policy in self._state["policies"].values():
                if str(policy.get("state", "")) != "canary":
                    continue
                canary = policy.get("canary") if isinstance(policy.get("canary"), dict) else {}
                tenant_ids = {str(x).strip() for x in (canary.get("tenant_ids") or []) if str(x).strip()}
                if tenant in tenant_ids:
                    return dict(policy.get("policy_cfg", {}) or {})

            global_policy_id = str(self._state.get("active_global", "") or "")
            if global_policy_id:
                policy = self._state["policies"].get(global_policy_id)
                if policy and str(policy.get("state")) == "active":
                    return dict(policy.get("policy_cfg", {}) or {})

        return dict(default_policy_cfg or {})

    def get_policy(self, policy_id: str) -> Dict[str, Any]:
        with self._lock:
            item = self._state["policies"].get(str(policy_id or "").strip())
            return dict(item or {})

    def list_policies(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(v) for v in self._state["policies"].values()]

    def _transition(self, *, policy_id: str, to_state: str, patch: Dict[str, Any], event: str) -> Dict[str, Any]:
        pid = str(policy_id or "").strip()
        with self._lock:
            current = self._state["policies"].get(pid)
            if not current:
                return {"ok": False, "error_code": "POLICY_NOT_FOUND"}
            from_state = str(current.get("state", ""))
            if str(to_state) not in self.ALLOWED_TRANSITIONS.get(from_state, set()):
                return {
                    "ok": False,
                    "error_code": "INVALID_STATE_TRANSITION",
                    "from_state": from_state,
                    "to_state": to_state,
                }
            current["state"] = str(to_state)
            self._deep_merge(current, patch or {})
            current["updated_at"] = time.time()
            self._append_event(event, {"policy_id": pid, "from_state": from_state, "to_state": to_state})
            self._save_state()
            return {"ok": True, "policy": dict(current)}

    @staticmethod
    def _deep_merge(target: Dict[str, Any], patch: Dict[str, Any]) -> None:
        for key, value in patch.items():
            current = target.get(key)
            if isinstance(current, dict) and isinstance(value, dict):
                PolicyRolloutEngine._deep_merge(current, value)
            else:
                target[key] = value

    def _append_event(self, event: str, payload: Dict[str, Any]) -> None:
        self._state.setdefault("events", []).append(
            {
                "ts": time.time(),
                "event": str(event or ""),
                "payload": dict(payload or {}),
            }
        )
        if len(self._state["events"]) > 2000:
            self._state["events"] = self._state["events"][-2000:]

    def _load_state(self) -> Dict[str, Any]:
        if not os.path.exists(self._path):
            return {"policies": {}, "active_global": "", "active_by_tenant": {}, "events": []}
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                raise ValueError("invalid payload")
            payload.setdefault("policies", {})
            payload.setdefault("active_global", "")
            payload.setdefault("active_by_tenant", {})
            payload.setdefault("events", [])
            return payload
        except Exception:
            return {"policies": {}, "active_global": "", "active_by_tenant": {}, "events": []}

    def _save_state(self) -> None:
        tmp = f"{self._path}.tmp.{os.getpid()}.{threading.get_ident()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._path)
