import sys
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *
from PyQt5.QtWebEngineWidgets import *
from PyQt5.QtWebEngineWidgets import QWebEnginePage, QWebEngineSettings


class WebPage(QMainWindow):
    def __init__(self):
        super().__init__()
        self.browser = QWebEngineView()
        # Configurar todas as permissões como habilitadas
        settings = self.browser.page().settings()
        settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.PluginsEnabled, True)
        settings.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.AutoLoadImages, True)
        settings.setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, True)
        settings.setAttribute(QWebEngineSettings.JavascriptCanAccessClipboard, True)
        settings.setAttribute(QWebEngineSettings.WebGLEnabled, True)
        settings.setAttribute(QWebEngineSettings.AutoLoadIconsForPage, True)
        settings.setAttribute(QWebEngineSettings.Accelerated2dCanvasEnabled, True)
        settings.setAttribute(QWebEngineSettings.FullScreenSupportEnabled, True)
        settings.setAttribute(QWebEngineSettings.AllowRunningInsecureContent, True)

        # Configurações específicas para conteúdo protegido (DRM)
        settings.setAttribute(QWebEngineSettings.JavascriptCanAccessClipboard, True)
        settings.setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, True)

        # Defina um User-Agent
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/88.0.4324.150 Safari/537.36"
        self.browser.page().profile().setHttpUserAgent(user_agent)


        self.browser.setUrl(QUrl("https://tricontroledeacesso.com/assistant/"))

        self.setCentralWidget(self.browser)
        self.setWindowTitle("Assistant OS")
        # self.setGeometry(100, 100, 800, 600)
        self.showMaximized()
        # self.showFullScreen()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    web_page = WebPage()
    web_page.show()
    sys.exit(app.exec_())
