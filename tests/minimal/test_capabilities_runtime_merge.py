import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.server.routes.capabilities import _merged_retrieval_runtime


def test_merged_retrieval_runtime_uses_control_plane_state():
    runtime = _merged_retrieval_runtime(
        capability_id="brave_search",
        runtime_offer_by_id={
            "brave_search": {"setup_ready": True, "domains": ["web"], "roles": ["search"]}
        },
        control_plane_overrides={"brave_search": {"disabled": True}},
        control_plane_scorecard={"brave_search": {"runtime_health": 0.2}},
    )
    assert runtime.get("disabled") is True
    assert runtime.get("runtime_health") == 0.2
    assert runtime.get("operational_state") == "disabled"


def test_merged_retrieval_runtime_setup_pending_when_not_ready():
    runtime = _merged_retrieval_runtime(
        capability_id="spotify_search",
        runtime_offer_by_id={
            "spotify_search": {"setup_ready": False, "missing_required_fields": ["auth.clientId"]}
        },
        control_plane_overrides={},
        control_plane_scorecard={},
    )
    assert runtime.get("setup_ready") is False
    assert runtime.get("operational_state") == "setup_pending"
