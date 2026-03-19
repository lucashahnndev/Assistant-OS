from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


CONFLICT_TAGS = {
    "external:suppressed:custom_present": ("custom_knowledge", "external_knowledge"),
    "external:suppressed:custom_focus": ("custom_knowledge", "external_knowledge"),
    "examples:suppressed:capability_present": ("capability_knowledge", "examples"),
    "examples:suppressed:procedures_present": ("procedures", "examples"),
    "agent_experience:suppressed:no_troubleshooting": ("procedures", "agent_experience"),
    "policies:suppressed": ("procedures", "policies"),
}


@dataclass
class SessionTelemetry:
    session_id: str
    source: str
    cognitive_counters: Dict[str, Any] = field(default_factory=dict)
    cognitive_diag: Dict[str, Any] = field(default_factory=dict)
    broker_diag: Dict[str, Any] = field(default_factory=dict)
    prompt_metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TelemetryAuditSummary:
    session_count: int = 0
    domain_conflict_frequency: Dict[str, int] = field(default_factory=dict)
    domain_win_ratio: Dict[str, float] = field(default_factory=dict)
    domain_suppression_ratio: Dict[str, float] = field(default_factory=dict)
    evidence_density: Dict[str, float] = field(default_factory=dict)
    hint_effectiveness: Dict[str, float] = field(default_factory=dict)
    outcome_coverage: Dict[str, Any] = field(default_factory=dict)
    cognitive_signal: Dict[str, Any] = field(default_factory=dict)
    prompt_evidence: Dict[str, Any] = field(default_factory=dict)


def load_sessions(base_dir: str | Path) -> List[SessionTelemetry]:
    base = Path(base_dir)
    sessions: List[SessionTelemetry] = []
    for session_file in base.glob("*/session.json"):
        payload = _load_json(session_file)
        if not payload:
            continue
        session_id = str(payload.get("session_id") or session_file.parent.name)
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        broker_diag = context.get("last_context_broker") if isinstance(context.get("last_context_broker"), dict) else {}
        cognitive_diag = context.get("last_cognitive_layer") if isinstance(context.get("last_cognitive_layer"), dict) else {}
        counters = context.get("cognitive_effectiveness_counters") if isinstance(context.get("cognitive_effectiveness_counters"), dict) else {}
        prompt_metrics = {}
        if isinstance(broker_diag, dict):
            prompt_metrics = broker_diag.get("prompt_reduction") if isinstance(broker_diag.get("prompt_reduction"), dict) else {}

        sessions.append(
            SessionTelemetry(
                session_id=session_id,
                source=str(payload.get("source") or ""),
                cognitive_counters=dict(counters),
                cognitive_diag=dict(cognitive_diag),
                broker_diag=dict(broker_diag),
                prompt_metrics=dict(prompt_metrics),
            )
        )
    return sessions


def audit_sessions(sessions: Iterable[SessionTelemetry]) -> TelemetryAuditSummary:
    session_list = list(sessions)
    if not session_list:
        return TelemetryAuditSummary()

    conflict_counts = Counter()
    domain_wins = Counter()
    domain_suppressed = Counter()
    evidence_counts = Counter()
    evidence_chars = []
    evidence_turns = 0
    density_reductions = []
    low_value_suppressed = []

    hints_generated = 0
    hints_applied = 0
    hints_ignored = 0
    hints_suppressed = 0

    outcome_counts = Counter()
    generic_outcomes = 0
    generic_streak_max = 0

    fields_populated = Counter()
    fields_projected = Counter()
    commit_signal = Counter()
    planner_relevance_turns = 0

    prompt_evidence_chars = []
    prompt_evidence_counts = []
    prompt_evidence_domains = Counter()

    for session in session_list:
        broker = session.broker_diag
        cognitive = session.cognitive_diag
        counters = session.cognitive_counters

        conflict_summary = broker.get("domain_conflict_resolution_summary") if isinstance(broker.get("domain_conflict_resolution_summary"), list) else []
        for entry in conflict_summary:
            tag = str(entry)
            conflict_counts[tag] += 1
            if tag in CONFLICT_TAGS:
                winner, loser = CONFLICT_TAGS[tag]
                domain_wins[winner] += 1
                domain_suppressed[loser] += 1

        for key, value in (broker.get("evidence_counts_by_domain_selected") or {}).items():
            evidence_counts[str(key)] += int(value or 0)
        for key, value in (broker.get("evidence_counts_by_domain_suppressed") or {}).items():
            domain_suppressed[str(key)] += int(value or 0)

        total_chars = int(broker.get("total_evidence_chars") or 0)
        if int(broker.get("evidence_count") or 0) > 0:
            evidence_turns += 1
            evidence_chars.append(total_chars)
        density_reductions.append(int(broker.get("evidence_density_reduction_count") or 0))
        low_value_suppressed.append(int(broker.get("low_value_suppressed_count") or 0))

        hints_generated += int(counters.get("hints_generated") or 0)
        hints_applied += int(counters.get("hints_applied") or 0)
        hints_ignored += int(counters.get("hints_ignored") or 0)
        hints_suppressed += int(counters.get("hint_suppressed_count") or 0)

        outcome_counts.update({k: int(v) for k, v in (counters.get("outcome_types") or {}).items()})
        generic_outcomes += int(counters.get("generic_outcomes") or 0)
        generic_streak_max = max(generic_streak_max, int(counters.get("generic_outcome_streak") or 0))

        for field in list(cognitive.get("cognitive_fields_populated") or []):
            fields_populated[str(field)] += 1
        for field in list(cognitive.get("cognitive_fields_projected") or []):
            fields_projected[str(field)] += 1
        commit_signal[str(cognitive.get("commit_signal_strength") or "none")] += 1
        if bool(cognitive.get("planner_relevance_signal")):
            planner_relevance_turns += 1

        prompt_metrics = session.prompt_metrics
        if prompt_metrics:
            prompt_evidence_chars.append(int(prompt_metrics.get("evidence_density_metrics", {}).get("evidence_chars", 0)))
            prompt_evidence_counts.append(int(prompt_metrics.get("evidence_item_count") or 0))
            for domain in list(prompt_metrics.get("evidence_domains") or []):
                prompt_evidence_domains[str(domain)] += 1

    session_count = len(session_list)
    evidence_avg = _safe_avg(evidence_chars)
    density_avg = _safe_avg(density_reductions)
    low_value_avg = _safe_avg(low_value_suppressed)
    prompt_evidence_avg = _safe_avg(prompt_evidence_chars)
    prompt_item_avg = _safe_avg(prompt_evidence_counts)

    return TelemetryAuditSummary(
        session_count=session_count,
        domain_conflict_frequency=dict(conflict_counts.most_common(10)),
        domain_win_ratio=_ratio_map(domain_wins, domain_suppressed),
        domain_suppression_ratio=_ratio_map(domain_suppressed, evidence_counts),
        evidence_density={
            "avg_evidence_chars": evidence_avg,
            "avg_density_reduction": density_avg,
            "avg_low_value_suppressed": low_value_avg,
            "evidence_turns": evidence_turns,
        },
        hint_effectiveness={
            "hint_application_rate": _safe_ratio(hints_applied, hints_generated),
            "hint_noise_rate": _safe_ratio(hints_ignored, hints_generated),
            "hint_suppressed_rate": _safe_ratio(hints_suppressed, hints_generated),
        },
        outcome_coverage={
            "outcome_counts": dict(outcome_counts.most_common(12)),
            "generic_outcomes": generic_outcomes,
            "generic_outcome_streak_max": generic_streak_max,
        },
        cognitive_signal={
            "fields_populated": dict(fields_populated.most_common(10)),
            "fields_projected": dict(fields_projected.most_common(10)),
            "commit_signal_strength": dict(commit_signal),
            "planner_relevance_turns": planner_relevance_turns,
        },
        prompt_evidence={
            "avg_evidence_chars": prompt_evidence_avg,
            "avg_evidence_items": prompt_item_avg,
            "evidence_domain_mix": dict(prompt_evidence_domains.most_common(10)),
        },
    )


def render_audit_summary(summary: TelemetryAuditSummary) -> Dict[str, Any]:
    return {
        "session_count": summary.session_count,
        "top_domain_conflicts": summary.domain_conflict_frequency,
        "domain_win_ratio": summary.domain_win_ratio,
        "domain_suppression_ratio": summary.domain_suppression_ratio,
        "evidence_density": summary.evidence_density,
        "hint_effectiveness": summary.hint_effectiveness,
        "outcome_coverage": summary.outcome_coverage,
        "cognitive_signal": summary.cognitive_signal,
        "prompt_evidence": summary.prompt_evidence,
    }


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _safe_avg(values: Iterable[int]) -> float:
    values_list = list(values)
    if not values_list:
        return 0.0
    return round(sum(values_list) / len(values_list), 4)


def _safe_ratio(num: int, den: int) -> float:
    if not den:
        return 0.0
    return round(num / den, 4)


def _ratio_map(numerator: Counter, denominator: Counter) -> Dict[str, float]:
    result: Dict[str, float] = {}
    for key, value in numerator.items():
        denom = denominator.get(key, 0)
        if denom <= 0:
            result[str(key)] = 0.0
        else:
            result[str(key)] = round(value / denom, 4)
    return result
