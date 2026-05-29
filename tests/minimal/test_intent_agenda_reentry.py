import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from core.intents import IntentAgenda


def test_intent_reentry_requires_explicit_completion():
    agenda = IntentAgenda()
    intent = agenda.add_intent("Finish the report", linked_task_ids=["task_1"])
    agenda.update_intent_status(intent.intent_id, "PAUSED", blocking_reason="waiting")

    agenda.evaluate_reentry_signals({"task_1": {"status": "SUPERSEDED"}})
    assert agenda.get_intent(intent.intent_id).status == "PAUSED"

    agenda.evaluate_reentry_signals({"task_1": {"status": "COMPLETED"}})
    assert agenda.get_intent(intent.intent_id).status == "OPEN"


def test_intent_reentry_ignores_missing_tasks():
    agenda = IntentAgenda()
    intent = agenda.add_intent("Do something", linked_task_ids=["task_missing"])
    agenda.update_intent_status(intent.intent_id, "PAUSED", blocking_reason="waiting")

    agenda.evaluate_reentry_signals({})
    assert agenda.get_intent(intent.intent_id).status == "PAUSED"
