from .browser_control_skill import BrowserControlSkill

def create_skill(kernel, config):
    return BrowserControlSkill(kernel, config)
