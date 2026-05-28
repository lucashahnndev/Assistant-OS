from .capability import CloudflareTunnelCapability

def create_capability(kernel, config):
    return CloudflareTunnelCapability(kernel=kernel, config=config)
