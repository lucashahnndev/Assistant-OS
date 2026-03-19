from .capability import DdgSearchCapability


def create_capability(kernel, config):
    return DdgSearchCapability(kernel, config)
