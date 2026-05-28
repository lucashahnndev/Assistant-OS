from .capability import NgrokTunnelCapability

def create_capability(kernel, config):
    return NgrokTunnelCapability(kernel=kernel, config=config)
