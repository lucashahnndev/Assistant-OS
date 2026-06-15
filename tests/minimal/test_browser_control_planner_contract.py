import asyncio

from src.capabilities.browser_control.planner import BrowserSubagent


class _RuntimeStub:
    target_id = ""


class _LLMManagerStub:
    def __init__(self, result, error=None):
        self.chat_pool = object()
        self._result = result
        self._error = error

    def _execute_with_router(self, pool, method, **kwargs):
        return self._result, self._error


def _build_state():
    return {
        "url": "https://example.com",
        "title": "Example",
        "candidates": [],
        "markers": [],
        "focus": {},
        "total_nodes": 0,
        "viewport_count": 0,
    }


def test_structured_completion_signal_advances_without_legacy_thought_matching():
    agent = BrowserSubagent(_RuntimeStub(), object())
    agent._plan = ["step 1", "step 2", "step 3"]
    agent._current_step_idx = 0

    contract = agent._build_browser_contract_state(
        thought_data={
            "thought": "step 9 completed",
            "browser_step": {
                "current_step_index": 1,
                "completed_step_index": 1,
                "next_step_index": 2,
                "step_status": "completed",
            },
            "completion_signal": {
                "status": "completed",
                "reason": "verified",
                "evidence": [{"kind": "marker", "value": "done"}],
            },
            "next_action": {"action": "wait", "args": {"seconds": 1}},
        },
        state=_build_state(),
        parse_status="ok",
    )

    agent._apply_browser_contract_progress(contract)

    assert contract["source"] == "browser_control"
    assert contract["agent_role"] == "subagent"
    assert contract["semantic_authority"] == "internal_browser_only"
    assert contract["not_user_facing"] is True
    assert contract["not_atlas_primary_thought"] is True
    assert contract["planner_diagnostic"]["legacy_thought_matching_used"] is False
    assert agent._current_step_idx == 2
    assert contract["browser_step"]["current_step_index"] == 2
    assert contract["browser_step"]["next_step_index"] == 2
    assert contract["completion_signal"]["completed_step_index"] == 1


def test_structured_step_indexes_override_contradictory_thought_text():
    agent = BrowserSubagent(_RuntimeStub(), object())
    agent._plan = ["step 1", "step 2", "step 3"]
    agent._current_step_idx = 0

    contract = agent._build_browser_contract_state(
        thought_data={
            "thought": "step 3 completed",
            "browser_step": {
                "current_step_index": 1,
                "completed_step_index": 1,
                "next_step_index": 2,
                "step_status": "completed",
            },
            "completion_signal": {
                "status": "completed",
                "reason": "structured evidence wins",
                "evidence": [{"kind": "dom", "value": "search results"}],
            },
        },
        state=_build_state(),
        parse_status="ok",
    )

    agent._apply_browser_contract_progress(contract)

    assert contract["planner_diagnostic"]["legacy_thought_matching_used"] is False
    assert agent._current_step_idx == 2
    assert contract["browser_step"]["current_step_index"] == 2
    assert contract["browser_step"]["next_step_index"] == 2


def test_legacy_thought_matching_still_works_temporarily_and_is_diagnosed():
    agent = BrowserSubagent(_RuntimeStub(), object())
    agent._plan = ["step 1", "step 2", "step 3"]
    agent._current_step_idx = 0

    contract = agent._build_browser_contract_state(
        thought_data={
            "thought": "Milestone 2 reached",
            "action": "wait",
            "args": {"seconds": 1},
        },
        state=_build_state(),
        parse_status="ok",
    )

    agent._apply_browser_contract_progress(contract)

    assert contract["planner_diagnostic"]["legacy_thought_matching_used"] is True
    assert contract["planner_diagnostic"]["fallback_reason"] == "legacy_thought_matching"
    assert agent._current_step_idx == 2


def test_think_empty_output_and_invalid_json_remain_structured_diagnostics():
    empty_agent = BrowserSubagent(_RuntimeStub(), _LLMManagerStub(""))
    empty_agent._plan = ["step 1", "step 2"]
    empty_contract = asyncio.run(empty_agent._think("go somewhere", _build_state(), []))

    assert empty_contract["source"] == "browser_control"
    assert empty_contract["planner_diagnostic"]["parse_status"] == "provider_empty_output"
    assert empty_contract["planner_diagnostic"]["legacy_thought_matching_used"] is False
    assert empty_contract["planner_diagnostic"]["fallback_reason"] == "provider_empty_output"
    assert empty_contract["semantic_authority"] == "internal_browser_only"

    invalid_agent = BrowserSubagent(_RuntimeStub(), _LLMManagerStub(None, "invalid json from provider"))
    invalid_agent._plan = ["step 1", "step 2"]
    invalid_contract = asyncio.run(invalid_agent._think("go somewhere", _build_state(), []))

    assert invalid_contract["source"] == "browser_control"
    assert invalid_contract["planner_diagnostic"]["parse_status"] == "invalid_json"
    assert invalid_contract["planner_diagnostic"]["legacy_thought_matching_used"] is False
    assert invalid_contract["planner_diagnostic"]["fallback_reason"] == "provider_contract_error"
    assert invalid_contract["not_user_facing"] is True
