import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.services.safety_service import SafetyService


def test_fs_list_outside_workspace_is_sensitive(tmp_path):
    service = SafetyService()
    service.set_workspace_dir(str(tmp_path / "workspace"))

    assert service.is_sensitive(
        "system.control.fs.list",
        {"path": "~/Downloads"},
        capability_registry=SimpleNamespace(get_action_metadata=lambda action_id: {}),
    ) is True


def test_fs_list_inside_workspace_is_not_sensitive(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    service = SafetyService()
    service.set_workspace_dir(str(workspace))

    assert service.is_sensitive(
        "system.control.fs.list",
        {"path": "docs"},
        capability_registry=SimpleNamespace(get_action_metadata=lambda action_id: {}),
    ) is False
