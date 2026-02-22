import asyncio
import os
import pygame
import tempfile
import threading
from services.tts.providers.base import ITTSProvider
from utils.logging_config import get_logger

logger = get_logger("EdgeTTS")

try:
    import edge_tts
except ImportError:
    edge_tts = None

class EdgeTTSProvider(ITTSProvider):
    def __init__(self, config):
        super().__init__(config)
        self.voice = config.get('voice', 'pt-BR-FranciscaNeural')
        self.rate = config.get('rate', '+0%')
        self.volume = config.get('volume', '+0%')

    def is_available(self):
        # Basic check: is library installed? (Internet check is harder to do reliably without blocking)
        return edge_tts is not None

    def speak(self, text):
        if not self.is_available():
            logger.warning("EdgeTTS library not installed.")
            return False

        try:
            # edge-tts is async, so we need to run it in an event loop
            # We use a temporary file to store the audio
            
            temp_file = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
            temp_path = temp_file.name
            temp_file.close()

            async def _generate():
                communicate = edge_tts.Communicate(text, self.voice, rate=self.rate, volume=self.volume)
                await communicate.save(temp_path)

            # Run async function
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
            loop.run_until_complete(_generate())
            
            # Play Audio using Pygame (Standard in this project)
            self._play_audio(temp_path)
            
            # Cleanup
            if os.path.exists(temp_path):
                os.remove(temp_path)
                
            return True

        except Exception as e:
            logger.error(f"EdgeTTS Error: {e}")
            return False

    def _play_audio(self, file_path):
        try:
            pygame.mixer.init()
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10)
        except Exception as e:
            logger.error(f"Audio Playback Error: {e}")
            raise e
