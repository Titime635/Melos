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
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import SimpleCardWidget, StrongBodyLabel, isDarkTheme, qconfig

from ui.theme import MODULE_COLORS, mix, pal, qc   # noqa: F401  (MODULE_COLORS réexporté pour les panneaux)

# Couleur d'identité de chaque module : palette douce commune (ui/theme.py)
HEADER_HEIGHT = 30
VIEW_MARGINS = (12, 8, 12, 12)   # gauche, haut, droite, bas
ACTION_SIZE = 24


def paint_glyph(p: QPainter, name: str, color: QColor, size: float = 16.0):
    """Petit pictogramme au trait (grille 16 x 16) : un par module. Dessiné à la main : zéro fichier, net à toutes les tailles."""
    p.save()
    p.scale(size / 16.0, size / 16.0)
    pen = QPen(color, 1.5)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    path = QPainterPath()
    if name == "presets":                      # quatre emplacements
        for x, y in ((2, 2), (9, 2), (2, 9), (9, 9)):
            path.addRoundedRect(QRectF(x, y, 5, 5), 1.4, 1.4)
    elif name == "tuner":                      # diapason
        path.moveTo(5, 1.5); path.lineTo(5, 6.5); path.quadTo(5, 10, 8, 10); path.quadTo(11, 10, 11, 6.5)
        path.lineTo(11, 1.5); path.moveTo(8, 10); path.lineTo(8, 14.5)
    elif name == "drums":                      # fût + baguettes
        path.addEllipse(QRectF(2, 7, 12, 4))
        path.moveTo(2, 9); path.lineTo(2, 13); path.quadTo(8, 16, 14, 13); path.lineTo(14, 9)
        path.moveTo(3, 1.5); path.lineTo(7, 5.5); path.moveTo(13, 1.5); path.lineTo(9, 5.5)
    elif name == "loop":                       # flèche circulaire
        path.arcMoveTo(QRectF(2.5, 2.5, 11, 11), 40)
        path.arcTo(QRectF(2.5, 2.5, 11, 11), 40, 280)
        path.moveTo(11.2, 1.8); path.lineTo(11.2, 5.4); path.lineTo(7.8, 4.6)
    elif name == "tempo":                      # métronome
        path.moveTo(5, 14.5); path.lineTo(11, 14.5); path.lineTo(9.6, 1.8); path.lineTo(6.4, 1.8); path.closeSubpath()
        path.moveTo(8, 12); path.lineTo(10.6, 5)
    elif name == "setlist":                    # liste
        for y in (3.5, 8, 12.5):
            path.moveTo(6.5, y); path.lineTo(14, y)
            path.moveTo(2.2, y); path.lineTo(2.3, y)
    else:
        path.addEllipse(QRectF(4.5, 4.5, 7, 7))
    p.drawPath(path)
    p.restore()


class _Dot(QWidget):
    """Point de couleur du module : plein avec un léger halo quand le module est actif, simple anneau gris quand il est coupé."""

    def __init__(self, color: str | None, parent=None):
        super().__init__(parent)
        self._color = QColor(color) if color else None
        self._glyph = next((k for k, v in MODULE_COLORS.items() if v == color), None) if color else None
        self._on = True
        self.setFixedSize(18, 18)

    def set_color(self, color: str | None):
        self._color = QColor(color) if color else None
        self._glyph = next((k for k, v in MODULE_COLORS.items() if v == color), None) if color else None
        self.update()

    def set_on(self, on: bool):
        self._on = on
        self.update()

    def paintEvent(self, _event):
        if self._color is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._glyph:                       # pictogramme du module : couleur du module quand il est actif, gris quand il est coupé
            p.translate(1, 1)
            col = self._color if isDarkTheme() else mix(self._color, qc("text"), 0.15)   # en clair : un peu assombri
            paint_glyph(p, self._glyph, col if self._on else qc("faint"))
            p.end()
            return
        if self._on:
            halo = QColor(self._color)
            halo.setAlpha(60)
            p.setPen(Qt.NoPen)
            p.setBrush(halo)
            p.drawEllipse(QRectF(1, 1, 14, 14))
            p.setBrush(self._color)
            p.drawEllipse(QRectF(4, 4, 8, 8))
        else:
            p.setPen(QPen(qc("faint"), 1.6))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(4.5, 4.5, 7, 7))
        p.end()


def notify_power(widget: QWidget, on: bool):
    """Prévient la carte de module qui contient `widget` que son module est actif / coupé (interrupteur de l'en-tête)."""
    w = widget.parentWidget()
    while w is not None:
        if isinstance(w, ModuleCard):
            w.set_power(on)
            return
        w = w.parentWidget()


class ModuleCard(SimpleCardWidget):
    def __init__(self, parent=None, accent: str | None = None):
        super().__init__(parent)
        self.headerView = QWidget(self)
        self.headerView.setFixedHeight(HEADER_HEIGHT)
        self.headerLayout = QHBoxLayout(self.headerView)
        self.headerLayout.setContentsMargins(12, 0, 6, 0)
        self.headerLayout.setSpacing(8)
        self._power_on = None            # None : module sans interrupteur ; True / False : actif / coupé
        self._dot = _Dot(accent, self.headerView)
        self._title = StrongBodyLabel("", self.headerView)
        self.headerLayout.addWidget(self._dot)
        self.headerLayout.addWidget(self._title)
        self.headerLayout.addStretch()

        self.separator = QFrame(self)
        self.separator.setFixedHeight(1)
        self._restyle_separator()
        qconfig.themeChanged.connect(lambda *_: self._restyle_separator())

        self.view = QWidget(self)
        self.viewLayout = QHBoxLayout(self.view)
        self.viewLayout.setContentsMargins(*VIEW_MARGINS)

        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.addWidget(self.headerView)
        self.vBoxLayout.addWidget(self.separator)
        self.vBoxLayout.addWidget(self.view, stretch=1)

    def _restyle_separator(self):
        self.separator.setStyleSheet(f"background: {pal()['border']}; border: none;")

    def paintEvent(self, _event):
        """Même carte que la partition : fond « surface » de la palette, fine bordure, coins de 12 px."""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = pal()
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        p.setBrush(QColor(c["surface"]))
        p.setPen(QPen(QColor(c["border"]), 1))
        p.drawRoundedRect(rect, 12, 12)
        # liseré de couleur en haut de la carte : la couleur du module quand il est actif (en dégradé), un simple filet gris
        # quand il est coupé
        col = self._dot._color if self._dot.isVisible() else None
        if col is not None:
            path = QPainterPath()
            path.addRoundedRect(rect, 12, 12)
            p.setClipPath(path)
            p.setPen(Qt.NoPen)
            if self._power_on is False:
                p.setBrush(QColor(c["border"]))
                p.drawRect(QRectF(rect.left(), rect.top(), rect.width(), 3))
            else:
                g = QLinearGradient(rect.left(), 0, rect.right(), 0)
                end = QColor(col)
                end.setAlphaF(0.25)
                g.setColorAt(0.0, col)
                g.setColorAt(1.0, end)
                p.setBrush(g)
                p.drawRect(QRectF(rect.left(), rect.top(), rect.width(), 3))
        p.end()

    def set_power(self, on: bool | None):
        """Module actif / coupé (None : sans interrupteur) : point plein ou anneau, titre atténué, liseré de couleur ou gris."""
        if on == self._power_on:
            return
        self._power_on = on
        self._dot.set_on(on is not False)
        self._title.setStyleSheet(f"color: {pal()['faint' if on is False else 'text']};" if on is False else "")
        self.update()

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


class PageCard(ModuleCard):
    """Carte des pages Réglages, Raccourcis et Éditeur de presets : exactement la carte des modules du Dashboard (fond, bordure,
    coins, titre), sans le point de couleur et avec des marges plus généreuses (formulaires)."""

    PAGE_HEADER = 38
    PAGE_MARGINS = (18, 12, 18, 16)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dot.hide()
        self.headerView.setFixedHeight(self.PAGE_HEADER)
        self.headerLayout.setContentsMargins(18, 0, 10, 0)
        self.viewLayout.setContentsMargins(*self.PAGE_MARGINS)

    def chrome_height(self) -> int:
        return self.PAGE_HEADER + 1 + self.PAGE_MARGINS[1] + self.PAGE_MARGINS[3]