from .skill import AssistiveOverlaySkill


def create_skill(kernel, config):
    return AssistiveOverlaySkill(kernel, config)
