import os
import vosk
import json
import time
import pygame as pgame
import pyaudio
import pyttsx3
import tempfile
import threading
import pyttsx3.voice
from enum import Enum
from typing import Any
from fuzzywuzzy import fuzz
import speech_recognition as sr
from google.cloud import texttospeech
from pydantic import BaseModel, validator



parent_dir = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))


class Assistant(BaseModel):


    name: str = 'Assistant'
    voice_recognition_engineering: str = 'google'
    text_to_speech_engineering: str = 'google'
    rec: Any = None
    command_to_activate: str = None
    command_to_activate_similarity: int = 60
    stream: Any = None

    class vosk_engine(BaseModel):
        model_path: str = f"{parent_dir}/model/vosk-model-pt/"
        chunk: int = 2048
        sample_rate: int = 16000
        microphone: int = 0
    vosk_engine_: vosk_engine() = vosk_engine()

    class speech_recognition_engine(BaseModel):
        language: str = 'pt-BR'
        microphone: int = 0
    speech_recognition_engine_: speech_recognition_engine() = speech_recognition_engine()

    class text_to_speech_engine(BaseModel):
        client: Any = None
        rate: int = 150
        volume: float = 1.0
        sp_engine: Any = None
        voice_language: str = 'pt-BR'
        voice_name: str = 'pt-BR-Wavenet-A'
        recognizer: Any = None
        microphone: str = 0

        @validator("voice_name")
        def validate_voice_name(cls, value):
            if value != "pt-BR-Wavenet-A" and value != "pt-BR-Wavenet-B" and value != "pt-BR-Wavenet-C":
                raise ValueError(
                    "The 'voice_name' option must be 'pt-BR-Wavenet-A' or 'pt-BR-Wavenet-B' or 'pt-BR-Wavenet-C'")
            return value
    tts_engine_: text_to_speech_engine() = text_to_speech_engine()  # Renomeado para 'tts_engine_'




    class Config:
        use_enum_values = True

    class InteractionModeEnum(str, Enum):
        voice = "voice"
        text = "text"

    class VoiceRecognitionEngineeringEnum(str, Enum):
        vosk = "vosk"
        google = "google"

    class TextToSpeechEngineeringEnum(str, Enum):
        default = "google"
        google = "google_cloud"

    @validator("voice_recognition_engineering")
    def validate_recognition_engine(cls, value):
        if value != "vosk" and value != "google":
            raise ValueError(
                "The 'voice_recognition_engineering' option must be 'vosk' or 'google'")
        return value

    @validator("text_to_speech_engineering")
    def validate_text_to_speech_engineering(cls, value):
        if value != "google" and value != "google_cloud":
            raise ValueError(
                "The 'text_to_speech_engineering' option must be 'google' or 'google_cloud'")
        return value


    def audio_listen(self):
        if self.voice_recognition_engineering == 'vosk':
            while True:
                data = self.stream.read(
                    self.vosk_engine_.chunk, exception_on_overflow=False)
                if len(data) == 0:
                    pass
                print('Processando...')
                # Reconhece o áudio
                if self.recognizer.AcceptWaveform(data):
                    # Obtém o texto reconhecido
                    result = json.loads(self.recognizer.Result())
                    text = result["text"]
                    print(text)
                    return text
        elif self.voice_recognition_engineering == 'google':
            try:
                with sr.Microphone(self.speech_recognition_engine_.microphone) as mic:
                    self.rec.adjust_for_ambient_noise(mic, duration=0.2)
                    audio = self.rec.listen(
                        mic, timeout=10, phrase_time_limit=5, snowboy_configuration=None)
                    print('Processando...')
                    text = self.rec.recognize_google(audio, language='pt-BR')
                    return text
            except sr.UnknownValueError:
                print('Não entendi o que você disse.')
                pass

    def google_cloud_credentials(self, GOOGLE_APPLICATION_CREDENTIALS):
        if self.text_to_speech_engineering == 'google_cloud':
            if GOOGLE_APPLICATION_CREDENTIALS is None:
                raise ValueError(
                    "The 'GOOGLE_APPLICATION_CREDENTIALS' environment variable must be set")
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_APPLICATION_CREDENTIALS
            self.tts_engine_.client = texttospeech.TextToSpeechClient()

    def speak(self, text_to_speak):
        text_to_speak = adjust_phonetic(text_to_speak)

        if self.text_to_speech_engineering == 'google':
            voices = self.tts_engine_.sp_engine.getProperty('voices')
            self.tts_engine_.sp_engine.setProperty('voice', voices[0].id)
            self.tts_engine_.sp_engine.say(text_to_speak)
            self.tts_engine_.sp_engine.runAndWait()
            self.tts_engine_.sp_engine.stop()

        if self.text_to_speech_engineering == 'google_cloud':
            synthesis_input = texttospeech.SynthesisInput(text=text_to_speak)
            voice = texttospeech.VoiceSelectionParams(
                language_code=self.tts_engine_.voice_language,
                name=self.tts_engine_.voice_name,
                ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL
            )
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3
            )
            response = self.tts_engine_.client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )
            audio_reproduction(write_file(response))

    def its_a_assistant_command(self, user_text):
        if user_text is None:
            return None

        user_text = user_text.lower().replace('  ', ' ')
        text_token = user_text.split(' ')
        user_test_without_command = " ".join(text_token[1:])
        text_to_analize = " ".join(text_token[:1])
        text_to_activate = self.name

        if self.command_to_activate:
            text_to_activate = f'{self.command_to_activate} {self.name}'
            user_test_without_command = " ".join(text_token[2:])
            text_to_analize = " ".join(text_token[:2])

        similarity = fuzz.ratio(text_to_analize.lower(),
                                text_to_activate.lower())
        if similarity >= self.command_to_activate_similarity:
            return user_test_without_command.strip()
        return None

    def initialize_text_to_speech_engine(self):
        if self.text_to_speech_engineering == 'google':
            self.tts_engine_.sp_engine = pyttsx3.init()
            self.tts_engine_.sp_engine.setProperty('rate', self.tts_engine_.rate)
            self.tts_engine_.sp_engine.setProperty('volume', self.tts_engine_.volume)
            self.tts_engine_.sp_engine.setProperty(
                'voice', self.tts_engine_.voice_name)
            self.tts_engine_.sp_engine.setProperty(
                'language', self.tts_engine_.voice_language)
        if self.text_to_speech_engineering == 'google_cloud':
            pass

    def initialize_voice_recognition_engine(self):
        if self.voice_recognition_engineering == 'vosk':
            audio = pyaudio.PyAudio()
            model = vosk.Model(self.vosk_engine_.model_path)
            audio_device_index = self.vosk_engine_.microphone  # Pode ser necessário ajustar
            self.stream = audio.open(format=pyaudio.paInt16,
                                     channels=1,
                                     rate=self.vosk_engine_.sample_rate,
                                     input=True, frames_per_buffer=self.vosk_engine_.chunk,
                                     input_device_index=audio_device_index)
            self.recognizer = vosk.KaldiRecognizer(
                model, self.vosk_engine_.sample_rate)

        elif self.voice_recognition_engineering == 'google':
            self.rec = sr.Recognizer()



def audio_reproduction(audio_file):
    pgame.init()

    pgame.mixer.music.load(audio_file)
    pgame.mixer.music.play()
    while pgame.mixer.music.get_busy():
        pass
    #pgame.quit()
    #t = threading.Thread(target=delete_file, args=(audio_file,))
    #t.start()


def delete_file(filename):
    os.remove(filename)


def write_file(audio_bitecode):
    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
        temp_file.write(audio_bitecode.audio_content)
        return temp_file.name

#ajusta a fonética dos caracteres especiais
def adjust_phonetic(text):
    text = text.replace('```', '')
    return text
