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
        Synthesize speech from text.
        :param text: Text to speak.
        :return: True if successful, False otherwise.
        """
        pass

    @abstractmethod
    def is_available(self):
        """
        Check if the provider is available (e.g. has internet).
        :return: Boolean
        """
        pass
