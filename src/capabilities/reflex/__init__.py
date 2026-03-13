from .capability import ReflexCapability

def create_capability(kernel, config):
    return ReflexCapability(kernel, config)
