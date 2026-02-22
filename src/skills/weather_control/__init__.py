from .skill import WeatherSkill

def create_skill(kernel, config):
    return WeatherSkill(kernel, config)
