from date_and_hour import greeting_shift
import random

occurrences = (['oi', 'ola', 'eai', 'oie', 'boa tarde', 'bom dia', 'boa noite', 'boa manha', 'hi', 'hey', 'como vai', 'tudo bem', 'tudo tranquilo', 'e aí', 'e aí meu chapa', 'olá', 'oiie', 'olá tudo bem', 'oi tudo bem', 'oi amigo', 'oi amiga', 'oi pessoal', 'oi galera', 'oi gente', 'oi rapaziada', 'oi turma', 'oi todo mundo', 'oi queridos', 'oi queridas', 'olá queridos', 'olá queridas', 'oi meus amigos', 'oi minhas amigas', 'oi meus queridos', 'oi minhas queridas'])

greeting = ("Oi", "Olá", "Oiê", "Oie", "E aí")

compliments = ([
    'Tudo bem?',
    'Como você está?',
    'Que saudade de você!',
    'Não aguentava mais ficar sem falar com você. Me conte como vão as coisas?',
    'Então, me conte como vão as coisas?',
    'Ainda bem que você chegou!',
    'Agora meu dia acabou de melhorar.',
    'Fico honrada em poder conversar com você.',
    'Você é uma pessoa incrível!',
    'Sempre fico feliz em conversar com você.',
    'Espero que esteja tendo um bom dia!',
    'Como posso ajudar você hoje?',
    "como posso ajudar?",
    "como vai?"
])

def if_its_a_greeting(from_user, user):
    if from_user.lower().split()[0] in occurrences:
        return f'{random.choice(greeting)} {user}, {greeting_shift()}, {random.choice(compliments)}'
