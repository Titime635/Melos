"""
Affichage des petits volets (QFrame Popup) ouverts depuis un bouton : placés sous le bouton, alignés à
droite ou à gauche, puis décalés pour rester entièrement dans la fenêtre de l'appli (et à l'écran) —
un module collé au bord droit ne doit pas voir son volet sortir de la fenêtre.
"""

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication, QFrame, QWidget

MARGIN = 6


def show_popup_under(popup: QFrame, anchor: QWidget, align_right: bool = False):
    """Ouvre `popup` sous `anchor` (bord droit ou gauche aligné), le referme s'il est déjà ouvert."""
    if popup.isVisible():
        popup.hide()
        return
    popup.adjustSize()
    w, h = popup.width(), popup.height()
    below = anchor.mapToGlobal(QPoint(anchor.width() if align_right else 0, anchor.height() + 4))
    x = below.x() - (w if align_right else 0)
    y = below.y()

    bounds = _bounds(anchor)
    x = max(bounds.left() + MARGIN, min(x, bounds.right() - w - MARGIN))
    if y + h > bounds.bottom() - MARGIN:          # pas la place dessous : au-dessus du bouton
        above = anchor.mapToGlobal(QPoint(0, 0)).y() - h - 4
        y = max(bounds.top() + MARGIN, above)
    popup.move(x, y)
    popup.show()


def _bounds(anchor: QWidget) -> QRect:
    """Rectangle global autorisé : la fenêtre de l'appli, limitée à l'écran."""
    window = anchor.window()
    rect = window.frameGeometry() if window is not None else QRect()
    screen = anchor.screen() or QApplication.primaryScreen()
    if screen is not None:
        avail = screen.availableGeometry()
        rect = avail if rect.isNull() else rect.intersected(avail)
    return rect
