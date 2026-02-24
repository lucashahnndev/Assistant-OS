from .skill import DeepMemorySkill


def create_skill(kernel, config):
    return DeepMemorySkill(kernel, config)
