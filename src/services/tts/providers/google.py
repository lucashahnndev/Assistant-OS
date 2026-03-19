import os
import tempfile
import pygame
from services.tts.providers.base import ITTSProvider
from server.core.secret_manager import resolve_secret_ref
from utils.logging_config import get_logger

logger = get_logger("GoogleCloudTTS")

try:
    from google.cloud import texttospeech
    from google.oauth2 import service_account
except ImportError:
    texttospeech = None
    service_account = None

class GoogleCloudProvider(ITTSProvider):
    def __init__(self, config):
        super().__init__(config)
        self.voice_language = config.get('language', 'pt-BR')
        self.voice_name = config.get('voice_name', 'pt-BR-Neural2-B')
        self.ssml_gender = str(config.get('ssml_gender', 'MALE')).upper()
        self.audio_encoding = str(config.get('audio_encoding', 'MP3')).upper()
        
        self.credentials_path = resolve_secret_ref(
            config.get('credentials_path')
        )

        self.client = None
        if texttospeech:
            try:
                api_key = resolve_secret_ref(config.get('secret_ref'))
                if api_key:
                    from google.api_core import client_options
                    opts = client_options.ClientOptions(api_key=api_key)
                    self.client = texttospeech.TextToSpeechClient(client_options=opts)
                    logger.info("Google Cloud TTS initialized with API Key.")
                elif self.credentials_path and service_account:
                    credentials = service_account.Credentials.from_service_account_file(
                        self.credentials_path
                    )
                    self.client = texttospeech.TextToSpeechClient(credentials=credentials)
                    logger.info("Google Cloud TTS initialized with explicit service account credentials.")
                else:
                    self.client = texttospeech.TextToSpeechClient()
                    logger.info("Google Cloud TTS initialized with Default Credentials.")
            except Exception as e:
                logger.error(f"Google Cloud Client Init Error: {e}")

    def is_available(self):
        return self.client is not None

    def generate(self, text) -> bytes:
        if not self.is_available():
            return b""
            
        try:
            gender_map = {
                "MALE": texttospeech.SsmlVoiceGender.MALE,
                "FEMALE": texttospeech.SsmlVoiceGender.FEMALE,
                "NEUTRAL": texttospeech.SsmlVoiceGender.NEUTRAL,
            }
            encoding_map = {
                "MP3": texttospeech.AudioEncoding.MP3,
                "OGG_OPUS": texttospeech.AudioEncoding.OGG_OPUS,
                "LINEAR16": texttospeech.AudioEncoding.LINEAR16,
            }
            synthesis_input = texttospeech.SynthesisInput(text=text)
            voice = texttospeech.VoiceSelectionParams(
                language_code=self.voice_language,
                name=self.voice_name,
                ssml_gender=gender_map.get(self.ssml_gender, texttospeech.SsmlVoiceGender.MALE)
            )
            audio_config = texttospeech.AudioConfig(
                audio_encoding=encoding_map.get(self.audio_encoding, texttospeech.AudioEncoding.MP3)
            )
            
            response = self.client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )
            return response.audio_content
        except Exception as e:
            logger.error(f"Google generate error: {e}")
            return b""

    def speak(self, text):
        audio_content = self.generate(text)
        if not audio_content:
            return False

        try:
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
                temp_file.write(audio_content)
                temp_path = temp_file.name
                
            self._play_audio(temp_path)
            
            if os.path.exists(temp_path):
                os.remove(temp_path)
                
            return True
        except Exception as e:
            logger.error(f"Google speak error: {e}")
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
