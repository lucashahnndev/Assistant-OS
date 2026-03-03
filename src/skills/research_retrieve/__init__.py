from .skill import ResearchRetrieveSkill


def create_skill(kernel, config):
    return ResearchRetrieveSkill(kernel, config)
