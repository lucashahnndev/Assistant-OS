import os
import tempfile
import pygame
from services.tts.providers.base import ITTSProvider
from utils.logging_config import get_logger

logger = get_logger("GoogleCloudTTS")

try:
    from google.cloud import texttospeech
except ImportError:
    texttospeech = None

class GoogleCloudProvider(ITTSProvider):
    def __init__(self, config):
        super().__init__(config)
        self.voice_language = config.get('language', 'pt-BR')
        self.voice_name = config.get('voice_name', 'pt-BR-Wavenet-A')
        
        # Credentials handling
        # Assuming credentials are set in environment or passed via config
        self.credentials_path = config.get('credentials_path')
        if self.credentials_path:
             os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.credentials_path
             
        self.client = None
        if texttospeech:
            try:
                self.client = texttospeech.TextToSpeechClient()
            except Exception as e:
                logger.error(f"Google Cloud Client Init Error: {e}")

    def is_available(self):
        return self.client is not None

    def speak(self, text):
        if not self.is_available():
            return False

        try:
            # Logic adapted from src/models/assistant.py
            synthesis_input = texttospeech.SynthesisInput(text=text)
            
            voice = texttospeech.VoiceSelectionParams(
                language_code=self.voice_language,
                name=self.voice_name,
                ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL
            )
            
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3
            )
            
            response = self.client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )
            
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
                temp_file.write(response.audio_content)
                temp_path = temp_file.name
                
            self._play_audio(temp_path)
            
            if os.path.exists(temp_path):
                os.remove(temp_path)
                
            return True

        except Exception as e:
            logger.error(f"Google Cloud TTS Error: {e}")
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
