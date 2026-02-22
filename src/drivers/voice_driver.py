import threading
import random
from .base_driver import BaseDriver
from core.identity import PrincipalContext
from drivers.voice.assistant import Assistant
from drivers.voice.interface import AssistantInterface
from utils.cli import clear_console
from services.tts import TTSManager
from utils.logging_config import get_logger
import os

class VoiceDriver(BaseDriver):
    def __init__(self, kernel, parent_dir):
        super().__init__(kernel)
        self.parent_dir = parent_dir
        self.logger = get_logger("VoiceDriver")
        self.assistant = None
        self.interface = None
        self.tts_manager = None
        self.running = False
        self.skip_activation = False
        self.activation_confirm = [
            'Sim, como posso ajudar?', 'Sim, o que deseja?', 
            'Sim, o que posso fazer por você?', 'Olá, como posso ajudar?'
        ]

    def _initialize_components(self):
        # Initialize TTS Manager
        self.tts_manager = TTSManager()
        
        # Get Configs
        from config.manager import ConfigManager
        cm = ConfigManager()
        stt_config = cm.get_stt_config()
        interface_config = cm.get_interfaces_config().get('voice', {})
        
        stt_provider = stt_config.get('provider', 'google')
        # Note: Assistant class might need raw string for 'voice_recognition_engineering'
        # e.g 'google', 'vosk', 'openai'
        
        # Initialize original Assistant
        # We pass dummy logic for TTS engine as we use TTSManager
        assistant_voice = Assistant.text_to_speech_engine(
            voice_language='pt-BR',
            voice_name='pt-BR-Wavenet-C',
        )
        
        self.assistant = Assistant(
            voice_recognition_engineering=stt_provider,
            text_to_speech_engineering='google_cloud', # Legacy param, unused by us now
            name=interface_config.get('wake_word', 'Assistente'),
            tts_engine_=assistant_voice
        )
        
        # Load Credentials
        # Only set if explicitly provided in config, otherwise assume Env Var is set externally
        google_creds = stt_config.get('google_credentials_path')
        if google_creds:
             if os.path.exists(google_creds):
                 self.assistant.google_cloud_credentials(google_creds)
             else:
                 self.logger.warning(f"Google Credentials file not found at: {google_creds}")
        
        # Initialize Engines
        # We might need to pass specific args for vosk/openai if Assistant supports it
        # For now, we assume Assistant.py handles logic based on the provider string
        self.assistant.initialize_voice_recognition_engine()
        
        # Initialize UI
        self.interface = AssistantInterface(name='Atlas')

    def start(self):
        self._initialize_components()
        self.running = True
        
        # Start Interface Thread
        threading.Thread(target=self.interface.start).start()
        
        # Start Voice Loop Thread
        threading.Thread(target=self._voice_loop, daemon=True).start()

    def stop(self):
        self.running = False
        if self.interface:
            self.interface.stop()

    def send_response(self, text, target=None, is_chunk=False, attachments=None):
        if not self.interface or not self.tts_manager:
            self.logger.warning(f"VoiceDriver components not ready to send response: {text}")
            return
            
        self.interface.assistant_color()
        self.interface.update_assistant_text(text)
        
        # Use TTS Manager instead of Assistant.speak
        # self.assistant.speak(text) 
        self.tts_manager.speak(text)
        
        self.interface.user_color()

    def _voice_loop(self):
        # Main Voice Logic (Adapted from main.py)
        clear_console()
        
        while self.running:
            try:
                if not self.assistant:
                    self.logger.error("Assistant component not initialized. Retrying in 2s...")
                    import time
                    time.sleep(2)
                    continue
                
                transcription = self.assistant.audio_listen()
                clear_console()
                self.logger.info(f"Transcription: {transcription}")
                
                if transcription:
                    self.interface.update_user_text(transcription)
                
                if transcription is None:
                    continue

                user_input = transcription
                
                # Check for activation word (Wakeword logic)
                if not self.skip_activation:
                    user_input = self.assistant.its_a_assistant_command(transcription)
                    if user_input == '':
                        self.skip_activation = True
                        self.send_response(random.choice(self.activation_confirm))
                        continue
                else:
                    self.skip_activation = False

                if user_input:
                    self.logger.info(f"User input command: {user_input}")
                    context = PrincipalContext(
                        interface="voice",
                        sender_id="local_user",
                        sender_name="Voice User",
                        session_id="voice_main"
                    )
                    # Send to Kernel for processing
                    self.on_message_received(user_input, user_id='voice_main', context=context)

            except Exception as e:
                self.logger.error(f"Voice Loop Error: {e}")
                self.send_response('Desculpe, houve um erro, tente novamente.')

    def send_file(self, target, file_path, caption=None):
        """
        VoiceDriver does not support sending files.
        """
        self.logger.warning(f"VoiceDriver received request to send file to {target}: {file_path}. Ignoring.")

    def send_status(self, target, phase, payload=None):
        """VoiceDriver does not support structured status."""
        pass

    def send_reasoning_chunk(self, target, content):
        """VoiceDriver does not support reasoning chunks."""
        pass

    def send_complete(self, target):
        """VoiceDriver does not support completion events."""
        pass

    def get_capabilities(self) -> dict:
        """Voice interfaces don't support markdown formatting or visual media natively."""
        return {
            "markdown": False,
            "rich_media": False,
            "voice_only": True,
            "streaming": True
        }

