"""
Fenêtre flottante « Marque-pages » de la page Partition : liste des marque-pages du morceau, ajout à la mesure courante,
renommage, suppression ; un clic sur une ligne (ou Entrée) saute à la mesure.
"""

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QFrame, QHBoxLayout, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from tabs.score_library import NAME_MAX, ScoreLibrary
from ui.tab_widgets import DragSource, PopupCard, SearchField, TabButton
from ui.theme import pal, rgba, scrollbar_qss
from ui.track_list import _Elided

WIDTH = 400
ROW_H = 46
MAX_ROWS = 7                       # au-delà, la liste défile (liste de données : exception légitime)


class _Row(QWidget):
    renamed = Signal(int, str)
    removed = Signal(int)

    def __init__(self, bar: int, name: str, parent=None):
        super().__init__(parent)
        self.bar = bar
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 4, 6, 4)
        lay.setSpacing(4)
        badge = _Elided(type("CaptionLabel", (), {}), f"Mes. {bar + 1}", self, fit=True)       # pastille ambrée (comme le drapeau de la partition)
        badge.setFixedWidth(58)
        badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        lay.addWidget(badge)
        self.name = _Elided(type("BodyLabel", (), {}), name, self)
        self.name.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        lay.addWidget(self.name, 1)
        self.box = QFrame(self)                          # champ de renommage (visible seulement en édition)
        self.box.setObjectName("renameBox")
        self.box.setStyleSheet(f"#renameBox{{background:{pal()['surface']};border:1px solid {rgba('accent', 0.7)};border-radius:8px}}")
        bl = QHBoxLayout(self.box)
        bl.setContentsMargins(8, 0, 4, 0)
        self.edit = SearchField(self.box)
        self.edit.setMaxLength(NAME_MAX)
        self.edit.setText(name)
        self.edit.setFixedHeight(28)
        self.edit.returnPressed.connect(self._commit)
        bl.addWidget(self.edit)
        self.box.hide()
        lay.addWidget(self.box, 1)
        self.edit_btn = TabButton("", "edit", "ghost", self, height=30)
        self.edit_btn.setFixedSize(30, 30)
        self.edit_btn.setToolTip("Renommer")
        self.edit_btn.clicked.connect(self._start_edit)
        lay.addWidget(self.edit_btn)
        rm = TabButton("", "close", "ghost", self, height=30)
        rm.setFixedSize(30, 30)
        rm.setToolTip("Supprimer ce marque-page")
        rm.clicked.connect(lambda: self.removed.emit(bar))
        lay.addWidget(rm)

    def _start_edit(self):
        self.name.hide()
        self.box.show()
        self.edit.setFocus()
        self.edit.selectAll()

    def _commit(self):
        text = self.edit.text().strip()
        if text:
            self.renamed.emit(self.bar, text)


class BookmarkPopup(PopupCard):
    jump = Signal(int)                 # index de mesure (0 = première)
    drag_started = Signal(str, str)    # libellé, couleur : un NOUVEAU marque-page glissé depuis « Ajouter » vers la partition
    drag_moved = Signal(QPoint)
    drag_dropped = Signal(QPoint)

    def __init__(self, library: ScoreLibrary, name_hint=None, parent=None):
        super().__init__(parent)
        self.library = library
        self.name_hint = name_hint or (lambda bar: "")     # nom proposé pour une mesure (ex. titre de section)
        self.song_id = -1
        self.current_bar = -1
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(_Elided(type("StrongBodyLabel", (), {}), "Marque-pages", self), 1)
        self.add_btn = TabButton("Ajouter", "bookmark", "accent", self, height=32)
        self.add_btn.clicked.connect(self._add_or_remove)
        top.addWidget(self.add_btn)
        self._drag = DragSource(self.add_btn)               # glisser « Ajouter » sur la partition : pose le marque-page là
        self._drag.started.connect(self._drag_start)
        self._drag.moved.connect(self.drag_moved)
        self._drag.dropped.connect(self._drag_drop)
        lay.addLayout(top)
        self.hint = _Elided(type("CaptionLabel", (), {}), "Glisse « Ajouter » sur la partition · Ctrl+B : poser / retirer · Ctrl+←/→ : suivant", self)
        lay.addWidget(self.hint)
        self.list = QListWidget(self)
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.setMouseTracking(True)
        self.list.itemEntered.connect(lambda it: self.list.setCurrentItem(it) if it.flags() & Qt.ItemIsSelectable else None)
        self.list.itemClicked.connect(self._clicked)
        lay.addWidget(self.list)
        self.setFixedWidth(WIDTH)
        library.listeners.append(self._changed)

    # ---------- contenu ----------
    def refresh(self):
        marks = self.library.bookmarks(self.song_id)
        self.list.clear()
        if not marks:
            item = QListWidgetItem("Aucun marque-page.\nClique sur la partition pour placer le curseur, puis « Ajouter ».")
            item.setFlags(Qt.NoItemFlags)
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor(pal()["muted"]))
            item.setSizeHint(QSize(10, 64))
            self.list.addItem(item)
        for b in marks:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, b["bar"])
            item.setSizeHint(QSize(10, ROW_H))
            self.list.addItem(item)
            row = _Row(b["bar"], b["name"], self.list)
            row.renamed.connect(lambda bar, text: self.library.rename_bookmark(self.song_id, bar, text))
            row.removed.connect(lambda bar: self.library.remove_bookmark(self.song_id, bar))
            self.list.setItemWidget(item, row)
        if marks:
            self.list.setCurrentRow(0)
        self.list.setFixedHeight((min(MAX_ROWS, len(marks)) * ROW_H + 4) if marks else 68)
        has_bar = self.current_bar >= 0
        exists = has_bar and self.library.bookmark_at(self.song_id, self.current_bar) is not None
        self.add_btn.setEnabled(has_bar)
        self.add_btn.setKind("soft" if exists else "accent")
        self.add_btn.setText(f"Retirer (mesure {self.current_bar + 1})" if exists else
                             f"Ajouter à la mesure {self.current_bar + 1}" if has_bar else "Ajouter")
        self.adjustSize()

    def _changed(self):
        if self.isVisible():
            self.refresh()

    def _drag_start(self, pos):
        if self.library.bookmark_at(self.song_id, self.current_bar):       # « Retirer » : rien à glisser
            self._drag.cancel()
            return
        self.setWindowOpacity(0.35)                                          # la partition derrière doit rester visible
        self.drag_started.emit("Marque-page", pal()["amber"])
        self.drag_moved.emit(pos)

    def _drag_drop(self, pos):
        self.setWindowOpacity(1.0)
        self.close()
        self.drag_dropped.emit(pos)

    def hideEvent(self, e):
        self.setWindowOpacity(1.0)
        super().hideEvent(e)

    def _add_or_remove(self):
        if self.current_bar < 0:
            return
        if self.library.bookmark_at(self.song_id, self.current_bar):
            self.library.remove_bookmark(self.song_id, self.current_bar)
        else:
            self.library.add_bookmark(self.song_id, self.current_bar, self.name_hint(self.current_bar))

    def _clicked(self, item):
        bar = item.data(Qt.UserRole)
        if bar is not None:
            self.close()
            self.jump.emit(int(bar))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
        elif e.key() in (Qt.Key_Down, Qt.Key_Up) and self.list.count():
            row = self.list.currentRow() + (1 if e.key() == Qt.Key_Down else -1)
            self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter) and self.list.currentItem() is not None:
            self._clicked(self.list.currentItem())
        else:
            super().keyPressEvent(e)

    def popup_at(self, widget, song_id: int, current_bar: int):
        """Au-dessus du bouton (il est dans la barre du bas), aligné à gauche, ramené dans l'écran."""
        self.song_id, self.current_bar = song_id, current_bar
        c = pal()
        self.list.setStyleSheet(f"QListWidget{{background:transparent;border:none;outline:0}}QListWidget::item{{border-radius:8px}}"
                                f"QListWidget::item:selected{{background:{rgba(c['accent'], 0.16)}}}" + scrollbar_qss())
        self.refresh()
        self.place_near(widget, above=True)
        self.show()
        self.setFocus()