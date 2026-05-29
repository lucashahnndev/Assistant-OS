import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.drivers.interfaces.telegram.telegram_driver import TelegramDriver


def test_telegram_send_status_accepts_model_info_argument():
    driver = TelegramDriver(kernel=None, parent_dir=str(ROOT))
    driver.bot = None

    driver.send_status("telegram_12345", "thinking", {"code": "ack"}, model_info="gemini-3.1-flash-lite")
