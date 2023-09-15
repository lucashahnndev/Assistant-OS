import random
import os
import pyautogui
from config import GOOGLE_CLOUD_API_KEY
from googleapiclient.discovery import build
import requests

search_terms = ['pesquisar no youtube music ', 'pesquise no youtube music', 'pesquisa no youtube music',
                'tocar no youtube music', 'toque no youtube music', 'toca no youtube music',
                'abre no youtube music', 'abrir no youtube music', 'abra no youtube music',
                'reproduzir no youtube music', 'reproduza no youtube music',
                'rode no youtube music', 'rodar no youtube music', 'roda no youtube music',
                "no youtube music", "youtube music"
                ]

aditional_search_terms = ['sobre ', 'sobre o ', 'sobre a ', 'por ', 'faça uma ', 'realize uma ', 'de ',
                          'musica da ', 'musica de ', 'musica do ', 
                          'abrir','abrir o', 'o']

confirmation = ([
    "reprodusindo a primeira opção de",
    "abrindo a primeira opção de",
    "tocando a primeira opção de",
    "rodando a primeira opção de",
    "reproduzindo a primeira ocorrencia de",
    "abrindo a primeira ocorrencia de",
    "tocando a primeira ocorrencia de",
    "rodando a primeira ocorrencia de",
    ])
ok = (["ok", "certo", "entendido", "sim", "claro"])

def play_in_youtube(query):
    url_video = f'watch?v={get_first_video_(query)}'
    if query is None or 'abrir' in query or query == '':
        url_video = ''
    
    bronser = 'chrome '
    url = f"-app=https://music.youtube.com/{url_video}"
    if bronser == 'microsoft-edge:':
        url = f"https://music.youtube.com/{url_video}"
        
    os.popen(f"start {bronser}{url}")
    
    pyautogui.sleep(5)
    pyautogui.hotkey('f')
    pyautogui.hotkey('f11')
    return f'{random.choice(ok)}, {random.choice(confirmation)} {query} no youtube'


def remove_aditional_terms(query, term, aditional_search_terms):
    query = query.replace('  ', ' ')
    query = query.replace(f'{term}', '_*_')
    for aditional_term in aditional_search_terms:
        if aditional_term in query:
            query = query.replace(f'{aditional_term} _*_', '_*_')
            query = query.replace(f'_*_ {aditional_term}', '_*_')
    return query.replace('_*_', '')


def if_its_a_command_play_in_youtube_music(message):  
    message = message.lower()
    query = message
    for term in search_terms:
        if term in message:
            query = remove_aditional_terms(query, term, aditional_search_terms)
            if query is not None:
                return play_in_youtube(query)
    return None

def get_first_video_(query):
    url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&maxResults=1&q={query}&key={GOOGLE_CLOUD_API_KEY}"
    response = requests.get(url)
    data = response.json()
    video_id = data['items'][0]['id']['videoId']
    return video_id

