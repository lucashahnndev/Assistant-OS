# import memory
#from chatterbot_bot import response_to_user
from greeting import if_its_a_greeting
from command import if_its_a_command_open_program, if_its_a_command_search, if_its_a_key_command, if_its_a_command_play_in_youtube,if_its_a_command_search_in_maps
from command import if_its_a_command_play_in_youtube_music
import os
import open_ai_conector
import memory
from chatterbot_bot import response_to_user

# obter o cominho do arquivo
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def process(id_user, mensagem, name_param):
    global name
    name = name_param
    result = 0
    if mensagem.lower() == 'sair do chat':
        return 'Até  mais.', True
        exit()

    if mensagem.lower() == 'exibir logs':
        os.popen(f'start {parent_dir}\logs\log.log')
        return 'Exibindo logs.', True

    if mensagem.lower() == 'desativar modo texto':
        os.environ['TEXT_MODE'] = 'False'
        return 'Modo texto desativado.', True

    if mensagem.lower() == 'ativar modo texto':
        os.environ['TEXT_MODE'] = 'True'
        return 'Modo texto ativado.', True

    if__key_command = if_its_a_key_command(mensagem)
    if if__key_command is not None:
        result = 1
        return if__key_command, True

    if__youtube_music = if_its_a_command_play_in_youtube_music(mensagem)
    if if__youtube_music is not None:
        result = 1
        return if__youtube_music, True

    if__youtube = if_its_a_command_play_in_youtube(mensagem)
    if if__youtube is not None:
        result = 1
        return if__youtube, True

    if_maps = if_its_a_command_search_in_maps(mensagem)
    if if_maps is not None:
        result = 1
        return if_maps, True

    if__search = if_its_a_command_search(mensagem)
    if if__search is not None:
        result = 1
        return if__search, True

    if__command = if_its_a_command_open_program(mensagem)
    if if__command is not None:
        result = 1
        return if__command, True

    if_greeting = if_its_a_greeting(mensagem, name)
    if if_greeting is not None:
        result = 1
        return if_greeting, True

    memory_a = memory.do_not_know(id_user, mensagem)
    if memory_a is not None:
        result = 1
        return memory_a

    if result == 0:
        return 'Não entendi o que você quis dizer.', False
        #return open_ai_conector.response_to_user(mensagem), True
        #return response_to_user(mensagem), True
