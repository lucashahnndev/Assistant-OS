from .capability import CommonCrawlSearchCapability


def create_capability(kernel, config):
    return CommonCrawlSearchCapability(kernel, config)
