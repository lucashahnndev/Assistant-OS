import os

from chatterbot.logic import LogicAdapter
from chatterbot.conversation import Statement
from json import load
from unidecode import unidecode

parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
file_config = open(f'{parent_dir}/data/config.json', 'r')

config = load(file_config)
Api_Key = config['Wheather']['apiKey']
lat = config['Wheather']['lat']
lon = config['Wheather']['lon']

words = ["qual e a temperatura","o tempo", "qual a temperatura", 'a temperetura', ' e temperatura', 'como esta o ceu', 'o ceu como esta',
         'como esta o clima', 'o clima agora', 'esta chovendo', 'tem sol' 'como esta a umidade', 'qual a umidade', 'umidade', 'quantos graus', 'graus esta']


class weather_adapter(LogicAdapter):
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

        response = requests.get(f'{Api_Key}&lat{lat}&lon{lon}')
        data = response.json()

        if response.status_code == 200:
            confidence = 1
        else:
            confidence = 0
        descricao = data['weather'][0]['description']
        umidade = round(data['main']['humidity'])
        clima = {umidade}, {descricao}
        temperature = round(data['main']['temp'] - 273.15)

        climate_group = '{ "temperature" : [ "graus", "temperatura" ] , "sky" : ["ceu"] , "moisture" : ["umidade"] , "complete" : [ "clima" , "sol" , "chuva" ] }'
        climate_groups = loads(climate_group)

        for tuple in climate_groups:
            for x in climate_groups[tuple]:
                if x in unidecode(repr(input_statement).lower()):
                    processing_result = tuple

        if processing_result == 'temperature':
            response_statement = Statement(
                text='Atualmente a temperatura está alcançando uma média de {} Graus Celsios !'.format(temperature))
            response_statement.confidence = confidence
            return response_statement
        if processing_result == 'sky':
            response_statement = Statement(
                text='O clima agora esta {} !'.format(descricao))
            response_statement.confidence = confidence
            return response_statement
        if processing_result == 'moisture':
            response_statement = Statement(
                text='Neste momento a umidade do ar está em media de {}% !'.format(umidade))
            response_statement.confidence = confidence
            return response_statement
        if processing_result == 'complete':
            response_statement = Statement(
                text=f"""
O clima agora esta {descricao}

a umidade atual é de {umidade}%
                    
Atualmente a temperatura está alcançando uma média de {temperature} Graus Celsios !""")
            response_statement.confidence = confidence
            return response_statement
