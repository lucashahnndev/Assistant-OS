from .capability import OpenAlexSearchCapability


def create_capability(kernel, config):
    return OpenAlexSearchCapability(kernel, config)
