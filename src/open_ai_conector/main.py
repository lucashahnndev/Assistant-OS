import openai
from config import OPENAI_API_KEY, OPENAI_ORGANIZATION_ID, BOT_NAME

openai.organization = OPENAI_ORGANIZATION_ID
openai.api_key = OPENAI_API_KEY
# list = openai.Model.list()
# este codigo é um modulo de conexção com a api do open ai
# https://beta.openai.com/docs/api-reference/create-completion
# usa o modelo gpt-3.5-turbo
# usado para criar uma conversa
# a função deve receber uma pergunta e retornar uma resposta

messages_ = [
    {"role": "system", "content": "You are a helpful assistant. Your name is Lila , you were created by Lucas brinker Hann"},
    {"role": "user", "content": "What is your name"},
    {"role": "assistant", "content": "My name is Lila , I'm a virtual assistant "}
]

def response_to_user(mensagem):
    messages_.append({"role": "user", "content": mensagem})
    completion = openai.ChatCompletion.create(
        max_tokens=150,
        n=1,
        temperature=0.9,
        model="gpt-3.5-turbo",
        messages=messages_,
        
    )
    messages_.append({"role": "assistant", "content": str(completion.choices[0].message.content)})
    return completion.choices[0].message.content
