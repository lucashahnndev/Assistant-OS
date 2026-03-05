from abc import ABC, abstractmethod

class ITTSProvider(ABC):
    def __init__(self, config):
        """
        Initialize the provider with configuration.
        :param config: Dictionary containing provider-specific settings.
        """
        self.config = config

    @abstractmethod
    def speak(self, text):
        """
        Synthesize and play speech from text locally.
        """
        return None

    @abstractmethod
    def generate(self, text) -> bytes:
        """
        Synthesize speech from text and return audio bytes.
        """
        return b""

    @abstractmethod
    def is_available(self):
        """
        Check if the provider is available (e.g. has internet).
        :return: Boolean
        """
        pass
