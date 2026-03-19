from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping


@dataclass(slots=True)
class ProviderRuntimeState:
    provider: str
    disabled: bool = False
    degraded: bool = False
    force_fallback: bool = False
    quota_exceeded: bool = False
    error_previous: bool = False
    setup_ready: bool = True
    runtime_health: float = 0.75
    success_rate: float = 0.75
    latency_ms: int = 1200
    cost: float = 0.0
    user_context_boost: float = 0.0
    historical_performance: float = 0.5
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "disabled": bool(self.disabled),
            "degraded": bool(self.degraded),
            "force_fallback": bool(self.force_fallback),
            "quota_exceeded": bool(self.quota_exceeded),
            "error_previous": bool(self.error_previous),
            "setup_ready": bool(self.setup_ready),
            "runtime_health": float(self.runtime_health),
            "success_rate": float(self.success_rate),
            "latency_ms": int(self.latency_ms),
            "cost": float(self.cost),
            "user_context_boost": float(self.user_context_boost),
            "historical_performance": float(self.historical_performance),
            "notes": self.notes,
        }


@dataclass(slots=True)
class ProviderControlPlane:
    states: Dict[str, ProviderRuntimeState] = field(default_factory=dict)

    @classmethod
    def from_constraints(cls, constraints: Mapping[str, Any] | None) -> "ProviderControlPlane":
        raw = constraints if isinstance(constraints, Mapping) else {}
        overrides = raw.get("provider_runtime_overrides") if isinstance(raw.get("provider_runtime_overrides"), Mapping) else {}
        scorecard = raw.get("provider_runtime_scorecard") if isinstance(raw.get("provider_runtime_scorecard"), Mapping) else {}

        states: Dict[str, ProviderRuntimeState] = {}
        providers = set(overrides.keys()) | set(scorecard.keys())
        for provider in providers:
            ov = overrides.get(provider) if isinstance(overrides.get(provider), Mapping) else {}
            sc = scorecard.get(provider) if isinstance(scorecard.get(provider), Mapping) else {}
            state = ProviderRuntimeState(
                provider=str(provider),
                disabled=bool(ov.get("disabled", False)),
                degraded=bool(ov.get("degraded", False)),
                force_fallback=bool(ov.get("force_fallback", False)),
                quota_exceeded=bool(ov.get("quota_exceeded", False)),
                error_previous=bool(ov.get("error_previous", False)),
                setup_ready=bool(ov.get("setup_ready", True)),
                runtime_health=cls._clamp_float(sc.get("runtime_health"), 0.75),
                success_rate=cls._clamp_float(sc.get("success_rate"), 0.75),
                latency_ms=cls._clamp_int(sc.get("latency_ms"), 1200),
                cost=cls._clamp_float(sc.get("cost"), 0.0),
                user_context_boost=cls._clamp_float(sc.get("user_context_boost"), 0.0),
                historical_performance=cls._clamp_float(sc.get("historical_performance"), 0.5),
                notes=str(ov.get("notes") or sc.get("notes") or "").strip(),
            )
            states[str(provider)] = state
        return cls(states=states)

    def state_for(self, provider: str) -> ProviderRuntimeState:
        return self.states.get(str(provider), ProviderRuntimeState(provider=str(provider)))

    def to_trace(self) -> Dict[str, Any]:
        return {name: state.to_dict() for name, state in sorted(self.states.items())}

    @staticmethod
    def _clamp_float(value: Any, default: float) -> float:
        try:
            n = float(value)
        except Exception:
            n = default
        return max(0.0, min(1.0, n))

    @staticmethod
    def _clamp_int(value: Any, default: int) -> int:
        try:
            n = int(value)
        except Exception:
            n = default
        return max(0, n)
