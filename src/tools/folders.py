import os

def if_folder_not_exists_create_it(url):
    # Extrair o caminho do diretório
    dir_path = os.path.dirname(url)
    
    # Verificar se o diretório existe
    if not os.path.exists(dir_path):
        # Criar o diretório (e qualquer diretório pai necessário)
        os.makedirs(dir_path)
