"""
Quels codecs vidéo/audio le QtWebEngine de ton PySide6 sait-il lire ? (YouTube : « Impossible de lire cette vidéo avec
votre navigateur » = il manque le codec dans lequel la vidéo est servie.)

    .venv\\Scripts\\python.exe tools\\codec_check.py
"""
import json
import sys

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

TYPES = {
    "H.264 (mp4)": 'video/mp4; codecs="avc1.42E01E"',
    "AAC (mp4)": 'audio/mp4; codecs="mp4a.40.2"',
    "VP9 (webm)": 'video/webm; codecs="vp9"',
    "VP8 (webm)": 'video/webm; codecs="vp8"',
    "AV1": 'video/mp4; codecs="av01.0.05M.08"',
    "Opus (webm)": 'audio/webm; codecs="opus"',
}

app = QApplication(sys.argv)
view = QWebEngineView()
view.setHtml("<html><body>test</body></html>")


def run(_ok):
    js = "JSON.stringify(Object.fromEntries(Object.entries(%s).map(([k,t])=>[k,MediaSource.isTypeSupported(t)])))" % json.dumps(TYPES)
    view.page().runJavaScript(js, done)


def done(raw):
    for name, ok in json.loads(raw).items():
        print(f"{name:14s} {'OUI' if ok else 'non'}")
    app.quit()


view.loadFinished.connect(run)
QTimer.singleShot(15000, app.quit)
app.exec()
