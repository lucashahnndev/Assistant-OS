import random
import os
import pyautogui
from config import GOOGLE_MAPS_API_KEY
from tools.location import get_location
import googlemaps
import speech_recognition as sr

occurrence = ['google maps', 'maps', 'mapas do google',
              'mapas do google maps', 'maps do google']


aditional_search_terms = ['sobre', 'sobre o', 'sobre a', 'por', 'faça uma', 'realize uma', 'de',
                          'localização de', 'localização do ', 'localização da',
                          'onde fica', 'onde fica o', 'onde fica a', 'local de', 'local do', 'local da',
                          'endereco de', 'endereco do', 'endereco da ',
                          'abre no', 'abrir no', 'abra no',
                          'pesquisar no ', 'pesquise no', 'pesquisa no ',
                          'pesquisa por', 'pesquisar por', 'pesquise por',
                          'procure no', 'procurar no', 'procura no',
                          'pesquise','pesquisa', 'pesquisar','no'
                          ]


confirmation = ([
    "procurando ocorrencias de",
    "pesquisando ocorrencias de",
    "encontrando ocorrencias de",
])
ok = (["ok", "certo", "entendido", "sim", "claro"])


def open_in_maps(query,old_query):
    user_location_lat, user_location_lon = get_location()
    maps_url = f"https://www.google.com/maps/search/?api=1&query={query}&query_place_id={query}&center={user_location_lat},{user_location_lon}"
    print(maps_url)
    bronser = 'chrome '
    url = f'-app="{maps_url}"'
    if bronser == 'microsoft-edge:':
        url = f'"{maps_url}"'
    
    os.popen(f"start {bronser}{url}")
    pyautogui.sleep(5)
    pyautogui.hotkey('f11')
    return f'{random.choice(ok)}, {random.choice(confirmation)} {query} no Google Maps.'


def remove_starting_string(starting_string, target_string):
    if target_string.startswith(starting_string):
        return target_string[len(starting_string):]
    else:
        return None

def remove_aditional_terms(query, term, aditional_search_terms):
    if query == None or query == '':
        return None
    query = query.replace('  ', ' ')
    query = query.replace(f'{term}', '_*_')
    aditional_terms_in_query = False
    for aditional_term in aditional_search_terms:
        if aditional_term in query:
            new_quey = remove_starting_string(aditional_term, query)
            if new_quey is not None:
                aditional_terms_in_query = True
                query = new_quey
            aditional_terms_in_query = True
            query = query.replace(f'{aditional_term} _*_', '_*_')
            query = query.replace(f'_*_ {aditional_term}', '_*_')
    if aditional_terms_in_query:
        return query.replace('_*_', '')
    else:
        return None

def if_its_a_command_search_in_maps(message):
    message = message.lower()
    query = message
    old_query= message.lower()
    for term in occurrence:
        if term in message:
            query = remove_aditional_terms(query, term, aditional_search_terms)
            if query is not None:
                return open_in_maps(query,old_query)
    return None


def speak_list_(query, user_location_lat, user_location_lon):
    """ if 'liste' in old_query or 'lista' in old_query or 'falar' in old_query or 'diga' in old_query:
        return speak_list_(query, user_location_lat, user_location_lon)
    else: """
    gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)
    places_result = gmaps.places(query, location=(user_location_lat, user_location_lon), radius=5000)
    if len(places_result['results']) > 0:
        speak(f'Encontrei {len(places_result["results"])} lugares com essa consulta.')
        for x in places_result['results']:
            print(f'{x["name"]}\n')
        TEXT_MODE = os.environ.get('TEXT_MODE')
        if TEXT_MODE == 'True':
            answer = input('Digite o nome do lugar: ')
        else:
            with sr.Microphone() as mic:
                rec = sr.Recognizer()
                rec.adjust_for_ambient_noise(mic)
                print("Diga o nome do lugar: ")
                audio = rec.listen(mic)
                print('Processando...')
                answer = rec.recognize_google(audio, language='pt-BR')
        print('você:  ', answer)
        
        for place in places_result['results']:
            if answer in place['name']:
                place_url = f"https://www.google.com/maps/search/?api=1&query={place_lat},{place_lng}&query_place_id={place['place_id']}"
                os.popen(f"start chrome -app={place_url}")
                
                pyautogui.sleep(5)
                # pressiona a tecla F11 para maximizar a janela
                pyautogui.hotkey('f11')
                return {'status': 'OK', 'message': f'aberto o {place["name"]} no Google Maps.'}
            
    else:
        return f'Desculpe, não encontrei nenhum lugar com essa consulta. {query}'
    