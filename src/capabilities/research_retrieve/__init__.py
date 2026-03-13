from .capability import ResearchRetrieveCapability


def create_capability(kernel, config):
    return ResearchRetrieveCapability(kernel, config)
