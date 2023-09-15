import os

folder_path = "/path/to/folder"  # caminho da pasta
files = os.listdir(folder_path)  # lista de arquivos na pasta

# filtra apenas os arquivos YAML
yaml_files = [file for file in files if file.endswith('.yml') or file.endswith('.yaml')]

# imprime a lista de arquivos YAML
print(yaml_files)



from rasa.nlu.model import Interpreter

model_directory = './models/nlu/default/nlu'
interpreter = Interpreter.load(model_directory)

message = "Olá, como posso ajudar?"
result = interpreter.parse(message)

print(result)
