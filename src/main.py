from models.assistant import Assistant
import sys
import os
import router
from tools import clear_console
import random
from models.interface import AssistantInterface, assistant_tray
import threading

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

# create an instance of the Assistant class
assistant_voice =Assistant.text_to_speech_engine(
                     voice_language='pt-BR',
                     voice_name='pt-BR-Wavenet-C',
                 )

assistant = Assistant(voice_recognition_engineering='google',
                 text_to_speech_engineering='google_cloud',
                 name='Assistente',
                 tts_engine_=assistant_voice
                 )

assistant.google_cloud_credentials(f'{parent_dir}\\data\\Lia-5732d88a57a2.json')


# initialize the voice recognition engine
assistant.initialize_voice_recognition_engine()
assistant.initialize_text_to_speech_engine()


acitivation_comfirm = ['Sim, como posso ajudar?', 'Sim, o que deseja?', 'Sim, o que posso fazer por você?', 'Olá, como posso ajudar?', 'Olá, o que deseja?',
                       'Olá, o que posso fazer por você?', 'Olá, como posso ser útil?', 'Olá, como posso ajudar?', 'Olá, o que deseja?', 'Olá, o que posso fazer por você?', 'Olá, como posso ser útil?']


interface = AssistantInterface(name='Assistente')
threading.Thread(target=interface.start).start()

#tray = assistant_tray(name='assistant', icon_file=f'{parent_dir}/images/logo.png')
#threading.Thread(target=tray.run).start()


clear_console()
skip_activation_command = False

def assistant_speak(text):
    interface.assistant_color()
    interface.update_assistant_text(text)
    assistant.speak(text)
    interface.user_color()


while True:
    try:
        transcription = assistant.audio_listen()
        clear_console()
        print('Transcription:', transcription)
        interface.update_user_text(transcription)
        user_input_without_command = transcription
        if skip_activation_command == False:
            user_input_without_command = assistant.its_a_assistant_command(
                transcription)
            if user_input_without_command == '':
                skip_activation_command = True
                interface.assistant_color()
                assistant_speak(random.choice(acitivation_comfirm))
                continue
        else:
            skip_activation_command = False

        print('User input without command:', user_input_without_command)
        if transcription == None or user_input_without_command == None:
            continue
        res, _ = router.process(1, user_input_without_command, 'senhor')
        print('Assistente response:', res)
        interface.assistant_color()
        assistant_speak(res)
    except KeyboardInterrupt:
        print('KeyboardInterrupt')
        interface.stop()
        break

    except Exception as e:
        print(e)
        assistant_speak('Desculpe, houve um erro, tente novamente.')
        continue

