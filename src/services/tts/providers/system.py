import pyttsx3
from services.tts.providers.base import ITTSProvider
from utils.logging_config import get_logger

logger = get_logger("SystemTTS")

class SystemProvider(ITTSProvider):
    def __init__(self, config):
        super().__init__(config)
        self.engine = pyttsx3.init()
        self.rate = config.get('rate', 150)
        self.volume = config.get('volume', 1.0)
        
        # Configure Engine
        self.engine.setProperty('rate', self.rate)
        self.engine.setProperty('volume', self.volume)
        
        # Select voice if specified (simple selection for now)
        # In future could list voices and select by name

    def is_available(self):
        return True # Always available (offline)

    def speak(self, text):
        try:
            self.engine.say(text)
            self.engine.runAndWait()
            return True
        except Exception as e:
            logger.error(f"System TTS Error: {e}")
            return False
