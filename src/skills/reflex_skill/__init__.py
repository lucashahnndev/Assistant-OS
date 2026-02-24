from .skill import ReflexSkill

def create_skill(kernel, config):
    return ReflexSkill(kernel, config)
