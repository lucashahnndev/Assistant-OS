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
        self.voice_id = str(config.get('voice_id', '') or '').strip()
        self.voice_name_contains = str(config.get('voice_name_contains', '') or '').strip().lower()
        self.preferred_gender = str(config.get('preferred_gender', 'MALE') or 'MALE').strip().upper()
        
        # Configure Engine
        self.engine.setProperty('rate', self.rate)
        self.engine.setProperty('volume', self.volume)
        self._select_voice()

    def is_available(self):
        return True # Always available (offline)

    def generate(self, text) -> bytes:
        import tempfile
        import os
        try:
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp:
                temp_path = temp.name
            
            self.engine.save_to_file(text, temp_path)
            self.engine.runAndWait()
            
            with open(temp_path, 'rb') as f:
                content = f.read()
            
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return content
        except Exception as e:
            logger.error(f"System generate error: {e}")
            return b""

    def speak(self, text):
        try:
            self.engine.say(text)
            self.engine.runAndWait()
            return True
        except Exception as e:
            logger.error(f"System TTS Error: {e}")
            return False

    def _voice_gender_score(self, voice) -> int:
        target = self.preferred_gender
        if target not in {"MALE", "FEMALE"}:
            return 0

        gender = str(getattr(voice, "gender", "") or "").upper()
        if target in gender:
            return 3

        text = f"{getattr(voice, 'id', '')} {getattr(voice, 'name', '')}".lower()
        male_tokens = ("male", "masculino", "homem", "man", "m ")
        female_tokens = ("female", "feminino", "mulher", "woman", "f ")

        if target == "MALE":
            if any(tok in text for tok in male_tokens):
                return 2
            if any(tok in text for tok in female_tokens):
                return -2
        else:
            if any(tok in text for tok in female_tokens):
                return 2
            if any(tok in text for tok in male_tokens):
                return -2
        return 0

    def _select_voice(self):
        try:
            voices = self.engine.getProperty('voices') or []
            if not voices:
                return

            # Explicit voice_id override has highest priority.
            if self.voice_id:
                for voice in voices:
                    if str(getattr(voice, "id", "")) == self.voice_id:
                        self.engine.setProperty('voice', self.voice_id)
                        logger.info("System voice selected by id: %s", self.voice_id)
                        return

            best_voice = None
            best_score = -999
            for voice in voices:
                score = 0
                if self.voice_name_contains:
                    name = str(getattr(voice, "name", "")).lower()
                    vid = str(getattr(voice, "id", "")).lower()
                    if self.voice_name_contains in name or self.voice_name_contains in vid:
                        score += 5
                score += self._voice_gender_score(voice)
                if score > best_score:
                    best_score = score
                    best_voice = voice

            if best_voice is not None:
                self.engine.setProperty('voice', getattr(best_voice, "id", ""))
                logger.info(
                    "System voice selected: id='%s' name='%s' gender_pref='%s' score=%s",
                    getattr(best_voice, "id", ""),
                    getattr(best_voice, "name", ""),
                    self.preferred_gender,
                    best_score,
                )
        except Exception as e:
            logger.warning("Failed to select system voice: %s", e)
