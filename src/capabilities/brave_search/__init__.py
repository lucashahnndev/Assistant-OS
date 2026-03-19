from .capability import BraveSearchCapability


def create_capability(kernel, config):
    return BraveSearchCapability(kernel, config)
