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

    def generate(self, text) -> bytes:
        if not self.is_available():
            return b""
            
        try:
            temp_file = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
            temp_path = temp_file.name
            temp_file.close()

            async def _generate():
                communicate = edge_tts.Communicate(text, self.voice, rate=self.rate, volume=self.volume)
                await communicate.save(temp_path)

            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
            loop.run_until_complete(_generate())
            
            with open(temp_path, 'rb') as f:
                content = f.read()
                
            if os.path.exists(temp_path):
                os.remove(temp_path)
                
            return content
        except Exception as e:
            logger.error(f"Edge generate error: {e}")
            return b""

    def speak(self, text):
        content = self.generate(text)
        if not content: return False
        
        try:
            temp_file = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
            temp_path = temp_file.name
            temp_file.write(content)
            temp_file.close()
            
            self._play_audio(temp_path)
            
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return True
        except Exception as e:
            logger.error(f"Edge speak error: {e}")
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
