from drivers.interfaces.system_driver import SystemDriver
from drivers.interfaces.voice.voice_driver import VoiceDriver


class _KernelStub:
    def __init__(self):
        self.workspace_service = type("_Ws", (), {"get_workspace_dir": lambda self: "/tmp"})()


def test_system_driver_send_status_accepts_model_info():
    driver = SystemDriver.__new__(SystemDriver)
    driver.kernel = _KernelStub()
    driver.send_status("session-1", "thinking", {"message": "ok"}, model_info={"model": "gemini"})


def test_voice_driver_send_status_accepts_model_info():
    driver = VoiceDriver.__new__(VoiceDriver)
    driver.send_status("session-1", "thinking", {"message": "ok"}, model_info={"model": "gemini"})
