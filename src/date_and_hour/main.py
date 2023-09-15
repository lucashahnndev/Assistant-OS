import time
import pytz
from datetime import datetime
def date_and_time():
    timezone = pytz.timezone('America/Sao_Paulo')
    return datetime.now(timezone)

def date_now():
    str_hora = date_and_time().strftime("%d/%m/%y")
    return str_hora

def time_now():
    str_hora = date_and_time().strftime("%H:%M:%S")
    return str_hora

def hour_now():
    str_hora = date_and_time().strftime("%H")
    return str_hora

def date_and_time_now():
    str_hora = date_and_time().strftime("%d/%m/%Y %H:%M")
    return str_hora

def month():
    str_month = date_and_time().strftime("%m")
    return str_month

def today():
    str_hora = date_and_time().strftime("%d")
    return str_hora

def year():
    str_hora = date_and_time().strftime("%y")
    return f'20{str_hora}'

def minutes():
    str_hora = date_and_time().strftime("%M")
    return str_hora

def seconds():
    str_hora = date_and_time().strftime("%S")
    return str_hora


hour = hour_now()


def shift():
    if hour > '0' and hour < '07':
        return 'Madrugada'

    if hour > '06' and hour < '13':
        return 'Manhã'

    if hour > '12' and hour < '19':
        return 'Tarde'

    if hour > '18' and hour < '24' and hour > '00':
        return 'Noite'

def greeting_shift():
    if hour > '0' and hour < '13':
        return 'bom dia'

    if hour > '12' and hour < '19':
        return 'boa Tarde'

    if hour > '18' and hour < '24' and hour > '00':
        return 'boa Noite'


def get_timezones():
    timezones = pytz.all_timezones
    return timezones