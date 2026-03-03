from .skill import YouTubeRetrieveSkill


def create_skill(kernel, config):
    return YouTubeRetrieveSkill(kernel, config)
