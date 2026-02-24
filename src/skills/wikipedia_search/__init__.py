from .skill import WikipediaSearchSkill


def create_skill(kernel, config):
    return WikipediaSearchSkill(kernel, config)
