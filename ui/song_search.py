"""
Recherche d'un morceau par son nom (comme la barre de recherche de Songsterr) : on tape dans le champ de la page
Partition, une liste de résultats s'ouvre sous le champ, on en choisit un (souris ou flèches + Entrée) et il se charge.
Un lien Songsterr collé dans le champ reste accepté tel quel.
"""

import logging

from PySide6.QtCore import QPoint, QSize, QThread, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QFrame, QListWidget, QListWidgetItem, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, LineEdit, isDarkTheme

from tabs.client import SongHit, TabError, search_songs
from tabs.debug import dbg
from ui.track_list import _Elided

log = logging.getLogger("melos.tabs")

ROW_H = 54
MAX_ROWS = 8                                  # au-delà, la liste défile (contenu qui doit défiler)


def looks_like_url(text: str) -> bool:
    t = text.strip().lower()
    return t.startswith(("http://", "https://")) or "songsterr.com" in t


class SearchWorker(QThread):
    done = Signal(int, object)                # jeton de la recherche, list[SongHit]
    failed = Signal(int, str)

    def __init__(self, token: int, query: str, parent=None):
        super().__init__(parent)
        self._token, self._query = token, query

    def run(self):
        try:
            self.done.emit(self._token, search_songs(self._query))
        except TabError as exc:
            self.failed.emit(self._token, str(exc))
        except Exception as exc:
            log.exception("recherche")
            self.failed.emit(self._token, f"{type(exc).__name__}: {exc}")


class SearchEdit(LineEdit):
    """Champ de saisie qui laisse passer les flèches / Entrée / Échap à la liste de résultats."""
    move = Signal(int)                        # -1 = haut, +1 = bas
    accept = Signal()                         # Entrée sur un résultat surligné
    dismiss = Signal()                        # Échap ou perte du focus

    def __init__(self, parent=None):
        super().__init__(parent)
        self.popup_open = False

    def keyPressEvent(self, ev):
        if self.popup_open:
            if ev.key() in (Qt.Key_Down, Qt.Key_Up):
                self.move.emit(1 if ev.key() == Qt.Key_Down else -1)
                return
            if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.accept.emit()
                return
            if ev.key() == Qt.Key_Escape:
                self.dismiss.emit()
                return
        super().keyPressEvent(ev)

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        self.dismiss.emit()


class _Row(QWidget):
    def __init__(self, hit: SongHit, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(0)
        lay.addWidget(_Elided(BodyLabel, hit.title, self))
        sub = hit.artist + (f"  ·  {', '.join(hit.tracks[:4])}" if hit.tracks else "")
        lay.addWidget(_Elided(CaptionLabel, sub, self))


class SearchPopup(QListWidget):
    """Liste flottante sous le champ (fenêtre sans focus : on continue de taper pendant qu'elle est ouverte)."""
    chosen = Signal(object)                   # SongHit

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setMouseTracking(True)
        self.itemEntered.connect(lambda it: self.setCurrentItem(it) if it.flags() & Qt.ItemIsSelectable else None)
        self.itemClicked.connect(self._clicked)
        self._apply_theme()

    def _apply_theme(self):
        dark = isDarkTheme()
        bg, border = ("#2b2c33", "#43444e") if dark else ("#ffffff", "#cfd0d8")
        sel = "rgba(77,163,255,0.28)"
        self.setStyleSheet(f"QListWidget{{background:{bg};border:1px solid {border};border-radius:8px;outline:0}}"
                           f"QListWidget::item{{border-radius:6px}}"
                           f"QListWidget::item:selected{{background:{sel}}}")

    def _clicked(self, item):
        hit = item.data(Qt.UserRole)
        if hit is not None:
            self.chosen.emit(hit)

    def set_hits(self, hits: list[SongHit], message: str = ""):
        self.clear()
        if not hits:
            item = QListWidgetItem(message or "Aucun résultat")
            item.setFlags(Qt.NoItemFlags)
            item.setSizeHint(QSize(10, 40))
            item.setForeground(QColor("#9a9aa6"))
            self.addItem(item)
            return
        for h in hits:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, h)
            item.setSizeHint(QSize(10, ROW_H))
            self.addItem(item)
            self.setItemWidget(item, _Row(h, self))
        self.setCurrentRow(0)

    def move_selection(self, delta: int):
        n = self.count()
        if n == 0:
            return
        row = max(0, min(n - 1, self.currentRow() + delta))
        self.setCurrentRow(row)
        self.scrollToItem(self.currentItem())

    def current_hit(self):
        item = self.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def show_under(self, widget: QWidget):
        self._apply_theme()
        rows = min(MAX_ROWS, max(1, self.count()))
        h = sum(self.sizeHintForRow(i) for i in range(min(rows, self.count()))) + 10 if self.count() else 50
        pos = widget.mapToGlobal(QPoint(0, widget.height() + 4))
        self.setGeometry(pos.x(), pos.y(), widget.width(), h)
        self.show()
        self.raise_()
        dbg("recherche : liste affichée", self.count(), "lignes")
