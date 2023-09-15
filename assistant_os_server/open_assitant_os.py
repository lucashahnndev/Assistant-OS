import os
import pyautogui
# Importe o módulo http.server
import http.server
import threading
import time
import keyboard

import keyboard
from pynput import keyboard
import pygetwindow as gw
import screeninfo
# system_pressf11 = False


def web_server():
    # Escolha a porta em que deseja executar o servidor
    port = 8007

    server_address = ("", port)
    handler = http.server.SimpleHTTPRequestHandler

    with http.server.HTTPServer(server_address, handler) as server:
        print(f"Servidor rodando na porta {port}")
        server.serve_forever()

def open_os_page():
    os.popen('start chrome --start-fullscreen --app="http://localhost:8007"')
    time.sleep(1)
    #pyautogui.hotkey('F11')

    time.sleep(1)


def cancel_the_event_f11():
    while True:
        def on_press(key):
            try:
                if system_pressf11 == False:
                    if key == keyboard.Key.f11:
                        print("Tecla F11 pressionada, impedindo a propagação.")
                        time.sleep(0.5)
                        pyautogui.hotkey('F11')
                        return False  # Impede a propagação da tecla F11
                else:
                    system_pressf11 = False
            except AttributeError:
                pass

        # Configurar o ouvinte de teclado
        listener = keyboard.Listener(on_press=on_press)

        # Iniciar o ouvinte
        listener.start()

        # Manter o programa em execução para continuar capturando eventos de teclado
        listener.join()

def close_first_window():
    # Obtém todas as janelas abertas
    janelas_abertas = gw.getAllTitles()

    if janelas_abertas:
        # Obtém o título da primeira janela
        titulo_janela = janelas_abertas[0]

        # Obtém a janela pelo título
        janela = gw.getWindowsWithTitle(titulo_janela)[0]

        # Fecha a janela
        janela.close()

        # Aguarda um momento para garantir o fechamento
        pyautogui.sleep(1)



def cancel_the_event_win():
    while True:
        def on_press(key):
            try:
                if key == keyboard.Key.cmd:
                    print("Tecla win pressionada, impedindo a propagação.")
                    time.sleep(1)
                    pyautogui.hotkey('win')
                    time.sleep(0.5)
                    pyautogui.hotkey('alt', 'F4')
                    time.sleep(0.5)
                    pyautogui.hotkey('enter')
                    #close_first_window()
                    time.sleep(1)
                    open_os_page()
                    return False  # Impede a propagação da tecla F11
                if key == keyboard.Key.esc:
                    pyautogui.hotkey('alt', 'left')
                    return False  # Impede a propagação da tecla F11
            except AttributeError:
                pass

        # Configurar o ouvinte de teclado
        listener = keyboard.Listener(on_press=on_press)

        # Iniciar o ouvinte
        listener.start()

        # Manter o programa em execução para continuar capturando eventos de teclado
        listener.join()


def is_screen_fullscreen():
    while True:
        # Obtém a janela ativa
        janela_ativa = gw.getActiveWindow()

        if janela_ativa:
            # Obtém informações sobre a tela
            # Suponhamos que estamos verificando a tela primária
            tela = screeninfo.get_monitors()[0]
            print((
                janela_ativa.left == tela.x and
                janela_ativa.top == tela.y and
                janela_ativa.width == tela.width and
                janela_ativa.height == tela.height
            ))
            # Compara as dimensões da janela com as dimensões da tela
            if (
                janela_ativa.left == tela.x and
                janela_ativa.top == tela.y and
                janela_ativa.width == tela.width and
                janela_ativa.height == tela.height
            ):
                pass
            else:
                # system_pressf11 = True
                pyautogui.hotkey('F11')
            time.sleep(1)
        else:
            # system_pressf11 = True
            pyautogui.hotkey('F11')
        time.sleep(1)


server_thread = threading.Thread(target=web_server)
server_thread.start()



os.popen('start chrome --start-fullscreen --app="http://localhost:8007/cover.html"')
time.sleep(0.5)
open_os_page()


"""
f11_thread = threading.Thread(target=cancel_the_event_f11)
f11_thread.start() """

""" win_thread = threading.Thread(target=cancel_the_event_win)
win_thread.start()


fullscreem_thread = threading.Thread(target=is_screen_fullscreen)
fullscreem_thread.start()
 """
