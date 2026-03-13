from .capability import WikipediaSearchCapability


def create_capability(kernel, config):
    return WikipediaSearchCapability(kernel, config)
