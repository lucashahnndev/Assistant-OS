from .capability import WebCapability


def create_capability(kernel, config):
    return WebCapability(kernel, config)
