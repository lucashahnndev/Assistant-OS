import date_and_hour
from chatterbot.logic import LogicAdapter
from chatterbot.conversation import Statement
from unidecode import unidecode

words = [
    'que horas sao',
    'tem horas',
    'sabe a hora',
    'qual é a hora',
    'que hora é',
    'qual data', 'que data e','que ano estamos', 'que ano ano', 'minuto', 'minutos', 'que mes', 'sabe o mes', 'sabe o ano','qual ano estamos' 'sabe o dia', 'que dia e hoje', 'hoje', "data e hora"
]

class time_adapter(LogicAdapter):
    def __init__(self, chatbot, **kwargs):
        super().__init__(chatbot, **kwargs)

    def can_process(self, statement):
        for str in words:
            if str.lower() in unidecode(repr(statement).lower()):
                return True
        return False

    def process(self, input_statement, additional_response_selection_parameters):
        import requests
        from json import loads

        time_group = '{ "hour" : [ "hora" ] , "day" : ["dia", "hoje" ] , "date" : ["data"] , "minutes" : [ "minutos" ] , "year" : [ "ano" ], "complete" : ["data e hora"]}'
        time_groups = loads(time_group)
        confidence = 1
        for tuple in time_groups:
            for x in time_groups[tuple]:
                if x in unidecode(repr(input_statement).lower()):
                    processing_result = tuple

        if processing_result == 'hour':
            response_statement = Statement(
                text='A hora agora é exatamente {}!'.format(date_and_hour.time_now()))
            response_statement.confidence = confidence
            return response_statement

        if processing_result == 'day':
            response_statement = Statement(
                text='Hoje é {}!'.format(date_and_hour.day()))
            response_statement.confidence = confidence
            return response_statement

        if processing_result == 'date':
            response_statement = Statement(
                text='A data de hoje é {}'.format(date_and_hour.date_now()))
            response_statement.confidence = confidence
            return response_statement

        if processing_result == 'minutes':
            response_statement = Statement(
                text=f'Os minutos agora são exatamente {date_and_hour.minutes()}!')
            response_statement.confidence = confidence
            return response_statement

        if processing_result == 'year':
            response_statement = Statement(
                text='estamos em {}!'.format(date_and_hour.year()))
            response_statement.confidence = confidence
            return response_statement

        if processing_result == 'complete':
            response_statement = Statement(
                text=f'Agora é {date_and_hour.time_now()} de {date_and_hour.date_now}!')
            response_statement.confidence = confidence
            return response_statement
