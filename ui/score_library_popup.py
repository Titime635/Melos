"""
Fenêtre flottante « Morceaux » de la page Partition : morceaux récents et favoris, avec recherche.
Clic sur une ligne (ou Entrée) = charger ; ★ = favori ; ✕ = retirer de l'historique.
"""

import time

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QListWidget, QListWidgetItem, QVBoxLayout, QWidget)

from tabs.score_library import ScoreEntry, ScoreLibrary
from ui.tab_widgets import PopupCard, SearchField, SegmentedPill, TabButton
from ui.theme import pal, rgba, scrollbar_qss
from ui.track_list import _Elided

WIDTH = 460
ROW_H = 52
MAX_ROWS = 8                       # au-delà, la liste défile (c'est une liste de morceaux : exception légitime)


def ago(ts: float, now: float | None = None) -> str:
    """« aujourd'hui », « hier », « il y a 3 j », « il y a 2 sem. », « il y a 5 mois »…"""
    days = int(((now if now is not None else time.time()) - ts) // 86400)
    if ts <= 0:
        return ""
    if days <= 0:
        return "aujourd'hui"
    if days == 1:
        return "hier"
    if days < 14:
        return f"il y a {days} j"
    if days < 60:
        return f"il y a {days // 7} sem."
    return f"il y a {days // 30} mois"


class StarButton(TabButton):
    """Étoile de favori : pleine et ambrée quand le morceau est favori, creuse et discrète sinon."""

    def __init__(self, on: bool = False, parent=None, size: int = 36):
        super().__init__("", "star", "ghost", parent, color="amber", height=size)
        self.setFixedSize(size, size)
        self.setCheckable(True)
        self.on = False
        self.set_on(on)

    def nextCheckState(self):                       # l'état vient de la bibliothèque, pas du clic
        pass

    def set_on(self, on: bool):
        self.on = bool(on)
        self.setChecked(self.on)
        self.setIconName("star-fill" if self.on else "star")
        self.setToolTip("Retirer des favoris" if self.on else "Ajouter aux favoris")


class _EntryRow(QWidget):
    star_clicked = Signal(int)
    remove_clicked = Signal(int)

    def __init__(self, entry: ScoreEntry, allow_remove: bool, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 4, 6, 4)
        lay.setSpacing(2)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(_Elided(type("BodyLabel", (), {}), entry.label, self))
        n = len(entry.bookmarks)
        sub = " · ".join(x for x in (entry.artist, ago(entry.opened), f"{n} marque-page{'s' if n > 1 else ''}" if n else "") if x)
        col.addWidget(_Elided(type("CaptionLabel", (), {}), sub, self))
        lay.addLayout(col, 1)
        self.star = StarButton(entry.favorite, self, size=30)
        self.star.clicked.connect(lambda: self.star_clicked.emit(entry.song_id))
        lay.addWidget(self.star)
        if allow_remove and not entry.keep:
            rm = TabButton("", "close", "ghost", self, height=30)
            rm.setFixedSize(30, 30)
            rm.setToolTip("Retirer de l'historique")
            rm.clicked.connect(lambda: self.remove_clicked.emit(entry.song_id))
            lay.addWidget(rm)


class ScorePicker(PopupCard):
    chosen = Signal(object)            # ScoreEntry

    def __init__(self, library: ScoreLibrary, parent=None):
        super().__init__(parent)
        self.library = library
        self._tab = "recent"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 8)
        lay.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.tabs = SegmentedPill(self, height=32)
        self.tabs.addItem("recent", "Récents", lambda: self._set_tab("recent"))
        self.tabs.addItem("fav", "Favoris", lambda: self._set_tab("fav"))
        top.addWidget(self.tabs)
        self.box = QFrame(self)                          # champ de filtre : creusé (niveau « surface »)
        self.box.setObjectName("filterBox")
        self.box.setFixedHeight(32)                      # même hauteur que les onglets, quel que soit le contenu de la liste
        bl = QHBoxLayout(self.box)
        bl.setContentsMargins(10, 0, 4, 0)
        self.search = SearchField(self.box)
        self.search.setPlaceholderText("Filtrer…")
        self.search.setFixedHeight(30)
        self.search.textChanged.connect(lambda _: self.refresh())
        self.search.installEventFilter(self)
        bl.addWidget(self.search)
        top.addWidget(self.box, 1)
        lay.addLayout(top)
        self.list = QListWidget(self)
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.setMouseTracking(True)
        self.list.itemEntered.connect(lambda it: self.list.setCurrentItem(it) if it.flags() & Qt.ItemIsSelectable else None)
        self.list.itemClicked.connect(self._clicked)
        lay.addWidget(self.list)
        foot = QHBoxLayout()
        self.count = _Elided(type("CaptionLabel", (), {}), "", self)
        foot.addWidget(self.count, 1)
        self.clear_btn = TabButton("Vider l'historique", None, "soft", self, height=30)
        self.clear_btn.setToolTip("Retire les morceaux récents ; les favoris et les morceaux avec marque-pages sont conservés")
        self.clear_btn.clicked.connect(self._clear)
        foot.addWidget(self.clear_btn)
        lay.addLayout(foot)
        self.setFixedWidth(WIDTH)
        self._apply_theme()
        library.listeners.append(self._library_changed)

    # ---------- contenu ----------
    def _entries(self) -> list[ScoreEntry]:
        base = self.library.recent() if self._tab == "recent" else self.library.favorites()
        return self.library.search(self.search.text(), base)

    def refresh(self):
        keep = self.list.verticalScrollBar().value()
        entries = self._entries()
        self.list.clear()
        if not entries:
            filtered = bool(self.search.text().strip())
            msg = ("Aucun résultat" if filtered else
                   "Aucune partition ouverte pour l'instant" if self._tab == "recent" else
                   "Aucun favori : clique sur l'étoile à côté d'un morceau")
            item = QListWidgetItem(msg)
            item.setFlags(Qt.NoItemFlags)
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor(pal()["muted"]))
            item.setSizeHint(QSize(10, 70))
            self.list.addItem(item)
        for e in entries:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, e)
            item.setSizeHint(QSize(10, ROW_H))
            self.list.addItem(item)
            row = _EntryRow(e, allow_remove=self._tab == "recent", parent=self.list)
            row.star_clicked.connect(self._toggle_star)
            row.remove_clicked.connect(self.library.remove)
            self.list.setItemWidget(item, row)
        if entries:
            self.list.setCurrentRow(0)
        rows = max(1, min(MAX_ROWS, len(entries))) if entries else 1
        self.list.setFixedHeight(rows * ROW_H + 4 if entries else 74)
        self.list.verticalScrollBar().setValue(keep)
        n_all = len(self.library.recent() if self._tab == "recent" else self.library.favorites())
        self.count.setText(f"{n_all} morceau{'x' if n_all > 1 else ''}")
        self.clear_btn.setVisible(self._tab == "recent")
        self.clear_btn.setEnabled(any(not e.keep for e in self.library.recent()))
        self.layout().activate()
        self.resize(WIDTH, self.layout().sizeHint().height())       # taille exacte du contenu : pas d'espace en trop réparti entre les lignes

    def _set_tab(self, tab: str):
        self._tab = tab
        self.refresh()

    def _library_changed(self):
        if self.isVisible():
            self.refresh()

    def _toggle_star(self, song_id: int):
        self.library.toggle_favorite(song_id)

    def _clear(self):
        self.library.clear_history()

    def _clicked(self, item):
        e = item.data(Qt.UserRole)
        if e is not None:
            self.close()
            self.chosen.emit(e)

    # ---------- clavier ----------
    def eventFilter(self, obj, ev):
        if obj is self.search and ev.type() == ev.Type.KeyPress:
            k = ev.key()
            if k in (Qt.Key_Down, Qt.Key_Up) and self.list.count():
                row = self.list.currentRow() + (1 if k == Qt.Key_Down else -1)
                self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
                self.list.scrollToItem(self.list.currentItem())
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                it = self.list.currentItem()
                if it is not None:
                    self._clicked(it)
                return True
        return super().eventFilter(obj, ev)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    # ---------- apparence ----------
    def _apply_theme(self):
        c = pal()
        self.list.setStyleSheet(f"QListWidget{{background:transparent;border:none;outline:0}}"
                                f"QListWidget::item{{border-radius:8px}}"
                                f"QListWidget::item:selected{{background:{rgba(c['accent'], 0.16)}}}" + scrollbar_qss())
        self.box.setStyleSheet(f"#filterBox{{background:{c['surface']};border:1px solid {c['border']};border-radius:8px}}")
        self.search.apply_theme()

    def popup_at(self, widget, tab: str | None = None):
        """Sous le bouton, aligné à gauche (et ramené dans l'écran). `tab` : « recent » ou « fav »."""
        if tab is None:
            tab = "fav" if not self.library.recent() and self.library.favorites() else self._tab
        self._tab = tab
        self.tabs.setCurrentItem(tab)
        self.search.clear()
        self._apply_theme()
        self.refresh()
        self.place_near(widget)
        self.show()
        self.search.setFocus()