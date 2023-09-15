from unidecode import unidecode
import historic
from chatterbot_bot import response_to_user

words = ['nao sei','me diga', 'nao sei fale', 'o que e?', 'quem e?', 'quem?', 'me diz voce','quem foi?', 'como?']
def do_not_know(id_user, mensagem):
        for str in words:
            if str.lower() in unidecode(mensagem).lower():
                bot_asked = historic.query(id_user)
                return response_to_user(bot_asked)

