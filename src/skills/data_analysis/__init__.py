from .skill import DataAnalysisSkill


def create_skill(kernel, config):
    return DataAnalysisSkill(kernel, config)
