from .capability import AssistiveOverlayCapability


def create_capability(kernel, config):
    return AssistiveOverlayCapability(kernel, config)
