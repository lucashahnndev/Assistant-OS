import wikipedia
from debug import log
from unidecode import unidecode
from chatterbot.logic import LogicAdapter
from chatterbot.conversation import Statement

wikipedia.set_lang("pt")

words = ['quem e','busque para mim sobre','busque para mim na wikipedia', 'o que e um','o que e', 'veja no wikipwdia', 'busque na wikipedia', 'o que a wikipedia diz', 'a origem', 'da onde vem', 'de onde vem', 'quem fez', 'quem construiu', 'quem criou', 'quem foi o primeiro', 'pesquise na wikipedia', 'me diga um resumo' ]

class search_in_wikipedia_adapter(LogicAdapter):
    def __init__(self, chatbot, **kwargs):
        super().__init__(chatbot, **kwargs)

    def can_process(self, statement):
        for str in words:
            if str.lower() in unidecode(repr(statement).lower()):
                return True
        return False

    def process(self, input_statement, additional_response_selection_parameters):
        text = unidecode(input_statement.text.lower().replace("'",''))
        def just_the_search_word(text):
            for str in words:
                if str.lower() in text:
                    input_statement2 = text.replace(str, '').replace('?','')
                    return input_statement2
        try:
            response_from_wikipedia = Statement(wikipedia.summary(just_the_search_word(text), sentences=3))
            if response_from_wikipedia is not None:
                response_statement = response_from_wikipedia
                response_statement.confidence = 0.60
            else:
                response_statement.confidence = 0
        except Exception as error:
            log(error, 'logs/log.log')
            response_statement.confidence = 0
            
        return response_statement
    