from .capability import DeepMemoryCapability


def create_capability(kernel, config):
    return DeepMemoryCapability(kernel, config)
