from .capability import WebRetrieveCapability


def create_capability(kernel, config):
    return WebRetrieveCapability(kernel, config)
