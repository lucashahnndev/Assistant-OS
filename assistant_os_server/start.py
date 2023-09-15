import subprocess
import time

# Inicie o aplicativo usando o subprocess
process = subprocess.Popen(["C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"])  # Substitua "nome_do_aplicativo" pelo nome do seu aplicativo

# Defina o tempo em segundos após o qual o processo será encerrado
tempo_para_encerrar = 10  # Por exemplo, para encerrar após 60 segundos

# Aguarde o tempo especificado
time.sleep(tempo_para_encerrar)

# Mate o subprocess
process.terminate()
