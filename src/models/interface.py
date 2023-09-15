import pygame
import sounddevice as sd
import numpy as np
import threading
import pystray
from PIL import Image
import sys

import os
parent_dir = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))


class AssistantInterface:
    def __init__(self, name='Assistant'):
        self.name = name
        self.screen_size = (600, 600)
        self.icon_size = 200
        self.icon_file = f'{parent_dir}/images/logo.png'
        self.icon_image = pygame.image.load(self.icon_file)
        self.icon_image = pygame.transform.scale(
            self.icon_image, (self.icon_size, self.icon_size))
        self.icon_position = (
            self.screen_size[0]//2 - self.icon_size//2, self.screen_size[1]//2 - self.icon_size//2)
        self.circle_position = (self.screen_size[0]//2, self.screen_size[1]//2)
        self.circle_radius = self.icon_size // 3
        self.max_radius = self.icon_size
        self.color = (0, 255, 0)
        self.assistantColor = (236, 28, 36)
        self.paused = False

        # text
        self.user_text = ""
        self.assistant_text = ""

        # initialize audio stream
        self.stream = sd.InputStream(channels=1, callback=self.process_audio)
        self.volume_threshold = 0.01

        # initialize pygame window

    def start(self):
        pygame.init()
        pygame.display.set_icon(pygame.image.load(self.icon_file))
        self.screen = pygame.display.set_mode(self.screen_size)
        pygame.display.set_caption(self.name)
        self.clock = pygame.time.Clock()
        self.running = True
        self.stream.start()
        while True:
            try:
                # check events
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self.paused = True
                        pygame.display.iconify()
                    elif event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_SPACE:
                            self.paused = not self.paused

                # update display if not paused
                if not self.paused:
                    # Update display if not paused
                    font = pygame.font.Font(None, 16)
                    user_text = font.render(
                        f"Você:    {self.user_text}", True, (0, 0, 0))
                    self.screen.blit(user_text, (50, 500))
                    assistant_text = font.render(
                        f" {self.name}:    {self.assistant_text}", True, (0, 0, 0))
                    self.screen.blit(assistant_text, (50, 550))
                    pygame.display.update()
                    self.clock.tick(60)
            except Exception as e:
                print(e)
        # stop audio stream
        self.stream.stop()

    def restart(self):
        self.paused = False
        pygame.display.toggle_fullscreen()

    def stop(self):
        self.running = False

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def assistant_color(self):
        self.color = self.assistantColor

    def user_color(self):
        self.color = (0, 255, 0)

    def update_user_text(self, text):
        self.user_text = text
        font = pygame.font.Font(None, 16)
        user_text = font.render(f"Você:    {text}", True, (0, 0, 0))
        self.screen.blit(user_text, (50, 500))
        pygame.display.update()

    def update_assistant_text(self, text):
        self.assistant_text = text
        font = pygame.font.Font(None, 16)
        assistant_text = font.render(f"assistant:    {text}", True, (0, 0, 0))
        self.screen.blit(assistant_text, (50, 550))
        pygame.display.update()

    def process_audio(self, audio_data, frames, time, status):
        if self.paused:
            return

        if status:
            print(f"Error: {status}")
        volume = np.abs(audio_data).mean()
        # update circle radius based on audio volume
        radius = int(self.circle_radius + volume /
                     self.volume_threshold * (self.max_radius - self.circle_radius))
        # draw circle and icon
        self.screen.fill((255, 255, 255))
        radius = (radius / 3000) * 100
        pygame.draw.circle(self.screen, self.color,
                           self.circle_position, radius, 3)
        self.screen.blit(self.icon_image, self.icon_position)


def assistant_tray(name='Assistant', icon_file=f'{parent_dir}/images/logo.png'):
    # Carrega a imagem do ícone
    image = Image.open(icon_file)
    # Cria um objeto do tipo Menu

    def fechar_janela():
        pygame.quit()
        sys.exit(0)

    def open_assistant():
        interface = AssistantInterface(name=name)
        interface.start()


    menu = pystray.Menu(pystray.MenuItem("Sair", lambda: fechar_janela(
    )), pystray.MenuItem(f"Abrir {name}", lambda: open_assistant()))
    # Cria o ícone da bandeja do sistema
    tray_icon = pystray.Icon(name, image, name, menu)
    # Retorna o objeto do ícone da bandeja do sistema
    return tray_icon


if __name__ == '__main__':
    import os
    parent_dir = os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))

    icon_file = f'{parent_dir}/images/logo.png'
    interface = AssistantInterface(name='Assistente')

    tray_icon = assistant_tray()
    # Inicia o loop da aplicação
    tray_icon.run()
