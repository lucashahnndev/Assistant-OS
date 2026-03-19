from .capability import YouTubeCapability


def create_capability(kernel, config):
    return YouTubeCapability(kernel, config)
