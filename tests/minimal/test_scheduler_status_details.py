import os
import queue

from core.scheduler import Scheduler, WorkStatus


def test_work_status_change_publishes_structured_status_details(tmp_path):
    previous = os.environ.get("AOSD_DATA_DIR")
    try:
        os.environ["AOSD_DATA_DIR"] = str(tmp_path)
        event_bus = queue.Queue()
        scheduler = Scheduler(event_bus)
        work = scheduler.create_work(
            session_id="session-status",
            input_text="write report",
            initial_context={},
        )

        scheduler.update_work_context(
            work.work_id,
            {
                "summary": {
                    "outcome_type": "clarification_required",
                    "task_completed": False,
                    "task_progressed": False,
                    "approval_pending": False,
                    "clarification_required": True,
                    "fallback_used": True,
                    "execution_state": "clarification",
                    "final_response": "I need more context.",
                    "approval_prompt": "Please approve the write action.",
                    "cursor": "1/1",
                }
            },
        )

        scheduler.update_work_status(work.work_id, WorkStatus.RUNNING)
        scheduler.update_work_status(
            work.work_id,
            WorkStatus.SUCCEEDED,
            result="I need more context.",
            metadata={"worker": {"thread_name": "Worker-1", "result_type": "str"}},
        )

        snapshot = scheduler.get_work_snapshot(work.work_id, include_context=True)
        assert snapshot is not None
        status_details = snapshot.get("status_details") or {}
        assert status_details.get("work_status") == "succeeded"
        assert status_details.get("outcome_type") == "clarification_required"
        assert status_details.get("execution_state") == "clarification"
        assert status_details.get("clarification_required") is True
        assert status_details.get("fallback_used") is True
        assert status_details.get("worker", {}).get("thread_name") == "Worker-1"

        first_event = event_bus.get_nowait()
        second_event = event_bus.get_nowait()
        assert first_event["type"] == "work_status_change"
        assert first_event["status"] == "running"
        assert second_event["type"] == "work_status_change"
        assert second_event["status_details"]["execution_state"] == "clarification"
    finally:
        if previous is None:
            os.environ.pop("AOSD_DATA_DIR", None)
        else:
            os.environ["AOSD_DATA_DIR"] = previous
