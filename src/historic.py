import pickle
from os import path
import os
import sys
# obter o cominho do arquivo
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# ir para parent_dir
sys.path.append(parent_dir)


def historic_process(id_user, mensagem_from_bot):
    historic = []
    file_name = f"{parent_dir}/historic/{id_user}.pkl"
    if path.exists(file_name):
        open_file = open(file_name, "rb")
        historic = pickle.load(open_file)
        open_file.close()
        last_item = historic[-1]
    else:
        last_item = ''

    historic.append(mensagem_from_bot)
    open_file = open(file_name, "wb")
    pickle.dump(historic, open_file)
    open_file.close()
    return last_item


def query(id_user):
    historic = []
    file_name = f"{parent_dir}/historic/{id_user}.pkl"
    if path.exists(file_name):
        open_file = open(file_name, "rb")
        historic = pickle.load(open_file)
        open_file.close()
        return historic[-1]
    else:
        return None
