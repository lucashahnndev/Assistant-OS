from geopy.geocoders import Nominatim
import requests
import os
import sys
from tools.folders import if_folder_not_exists_create_it

#obter o cominho do arquivo
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
#ir para parent_dir
sys.path.append(parent_dir)

cache_file = f'{parent_dir}\\data\\cache\\location_cache.txt'
if_folder_not_exists_create_it(cache_file)

def get_location():
    # Obter o endereço IP do usuário
    ip_address = requests.get('https://api.ipify.org').text

    # Verificar se o cache já contém as informações de localização para o endereço IP
    try:
        with open(cache_file, 'r') as f:
            cache_data = f.read().split(',')
            cache_ip = cache_data[0]
            cache_lat = float(cache_data[1])
            cache_lon = float(cache_data[2])
            if cache_ip == ip_address:
                return cache_lat, cache_lon
    except:
        pass

    # Se as informações de localização não estiverem no cache, obter a localização a partir do endereço IP
    geolocator = Nominatim(user_agent='myapp', timeout=15)
    location = geolocator.geocode(ip_address)

    # Salvar as informações de localização no cache
    with open(cache_file, 'w') as f:
        f.write(f"{ip_address},{location.latitude},{location.longitude}")

    # Retornar a latitude e longitude da localização
    return location.latitude, location.longitude
