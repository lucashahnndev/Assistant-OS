import os
import random
from debug import log
from chatterbot import ChatBot
from chatterbot.trainers import ChatterBotCorpusTrainer
from chatterbot.logic import BestMatch, MathematicalEvaluation, UnitConversion
from adapters import weather_adapter
from adapters import time_adapter
from adapters import search_in_wikipedia_adapter
from config import BOT_NAME as name_bot
import sys
# config

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

iabot = ChatBot(
    name_bot,
    logic_adapters=[
        "chatterbot.logic.BestMatch",
        'chatterbot.logic.MathematicalEvaluation',
        'chatterbot.logic.UnitConversion',
        {'import_path': 'adapters.weather_adapter'},
        {'import_path': 'adapters.time_adapter'},
        {'import_path': 'adapters.search_in_wikipedia_adapter'}

    ],
    storage_adapter="chatterbot.storage.SQLStorageAdapter",
    database_uri="sqlite:///historic/database.sqlite3",
    preprocessors=[
        'chatterbot.preprocessors.clean_whitespace'
    ]
)


conversa = ChatterBotCorpusTrainer(iabot)
conversa.train("corpus.portuguese")

i_didn_t_understand = ['Não entendi, pode repetir?', 'Como?', 'Desculpe, mas eu ainda não sei nada sobre este assunto.', 'Sei que muitas vezes não entendo o que você diz, mas peço que seja paciente.',
                       'Desculpe, não entendi, pode explicar melhor?', 'Gostaria que me explicasse melhor.', 'Eu não entendi!', 'Hmm, ainda não conhecia este termo! Me conte mais, por favor.']


def response_to_user(mensagem):
    try:
        resposta = iabot.get_response(mensagem)
        """ print(resposta)
        return resposta.text """
        if resposta.text.endswith('?'):
            return resposta
        if resposta.confidence > 0.0:
            return resposta.text
        else:
            return random.choice(i_didn_t_understand), False
    except Exception as error:
        log(error, 'logs/log.log')
        return '"' + random.choice(i_didn_t_understand), False
