from .capability import DataAnalysisCapability


def create_capability(kernel, config):
    return DataAnalysisCapability(kernel, config)
