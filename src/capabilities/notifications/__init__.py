from .capability import NotificationCapability

def create_capability(kernel, config):
    return NotificationCapability(kernel=kernel, config=config)

__all__ = ["NotificationCapability", "create_capability"]
