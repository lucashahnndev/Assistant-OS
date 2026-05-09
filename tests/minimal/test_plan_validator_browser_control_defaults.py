from core.plan_validator import PlanValidator
from core.resolution.action_plan import ActionPlan


class _CapRegistry:
    def get_capability_for_action(self, action_id):
        if action_id == "browser.control.run":
            return object()
        return None

    def get_action_metadata(self, action_id):
        if action_id != "browser.control.run":
            return {}
        return {
            "parameters": {
                "type": "object",
                "properties": {
                    "intent_class": {
                        "type": "string",
                        "enum": [
                            "controlar_midia",
                            "realizar_pesquisa",
                            "automacao_ui",
                            "validacao_visual",
                            "manutencao",
                        ],
                    }
                },
                "required": ["intent_class"],
                "additionalProperties": True,
            }
        }


class _Session:
    tool_health = {}
    drivers_state = {}


def test_plan_validator_does_not_mutate_browser_control_args():
    plan = ActionPlan(
        action_id="browser.control.run",
        args={"goal": "abrir amazon e buscar ps4"},
        confidence=0.9,
        source="llm",
    )
    result = PlanValidator.validate(
        plan=plan,
        capability_registry=_CapRegistry(),
        session=_Session(),
        context={},
    )
    assert result.is_valid is False
    assert plan.args == {"goal": "abrir amazon e buscar ps4"}
