from .capability import YouTubeRetrieveCapability


def create_capability(kernel, config):
    return YouTubeRetrieveCapability(kernel, config)
