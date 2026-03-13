from .browser_control_capability import BrowserControlCapability

def create_capability(kernel, config):
    return BrowserControlCapability(kernel, config)
