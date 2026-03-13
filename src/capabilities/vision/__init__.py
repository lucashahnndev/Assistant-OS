from .capability import VisionCapability

def create_capability(kernel, config):
    return VisionCapability(kernel, config)
