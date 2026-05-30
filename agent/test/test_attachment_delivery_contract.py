import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.core.observation import ActionObservation
from src.drivers.interfaces.telegram.telegram_driver import TelegramDriver


def test_action_observation_records_attachment_delivery_state():
    obs = ActionObservation.from_execution(
        action_name="shell.control.execute",
        status="success",
        result_summary="done",
        structured_result={"status": "success"},
        raw_result_preview="ok",
        source_args={"cmd": "ls"},
        work_id="w1",
        turn_id=7,
        attachment_delivery={
            "requested": ["/tmp/a.png"],
            "resolved": [{"path": "/tmp/a.png", "name": "a.png"}],
            "prepared": [{"path": "/tmp/a.png", "name": "a.png"}],
            "sent": [],
            "errors": [],
            "bridge": "telegram",
            "source_action": "shell.control.execute",
            "status": "prepared",
            "confirmed": False,
        },
    )

    payload = obs.to_dict()
    state_update = obs.to_state_summary_update()

    assert payload["attachment_delivery"]["status"] == "prepared"
    assert state_update["last_attachment_delivery_status"] == "prepared"
    assert state_update["last_attachment_delivery_prepared_count"] == 1
    assert state_update["last_attachment_delivery_sent_count"] == 0
    assert "attachment_delivery=status=prepared" in obs.to_prompt_summary()


def test_telegram_driver_returns_structured_delivery_report_for_attachments():
    class _FakeBot:
        def send_message_to(self, chat_id, text):
            return {"chat_id": str(chat_id), "text": text}

        def send_action_to(self, chat_id, action="typing"):
            return None

        def send_file_to(self, chat_id, file_path, caption=None):
            return {
                "bridge": "telegram",
                "status": "sent",
                "path": file_path,
                "chat_id": str(chat_id),
                "message_id": "msg-123",
                "kind": "document",
            }

    driver = TelegramDriver(kernel=SimpleNamespace(), parent_dir=str(ROOT))
    driver.bot = _FakeBot()

    report = driver.send_response(
        "Aqui está o arquivo.",
        target="telegram_123",
        attachments=[{"path": "/tmp/a.txt", "name": "a.txt"}],
    )

    assert report["bridge"] == "telegram"
    assert report["status"] == "sent"
    assert report["sent_attachments"][0]["status"] == "sent"
    assert report["sent_attachments"][0]["message_id"] == "msg-123"
