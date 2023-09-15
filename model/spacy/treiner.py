import json
import yaml
import random
from collections.abc import Iterable
# Carrega os dados de treinamento do arquivo YAML
with open('intent.yaml', 'r') as f:
    dados_treinamento = yaml.safe_load(f)

# Converte os dados de treinamento para JSON
dados_treinamento_json = json.dumps(dados_treinamento)

# Treina o modelo no spaCy
import spacy
from spacy.util import minibatch, compounding

# Cria um novo modelo vazio no spaCy
import spacy

nlp = spacy.load('pt_core_news_sm')
sentencizer = nlp.create_pipe('sentencizer')
nlp.add_pipe('sentencizer')




# Configura os dados de treinamento para o componente
DATA = json.loads(dados_treinamento_json)
TRAIN_DATA = []
for intent in DATA['intents']:
    for example in intent['phrases']:
        TRAIN_DATA.append((example, {'intent': intent['name']}))

for epoch in range(5):
    random.shuffle(TRAIN_DATA)
    batches = minibatch(TRAIN_DATA, size=compounding(4.0, 32.0, 1.001))
    losses = {}
    for batch in batches:
        print(batch)
        texts, annotations = zip(*batch)
        nlp.update(
            texts,
            annotations,
            drop=0.5,
            losses=losses,
        )

# Salva o modelo treinado
nlp.to_disk("meu_modelo_spacy")


""" # Carrega o modelo treinado
nlp = spacy.load("meu_modelo_spacy")

# Define a frase de entrada para classificar
frase = "Abra o vídeo do gato engraçado no YouTube"

# Processa a frase de entrada com o modelo
doc = nlp(frase)

# Obtém a intenção com maior probabilidade
intencao = max(doc.cats, key=doc.cats.get)

# Obtém o objeto de interesse correspondente à intenção
objeto_de_interesse = None
for ent in doc.ents:
    if ent.label_ == "OBJETO_DE_INTERESSE":
        objeto_de_interesse = ent.text
        break

# Imprime a intenção e o objeto de interesse correspondente
print(f"Intenção: {intencao}")
print(f"Objeto de interesse: {objeto_de_interesse}")
 """