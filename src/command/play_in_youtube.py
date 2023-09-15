import random
import os
import pyautogui
from config import GOOGLE_CLOUD_API_KEY
from googleapiclient.discovery import build


search_terms = ['pesquisar no youtube ', 'pesquise no youtube', 'pesquisa no youtube',
                'tocar no youtube', 'toque no youtube', 'toca no youtube',
                'abre no youtube', 'abrir no youtube', 'abra no youtube',
                'reproduzir no youtube', 'reproduza no youtube',
                'rode no youtube', 'rodar no youtube', 'roda no youtube',
                "no youtube", "youtube"
                ]

aditional_search_terms = ['sobre ', 'sobre o ', 'sobre a ', 'por ', 'faça uma ', 'realize uma ', 'de ',
                          'video de ', 'video do ', 'video da ',
                          'desenho do ', 'desenho da', 'desenho de ',
                          'filme do', 'filme da', 'filme de ',
                          'musica da ', 'musica de ', 'musica do ',
                          'filme de ', 'filme da ', 'filme do ',
                          'abrir', 'abrir o', 'o']

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
    confirmation_str = random.choice(confirmation)
    no = "no youtube"
    url_video = f'watch?v={get_first_video_(query)}'
    if query is None or query == '':
        url_video = ''
        confirmation_str = 'abrindo o youtube'
        no = ''

    bronser = 'chrome '
    url = f"-app=https://www.youtube.com/{url_video}"
    if bronser == 'microsoft-edge:':
        url = f"https://www.youtube.com/{url_video}"

    os.popen(f"start {bronser}{url}")

    pyautogui.sleep(5)
    pyautogui.hotkey('f')
    pyautogui.hotkey('f11')
    return f'{random.choice(ok)}, {confirmation_str} {query} {no}'


def remove_aditional_terms(query, term, aditional_search_terms):
    query = query.replace('  ', ' ')
    query = query.replace(f'{term}', '_*_')
    for aditional_term in aditional_search_terms:
        if aditional_term in query:
            query = query.replace(f'{aditional_term} _*_', '_*_')
            query = query.replace(f'_*_ {aditional_term}', '_*_')
    return query.replace('_*_', '')


def if_its_a_command_play_in_youtube(message):
    message = message.lower()
    query = message
    for term in search_terms:
        if term in message:
            query = remove_aditional_terms(query, term, aditional_search_terms)
            if query is not None:
                return play_in_youtube(query)
    return None


def get_first_video_(query):
    youtube_service = build('youtube', 'v3', developerKey=GOOGLE_CLOUD_API_KEY)
    search_response = youtube_service.search().list(
        q=query.replace(' ', '+'),
        part='id,snippet',
        type='video',
        videoDefinition='high',
        maxResults=1
    ).execute()
    video_id = search_response['items'][0]['id']['videoId']
    return video_id
