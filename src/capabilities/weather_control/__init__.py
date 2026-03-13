from .capability import WeatherCapability

def create_capability(kernel, config):
    return WeatherCapability(kernel, config)
