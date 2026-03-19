from .capability import SearxngSearchCapability


def create_capability(kernel, config):
    return SearxngSearchCapability(kernel, config)
