from src.capabilities.browser_control.browser_control_capability import BrowserControlCapability


def test_execution_context_includes_runtime_generic_fields_and_legacy_cdp_field():
    payload = BrowserControlCapability._build_execution_context(
        browser_instance_id="inst-1",
        tab_id="tab-1",
        debug_port=9222,
        cdp_target_id="target-1",
        runtime_backend="playwright",
        intent_class="automacao_ui",
        reused=True,
        policy_decision={"route": "new_instance"},
    )
    assert payload["runtime_backend"] == "playwright"
    assert payload["runtime_target_id"] == "target-1"
    assert payload["cdp_target_id"] == "target-1"
