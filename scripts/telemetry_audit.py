from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.telemetry import audit_sessions, load_sessions, render_audit_summary


def _format_pairs(data: dict) -> list[str]:
    return [f"{key}: {value}" for key, value in data.items()]


def _recommendations(summary: dict) -> tuple[list[str], list[str]]:
    opportunities: list[str] = []
    low_priority: list[str] = []

    hint = summary.get("hint_effectiveness", {})
    hint_app = float(hint.get("hint_application_rate", 0.0) or 0.0)
    if hint_app < 0.4:
        opportunities.append("Hint application rate is low; tighten hint generation thresholds or adjust broker hint usage.")
    else:
        low_priority.append("Hint application rate is healthy; no immediate tuning required.")

    outcome = summary.get("outcome_coverage", {})
    generic_outcomes = int(outcome.get("generic_outcomes", 0) or 0)
    if generic_outcomes > 0:
        opportunities.append("Generic outcome usage persists; review top generic branches for targeted mappings.")
    else:
        low_priority.append("Generic outcome usage is low; defer outcome taxonomy expansion.")

    evidence = summary.get("evidence_density", {})
    avg_chars = float(evidence.get("avg_evidence_chars", 0.0) or 0.0)
    if avg_chars > 1400:
        opportunities.append("Evidence payloads are large; tighten per-domain content limits or caps.")
    elif avg_chars < 200:
        opportunities.append("Evidence payloads are very small; check for over-suppression.")

    conflicts = summary.get("top_domain_conflicts", {})
    if conflicts:
        opportunities.append("Frequent domain conflicts detected; consider refining conflict resolution order.")
    else:
        low_priority.append("No dominant domain conflicts detected.")

    return opportunities[:6], low_priority[:6]


def build_markdown(summary: dict) -> str:
    opportunities, low_priority = _recommendations(summary)
    lines = [
        "# Real Session Telemetry Audit Report",
        "",
        "## 1. Executive Summary",
        f"- Sessions analyzed: {summary.get('session_count', 0)}",
        f"- Hint application rate: {summary.get('hint_effectiveness', {}).get('hint_application_rate', 0.0)}",
        f"- Avg evidence chars: {summary.get('evidence_density', {}).get('avg_evidence_chars', 0.0)}",
        "",
        "## 2. Domain Conflict Analysis",
        "Top conflicts:",
    ]
    lines += [f"- {item}" for item in _format_pairs(summary.get("top_domain_conflicts", {}))] or ["- none"]
    lines += ["Domain win ratio:"]
    lines += [f"- {item}" for item in _format_pairs(summary.get("domain_win_ratio", {}))] or ["- none"]
    lines += ["Domain suppression ratio:"]
    lines += [f"- {item}" for item in _format_pairs(summary.get("domain_suppression_ratio", {}))] or ["- none"]
    lines += [
        "",
        "## 3. Evidence Density Analysis",
    ]
    lines += [f"- {item}" for item in _format_pairs(summary.get("evidence_density", {}))] or ["- none"]
    lines += [
        "",
        "## 4. Hint Effectiveness Analysis",
    ]
    lines += [f"- {item}" for item in _format_pairs(summary.get("hint_effectiveness", {}))] or ["- none"]
    lines += [
        "",
        "## 5. Outcome Coverage Analysis",
    ]
    lines += [f"- {item}" for item in _format_pairs(summary.get("outcome_coverage", {}))] or ["- none"]
    lines += [
        "",
        "## 6. Cognitive Signal Usefulness",
    ]
    lines += [f"- {item}" for item in _format_pairs(summary.get("cognitive_signal", {}))] or ["- none"]
    lines += [
        "",
        "## 7. Prompt Evidence Effectiveness",
    ]
    lines += [f"- {item}" for item in _format_pairs(summary.get("prompt_evidence", {}))] or ["- none"]
    lines += [
        "",
        "## 8. High-Impact Tuning Opportunities",
    ]
    lines += [f"- {item}" for item in opportunities] or ["- none"]
    lines += [
        "",
        "## 9. Low-Priority Noise",
    ]
    lines += [f"- {item}" for item in low_priority] or ["- none"]
    lines += [
        "",
        "## 10. Recommended Next Tuning Pass",
        "- Prioritize the top two conflict patterns and top suppression ratio domains for the next tuning pass.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    base_dir = Path("data/sessions")
    sessions = load_sessions(base_dir)
    summary = audit_sessions(sessions)
    summary_dict = render_audit_summary(summary)

    report_path = Path("docs/reports/real-session-telemetry-audit-report.md")
    report_path.write_text(build_markdown(summary_dict), encoding="utf-8")


if __name__ == "__main__":
    main()
