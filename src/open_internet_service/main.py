import re
import os
import sys
import time
from selenium import webdriver
from unidecode import unidecode
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


#obter o cominho do arquivo
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
#ir para parent_dir
sys.path.append(parent_dir)


os.environ['PATH'] += os.pathsep + os.path.join(parent_dir,"tools")


def open_internet_app(app, url):
    profile = os.path.join(parent_dir,"data", "app_profile", str(app))
    options = webdriver.ChromeOptions()
    options = Options()
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument('--start-fullscreen')
    options.add_argument('--disable-extensions')
    options.add_argument(f'--app={url}')
    options.add_argument('--disable-infobars')
    options.add_argument('--disable-translate')
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-web-security')
    options.add_argument('--disable-notifications')
    options.add_argument('--disable-popup-blocking')
    options.add_argument('--disable-save-password-bubble')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3')
    options.add_argument(r"user-data-dir={}".format(profile))
    service = webdriver.chrome.service.Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.get(url)
    while True:
        time.sleep(1)
        try:
            # Tenta encontrar um elemento qualquer na página para verificar se ainda está aberta
            driver.find_element('xpath', '//html')
        except Exception as e:
            print(e)
            # Se não encontrar, significa que a janela foi fechada, então o loop é interrompido
            break



if __name__ == '__main__':
    """ app = 'netflix'
    url = 'https://www.netflix.com/br/'
    open_internet_app(app, url) """
