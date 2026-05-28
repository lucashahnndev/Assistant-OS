from .capability import WegenaCapability

def create_capability(kernel=None, config=None):
    return WegenaCapability(kernel=kernel, config=config)

__all__ = ["WegenaCapability", "create_capability"]
