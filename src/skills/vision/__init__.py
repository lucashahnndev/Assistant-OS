from .skill import VisionSkill

def create_skill(kernel, config):
    return VisionSkill(kernel, config)
