from .skill import WebRetrieveSkill


def create_skill(kernel, config):
    return WebRetrieveSkill(kernel, config)
