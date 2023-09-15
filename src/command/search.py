import random
import os
import threading

search_terms = ['pesquisar ', 'pesquise', 'pesquisa',
                'procurar', 'procure', 'busque', 'buscar', 'busca']
aditional_search_terms = ['sobre', 'sobre o', 'sobre a', 'por','faça uma', 'realize uma','de']

confirmation = ([
    'pesquisando por',
    'procurando por',
    'procurando na internet por',
    'fazendo uma pesquisa na internet por',
    'pesquisando na internet por',
    'fazendo uma pesquisa por'])
ok = (["ok", "certo", "entendido", "sim", "claro"])


edge_terms_list = ['no edge', 'pelo navegador edge', 'usando o edge','usando edge']
chrome_terms_list = ['no chrome', 'pelo navegador chrome', 'usando o chrome','usando chrome']
google_terms_list = ['no google', 'pelo navegador google', 'usando o google','usando google']
bing_terms_list = ['no bing', 'pelo motor bing', 'usando o bing','usando bing']
youtube_terms_list = ['no youtube', 'pelo motor youtube', 'usando o youtube','usando youtube']

def search_in_bronser(query):
    bronser = ''
    bronser_name = ''
    bronser_motor = ''

    if 'chrome' in query:
        bronser = 'chrome '
        bronser_name = 'no navegador google chrome'
        for term in chrome_terms_list:
            query = query.replace(term, '')
   
    if 'edge' in query:
        bronser = 'microsoft-edge:'
        bronser_name = 'no navegador microsoft edge'
        for term in edge_terms_list:
            query = query.replace(term, '')
            
    url = f"https://www.google.com/search?q="

    if 'google' in query:
        bronser_motor = 'usando google'
        for term in google_terms_list:
            query = query.replace(term, '')

    if 'bing' in query:
        url = f"https://www.bing.com/search?q="
        bronser_motor = 'usando Bing'
        for term in bing_terms_list:
            query = query.replace(term, '')   
            
    if 'youtube' in query:
        bronser = 'chrome '
        url = f"-app=https://www.youtube.com/results?search_query="
        if bronser == 'microsoft-edge:':
            url = f"https://www.youtube.com/results?search_query="
        bronser_motor = 'usando Youtube'
        for term in youtube_terms_list:
            query = query.replace(term, '')   
             
             
    os.popen(f"start {bronser}{url}{query.replace(' ', '+')}")
    
    return f'{random.choice(ok)}, {random.choice(confirmation)} {query} {bronser_motor} {bronser_name}'


def remove_aditional_terms(query, term, aditional_search_terms):
    query = query.replace('  ', ' ')
    query = query.replace(f'{term}', '_*_')
    for aditional_term in aditional_search_terms:
                if aditional_term in query:
                        query = query.replace(f'{aditional_term} _*_', '_*_')
                        query = query.replace(f'_*_ {aditional_term}', '_*_')
    return query.replace('_*_', '')


def if_its_a_command_search(message):
    message = message.lower()
    query = message
    for term in search_terms:
        if term in message:
            query = remove_aditional_terms(query, term, aditional_search_terms)
            if query is not None:
                return search_in_bronser(query)
    return None
