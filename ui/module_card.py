"""
Carte de base de tous les modules (presets, tuner, batterie, looper, tempo, setlist).

Remplace le HeaderCardWidget de Fluent, dont l'en-tête (48 px) et les marges (24 px) mangeaient
~70 px avant le premier élément utile. Ici : un en-tête compact (~30 px) avec un point de la couleur
du module, le titre, et à droite un emplacement pour les actions du module (engrenage...), puis un
contenu aux marges serrées.

API compatible avec HeaderCardWidget pour les modules : `setTitle`, `viewLayout` (QHBoxLayout où
poser le contenu), `headerView`. En plus : `add_header_action(widget)` et `chrome_height()` (hauteur
prise par l'en-tête et les marges, pour que les modules adaptatifs calculent leur hauteur de base).
"""

from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import SimpleCardWidget, StrongBodyLabel

# Couleur d'identité de chaque module (même palette que les couleurs de preset)
MODULE_COLORS = {
    "presets": "#61D149",
    "tuner": "#46D1E6",
    "drums": "#E98D32",
    "loop": "#DF74D6",
    "tempo": "#F2C94C",
    "setlist": "#2C75EE",
}

HEADER_HEIGHT = 30
VIEW_MARGINS = (12, 8, 12, 12)   # gauche, haut, droite, bas
ACTION_SIZE = 24


class _Dot(QWidget):
    def __init__(self, color: str | None, parent=None):
        super().__init__(parent)
        self._color = QColor(color) if color else None
        self.setFixedSize(10, 10)

    def set_color(self, color: str | None):
        self._color = QColor(color) if color else None
        self.update()

    def paintEvent(self, _event):
        if self._color is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self._color)
        p.drawEllipse(QRectF(0.5, 0.5, 9, 9))
        p.end()


class ModuleCard(SimpleCardWidget):
    def __init__(self, parent=None, accent: str | None = None):
        super().__init__(parent)
        self.headerView = QWidget(self)
        self.headerView.setFixedHeight(HEADER_HEIGHT)
        self.headerLayout = QHBoxLayout(self.headerView)
        self.headerLayout.setContentsMargins(12, 0, 6, 0)
        self.headerLayout.setSpacing(8)
        self._dot = _Dot(accent, self.headerView)
        self._title = StrongBodyLabel("", self.headerView)
        self.headerLayout.addWidget(self._dot)
        self.headerLayout.addWidget(self._title)
        self.headerLayout.addStretch()

        self.separator = QFrame(self)
        self.separator.setFixedHeight(1)
        self.separator.setStyleSheet("background: rgba(128,128,128,0.20); border: none;")

        self.view = QWidget(self)
        self.viewLayout = QHBoxLayout(self.view)
        self.viewLayout.setContentsMargins(*VIEW_MARGINS)

        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.addWidget(self.headerView)
        self.vBoxLayout.addWidget(self.separator)
        self.vBoxLayout.addWidget(self.view, stretch=1)

    def setTitle(self, title: str):
        self._title.setText(title)

    def getTitle(self) -> str:
        return self._title.text()

    def set_accent(self, color: str | None):
        self._dot.set_color(color)

    def add_header_action(self, widget: QWidget):
        """Pose un petit bouton à droite de l'en-tête (engrenage du module, etc.)."""
        widget.setFixedSize(QSize(ACTION_SIZE + 4, ACTION_SIZE))
        self.headerLayout.addWidget(widget)

    def chrome_height(self) -> int:
        """Hauteur de tout ce qui n'est pas le contenu : en-tête, filet et marges haut/bas."""
        return HEADER_HEIGHT + 1 + VIEW_MARGINS[1] + VIEW_MARGINS[3]
