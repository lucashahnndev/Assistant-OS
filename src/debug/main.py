import sys
import os
from date_and_hour import date_and_time_now
def log(error , file):
    path = file.split('/')
    path = path[:-1]
    path_ok = ''

    for i in path:
        path_ok = f'{path_ok}/{i}'
    
    path_ok = path_ok[1:]
    if os.path.exists(path_ok) == False:
            print(f'{date_and_time_now()} creating folder "{path_ok}"')
            os.mkdir(path_ok)
            
    if type(error) == "str":
        with open(file, 'a', encoding='utf8') as log:
            log.write(f"{date_and_time_now()} - {error}\n")
            return
    try:
        file_error = error.__traceback__.tb_frame.f_code.co_filename
        function_error = error.__traceback__.tb_frame.f_code.co_name
        line_error = error.__traceback__.tb_lineno
        error =  f"{date_and_time_now()} - error in file {file_error}, function {function_error}, line {line_error}, error{repr(error)}\n"
        with open(file, 'a', encoding='utf8') as log:
            log.write(error)
    except Exception as error2:
        with open(file, 'a', encoding='utf8') as log:
            log.write(f"{date_and_time_now()} - {error}\n")
        with open( 'logs/debug_error.log', 'a', encoding='utf8') as log:
            log.write(f"{date_and_time_now()} - {error2}\n")
            