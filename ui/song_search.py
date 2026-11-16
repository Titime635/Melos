"""
Recherche d'un morceau par son nom (comme la barre de recherche de Songsterr) : on tape dans le champ de la page
Partition, une liste de résultats s'ouvre sous le champ, on en choisit un (souris ou flèches + Entrée) et il se charge.
Un lien Songsterr collé dans le champ reste accepté tel quel.
"""

import logging

from PySide6.QtCore import QPoint, QSize, QThread, Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel

from tabs.client import SongHit, TabError, search_songs
from tabs.debug import dbg
from ui import tab_icons
from ui.theme import INSTRUMENT_COLORS, pal, qc, rgba, scrollbar_qss
from ui.track_list import _Elided

log = logging.getLogger("melos.tabs")

ROW_H = 56
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


def _kind_of(name: str) -> str:
    """Famille d'affichage d'un nom d'instrument de résultat de recherche (« Distortion Guitar » → guitar…)."""
    n = (name or "").lower()
    for kind, words in (("vocals", ("vocal", "voice", "voix", "choir", "singer")), ("drums", ("drum", "perc", "batter")),
                        ("bass", ("bass",)), ("guitar", ("guitar", "banjo-gt"))):
        if any(w in n for w in words):
            return kind
    return tab_icons.instrument_kind(name, "other")


class _Row(QWidget):
    """Une ligne de résultat : pastille de l'instrument principal, titre / artiste, puces des instruments présents."""

    def __init__(self, hit: SongHit, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        kinds: list[str] = []
        for t in hit.tracks:
            k = _kind_of(t)
            if k not in kinds:
                kinds.append(k)
        main = kinds[0] if kinds else "other"
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 12, 6)
        lay.setSpacing(10)
        badge = QLabel(self)
        badge.setFixedSize(34, 34)
        badge.setAlignment(Qt.AlignCenter)
        color = INSTRUMENT_COLORS.get(main, INSTRUMENT_COLORS["other"])
        badge.setStyleSheet(f"background:{rgba(color, 0.16)};border-radius:9px")
        badge.setPixmap(tab_icons.pixmap(tab_icons.instrument_icon_name(main), color, 18))
        lay.addWidget(badge)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(_Elided(BodyLabel, hit.title, self))
        col.addWidget(_Elided(CaptionLabel, hit.artist, self))
        lay.addLayout(col, 1)
        for k in kinds[:5]:                    # puces : un instrument = une icône colorée (survol → nom via l'info-bulle de la ligne)
            ic = QLabel(self)
            ic.setFixedSize(18, 18)
            ic.setPixmap(tab_icons.pixmap(tab_icons.instrument_icon_name(k), INSTRUMENT_COLORS.get(k, INSTRUMENT_COLORS["other"]), 14))
            ic.setAlignment(Qt.AlignCenter)
            lay.addWidget(ic)


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
        p = pal()                                   # niveau « relief » : la liste flotte au-dessus de la page
        self.setStyleSheet(f"QListWidget{{background:{p['raised']};border:1px solid {p['border']};border-radius:12px;"
                           f"outline:0;padding:4px}}"
                           f"QListWidget::item{{border-radius:8px;margin:1px 0}}"
                           f"QListWidget::item:selected{{background:{rgba('accent', 0.16)}}}"
                           + scrollbar_qss(8))

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
            item.setForeground(qc("muted"))
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