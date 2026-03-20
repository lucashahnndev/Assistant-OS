from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .contracts import ExecutionContextEnvelope
from .policy_layer import PolicyLayer


@dataclass
class PolicySimulationInput:
    envelope: Dict[str, Any]
    action_params: Dict[str, Any]
    policy_current: Dict[str, Any]
    policy_candidate: Optional[Dict[str, Any]] = None


class PolicySimulationMode:
    """Evaluates policy behavior without executing real actions."""

    def __init__(self, policy_layer: Optional[PolicyLayer] = None) -> None:
        self.policy_layer = policy_layer or PolicyLayer()

    def single_policy_eval(
        self,
        *,
        envelope_payload: Dict[str, Any],
        action_params: Dict[str, Any] | None = None,
        policy_cfg: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        decision = self._evaluate(
            envelope_payload=envelope_payload,
            action_params=action_params or {},
            policy_cfg=policy_cfg or {},
        )
        return {
            "mode": "single_policy_eval",
            "decision": decision,
        }

    def diff_eval(
        self,
        *,
        envelope_payload: Dict[str, Any],
        action_params: Dict[str, Any] | None = None,
        policy_current: Dict[str, Any] | None = None,
        policy_candidate: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        current = self._evaluate(
            envelope_payload=envelope_payload,
            action_params=action_params or {},
            policy_cfg=policy_current or {},
        )
        candidate = self._evaluate(
            envelope_payload=envelope_payload,
            action_params=action_params or {},
            policy_cfg=policy_candidate or {},
        )
        changed = self._decision_changed(current, candidate)
        return {
            "mode": "diff_eval",
            "current": current,
            "candidate": candidate,
            "changed": changed,
            "risk_delta": self._risk_delta(current, candidate),
        }

    def historical_replay_eval(
        self,
        *,
        events: Iterable[Dict[str, Any]],
        policy_current: Dict[str, Any] | None = None,
        policy_candidate: Dict[str, Any] | None = None,
        max_items: int = 500,
    ) -> Dict[str, Any]:
        rows = list(events)[: max(1, int(max_items))]
        comparisons: List[Dict[str, Any]] = []
        changed_count = 0

        for row in rows:
            envelope_payload, action_params = self._extract_event_payload(row)
            diff = self.diff_eval(
                envelope_payload=envelope_payload,
                action_params=action_params,
                policy_current=policy_current or {},
                policy_candidate=policy_candidate or {},
            )
            if diff.get("changed"):
                changed_count += 1
            dimensions = self._dimensions_from_envelope(envelope_payload)
            comparisons.append({"diff": diff, "dimensions": dimensions})

        aggregates = self._aggregate_dimensions(comparisons)
        return {
            "mode": "historical_replay_eval",
            "total_events": len(rows),
            "changed_events": changed_count,
            "change_rate": round((changed_count / len(rows)), 4) if rows else 0.0,
            "aggregates": aggregates,
            "comparisons": comparisons,
        }

    def _evaluate(
        self,
        *,
        envelope_payload: Dict[str, Any],
        action_params: Dict[str, Any],
        policy_cfg: Dict[str, Any],
    ) -> Dict[str, Any]:
        envelope = self._coerce_envelope(envelope_payload)
        decision = self.policy_layer.evaluate(
            envelope,
            action_params=action_params,
            policy_cfg=policy_cfg,
        )
        return decision.to_dict()

    @staticmethod
    def _coerce_envelope(payload: Dict[str, Any]) -> ExecutionContextEnvelope:
        obj = payload if isinstance(payload, dict) else {}
        return ExecutionContextEnvelope(
            envelope_version=str(obj.get("envelope_version", "1.0")),
            environment_mode=str(obj.get("environment_mode", "production")),
            sandbox_profile_id=str(obj.get("sandbox_profile_id", "")),
            tenant_id=str(obj.get("tenant_id", "default")),
            agent_id=str(obj.get("agent_id", "")),
            session_id=str(obj.get("session_id", "")),
            work_id=str(obj.get("work_id", "")),
            action_id=str(obj.get("action_id", "")),
            qos_class=str(obj.get("qos_class", "NORMAL")),
            risk_level=str(obj.get("risk_level", "low")),
            runtime_version=str(obj.get("runtime_version", "runtime_v2")),
            planner_version=str(obj.get("planner_version", "planner_v2")),
            policy_version=str(obj.get("policy_version", "policy_v1")),
            metadata=dict(obj.get("metadata", {}) or {}),
        )

    @staticmethod
    def _decision_changed(current: Dict[str, Any], candidate: Dict[str, Any]) -> bool:
        return str(current.get("decision", "")) != str(candidate.get("decision", ""))

    @staticmethod
    def _risk_delta(current: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
        cur = ((current.get("explanation") or {}).get("risk_level") if isinstance(current.get("explanation"), dict) else "")
        cand = ((candidate.get("explanation") or {}).get("risk_level") if isinstance(candidate.get("explanation"), dict) else "")
        return {
            "current": str(cur or ""),
            "candidate": str(cand or ""),
            "changed": str(cur or "") != str(cand or ""),
        }

    @staticmethod
    def _extract_event_payload(row: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        payload = row if isinstance(row, dict) else {}
        envelope = payload.get("execution_context_envelope")
        if not isinstance(envelope, dict):
            envelope = payload.get("envelope") if isinstance(payload.get("envelope"), dict) else {}
        action_params = payload.get("action_params")
        if not isinstance(action_params, dict):
            action_params = payload.get("args") if isinstance(payload.get("args"), dict) else {}
        return dict(envelope), dict(action_params)

    @staticmethod
    def _dimensions_from_envelope(envelope: Dict[str, Any]) -> Dict[str, str]:
        metadata = envelope.get("metadata") if isinstance(envelope.get("metadata"), dict) else {}
        return {
            "tenant": str(envelope.get("tenant_id", "default") or "default"),
            "domain": str(metadata.get("domain", "") or ""),
            "risk_level": str(envelope.get("risk_level", "low") or "low"),
            "page_type": str(metadata.get("page_type", "") or ""),
        }

    @staticmethod
    def _aggregate_dimensions(comparisons: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
        counters = {
            "tenant": Counter(),
            "domain": Counter(),
            "risk_level": Counter(),
            "page_type": Counter(),
        }
        for item in comparisons:
            if not isinstance(item, dict):
                continue
            diff = item.get("diff") if isinstance(item.get("diff"), dict) else {}
            if not diff.get("changed"):
                continue
            dims = item.get("dimensions") if isinstance(item.get("dimensions"), dict) else {}
            for key in counters.keys():
                value = str(dims.get(key, "") or "")
                if value:
                    counters[key][value] += 1
        return {key: dict(counter) for key, counter in counters.items()}
