import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.drivers.interfaces.system_driver import SystemDriver


class _WorkspaceServiceStub:
    def __init__(self, workspace_dir: str):
        self._workspace_dir = workspace_dir

    def get_workspace_dir(self):
        return self._workspace_dir


class _KernelStub:
    def __init__(self, workspace_dir: str):
        self.workspace_service = _WorkspaceServiceStub(workspace_dir)


def test_system_driver_fs_list_supports_home_downloads(monkeypatch, tmp_path):
    home_dir = tmp_path / "home"
    downloads_dir = home_dir / "Downloads"
    downloads_dir.mkdir(parents=True)
    (downloads_dir / "report.txt").write_text("hello", encoding="utf-8")

    monkeypatch.setenv("HOME", str(home_dir))

    driver = SystemDriver(_KernelStub(str(tmp_path / "workspace")))
    result = driver.fs_list("~/Downloads")

    assert isinstance(result, list)
    assert result[0]["name"] == "report.txt"
    assert result[0]["is_dir"] is False
