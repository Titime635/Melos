"""
Icônes de la barre latérale dessinées en SVG (les icônes Fluent n'ont ni clavier,
ni prise, ni interrupteur, et `CANCEL` y est une flèche "annuler", pas un "non").

Les couleurs d'état sont fixes (vert / rouge / bleu, lisibles en thème clair comme
sombre) ; seule l'icône clavier suit le thème, d'où `refresh` à appeler quand il
change (cf MainWindow).
"""

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from qfluentwidgets import isDarkTheme

GREEN = "#2ecc71"
RED = "#e74c3c"
BLUE = "#3b9eff"
GREY = "#8a8a8a"

_SIZE = 64  # rendu haute définition, réduit par Qt à 16 px dans la barre


def _icon(svg_body: str) -> QIcon:
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{svg_body}</svg>'
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    image = QImage(_SIZE, _SIZE, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter)
    painter.end()
    return QIcon(QPixmap.fromImage(image))


def keyboard_icon() -> QIcon:
    c = "#ffffff" if isDarkTheme() else "#202020"
    return _icon(
        f'<rect x="2" y="6" width="20" height="12" rx="2.2" fill="none" stroke="{c}" stroke-width="1.8"/>'
        f'<g fill="{c}"><rect x="5" y="9" width="2.2" height="2.2"/><rect x="8.9" y="9" width="2.2" height="2.2"/>'
        f'<rect x="12.8" y="9" width="2.2" height="2.2"/><rect x="16.7" y="9" width="2.2" height="2.2"/>'
        f'<rect x="7" y="13.6" width="10" height="2"/></g>'
    )


def toggle_icon(mode: str) -> QIcon:
    """Interrupteur : vert = global, bleu = fenêtre active seulement, gris vide = désactivé."""
    if mode == "off":
        return _icon(
            f'<rect x="2.5" y="7" width="19" height="10" rx="5" fill="none" stroke="{GREY}" stroke-width="1.8"/>'
            f'<circle cx="7.5" cy="12" r="3" fill="{GREY}"/>'
        )
    color = GREEN if mode == "global" else BLUE
    return _icon(
        f'<rect x="2" y="6.5" width="20" height="11" rx="5.5" fill="{color}"/>'
        f'<circle cx="16.5" cy="12" r="3.6" fill="#ffffff"/>'
    )


def plug_icon(connected: bool) -> QIcon:
    """Prise verte (connecté) ou prise rouge barrée (déconnecté)."""
    color = GREEN if connected else RED
    body = (
        f'<g stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none">'
        f'<path d="M9 3v5M15 3v5"/><path d="M6 8h12v3a6 6 0 0 1-12 0z"/><path d="M12 17v4"/></g>'
    )
    if not connected:
        body += f'<path d="M3.5 3.5L20.5 20.5" stroke="{color}" stroke-width="2.4" stroke-linecap="round"/>'
    return _icon(body)


def transport_icon(kind: str, color: str) -> QIcon:
    """Icônes des touches du looper : record, overdub, play, stop, clear, wait (horloge)."""
    shapes = {
        "record": f'<circle cx="12" cy="12" r="6.5" fill="{color}"/>',
        "overdub": (f'<circle cx="12" cy="12" r="6.5" fill="none" stroke="{color}" stroke-width="2"/>'
                    f'<path d="M12 8.5v7M8.5 12h7" stroke="{color}" stroke-width="2" stroke-linecap="round"/>'),
        "play": f'<path d="M8 5.5v13l11-6.5z" fill="{color}"/>',
        "stop": f'<rect x="6.5" y="6.5" width="11" height="11" rx="1.5" fill="{color}"/>',
        "clear": (f'<g fill="none" stroke="{color}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">'
                  f'<path d="M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12M10.5 11v5M13.5 11v5"/></g>'),
        "cancel": (f'<path d="M7 7l10 10M17 7L7 17" stroke="{color}" stroke-width="2.2" stroke-linecap="round"/>'),
    }
    return _icon(shapes[kind])