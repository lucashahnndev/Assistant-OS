import pyautogui



occurrences = (['maximizar tela', 'maximizar', 'maximiza', 'maximize', 'maximizar tela',
                'minimizar tela', 'minimizar', 'minimiza', 'minimize', 'minimizar tela',
                'fechar tela', 'fechar', 'fecha', 'feche', 'fechar a tela',
                'aumentar tela', 'aumente a tela', 'aumente tela',
                'windows', 'sair','mudo', 'ativar mudo', 'desativar o volume',
                'desativar o som', 'desativar o mudo',  'reativar o volume', 'reativar o som'
                'aumenta volume', 'aumenta o volume', 'aumenta o som','aumenta  som',
                'aumentar volume', 'aumentar o volume', 'aumentar o som','aumentar  som',
                'reduzir volume', 'reduzir o volume', 'reduzir o som', 'reduzir  som',
                'diminuir volume', 'diminuir o volume', 'diminuir o som', 'diminuir som'
                'diminui volume', 'diminui o volume', 'diminui o som', 'diminui som'
                "pausar video", "pausar filme", "pausar vídeo", 'pausar o video', 'pausar o filme', 'pause o video', 'pausa o filme', 'para o filme',
                "continuar video", "continuar filme", "continuar vídeo", 'continuar o video', 'continuar o filme',
                "proximo video","proxima musica","proximo episodio","proximo",
                "video anterior", "musica anterior","episodio anterior"
                ])


def screnn_is_maximized():
    # Obter as dimensões da tela
    screen_width, screen_height = pyautogui.size()

    # Obter as dimensões da janela atual
    window = pyautogui.getActiveWindow()
    window_width, window_height = window.size

    # Verificar se a janela está maximizada
    return (window_width, window_height) == (screen_width, screen_height)


def router_key_command(world):

    if 'proximo' in world:
        pyautogui.hotkey('fn', 'right')
        return f'OK indo para o proximo'

    if 'anterior' in world:
        pyautogui.hotkey('fn', 'left')
        return f'OK indo para anterior'

    if 'aumentar volume' in world or 'aumentar o volume' in world or 'aumentar o som' in world or 'aumenta volume' in world or 'aumenta o volume' in world or 'aumenta o som' in world:
        if 'todo' in world or 'tudo' in world or 'total' in world or 'totalmente' in world or 'completamente' in world or 'inteiramente' in world or 'inteiro' in world or 'maximo' in world:
            for i in range(100):
                pyautogui.press('volumeup')
            return f' Volume aumentado no máximo'
        for i in range(10):
            pyautogui.press('volumeup')
        return f' Volume aumentado'

    if 'reduzir volume' in world or 'reduzir o volume' in world or 'reduzir o som' in world or 'diminuir volume' in world or 'diminuir o volume' in world or 'diminuir o som' in world or 'reduzi volume' in world or 'reduzi o volume' in world or 'reduzi o som' in world or 'diminui volume' in world or 'diminui o volume' in world or 'diminui o som' in world:
        for i in range(10):
            pyautogui.hotkey('volumedown')
        return f' Volume reduzido'

    if 'pausar' in world or 'parar' in world or 'pausa' in world or 'para' in world or 'pause' in world:
        pyautogui.hotkey('space')
        return f' Video pausado'

    if 'aumente' in world or 'aumentar' in world or 'aumenta' in world:
        pyautogui.hotkey('win', 'up')

    if 'maximize' in world or 'maximizar' in world:
        pyautogui.hotkey('f11')
        return f' Tela maximizada'

    if 'minimize' in world or 'minimizar' in world:
        if screnn_is_maximized():
            pyautogui.hotkey('f11')
        else:
            pyautogui.hotkey('win', 'down')
        return f' Tela minimizada'

    if 'fechar a tela' in world or 'fechar' in world or 'sair' in world:
        pyautogui.hotkey('alt', 'f4')
        return f' Tela fechada'

    if 'windows' in world:
        pyautogui.hotkey('win')
        return f' Windows aberto'

    if 'mudo' in world or 'ativar mudo' in world or 'desativar o mudo' in world:
        pyautogui.hotkey('volumemute')
        return f' Mudo ativado'


def if_its_a_key_command(message):
    message = message.lower()
    query = message
    for term in occurrences:
        if term in message:
            if query is not None:
                return router_key_command(query)
    return None
