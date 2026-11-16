"""
Fenêtre flottante « Presets » de la page Partition : changements de preset placés sur la partition.

Deux pages :
  - « Sur ce morceau » : la liste des changements (mesure, preset, état) ; un clic saute à la mesure ;
  - « Ajouter » : les presets de la BIBLIOTHÈQUE DE PRESETS, avec un champ de filtre. On clique un preset (il se place à la
    mesure visée) ou on le GLISSE sur la partition. Un preset déjà chargé dans l'ampli porte le numéro de son emplacement ;
    un preset qui n'y est pas est marqué « non chargé » (le changement se pose quand même, mais n'enverra rien tant que le
    preset n'est pas dans l'ampli : il faut l'envoyer depuis l'éditeur).

À la lecture, quand la partition atteint la mesure, Melos envoie à l'ampli l'emplacement qui contient le preset (« Envoi auto »).
Sans bibliothèque (éditeur indisponible) la liste propose les 7 emplacements bruts.
"""

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QStackedWidget,
                               QVBoxLayout, QWidget)

from tabs.score_library import SLOTS, ScoreLibrary
from ui import tab_icons
from ui.tab_widgets import DragSource, PopupCard, SearchField, SegmentedPill, TabButton
from ui.theme import SLOT_COLORS, pal, rgba, scrollbar_qss
from ui.track_list import _Elided

WIDTH = 440
ROW_H = 48
MAX_ROWS = 7                       # au-delà, la liste défile (liste de données : exception légitime)

# explications des états d'un changement de preset
NOTES = {                          # courtes (sous le nom) ; le détail est dans l'info-bulle (TIPS)
    "ahead": "à renvoyer vers l'ampli",
    "changed": "emplacement modifié hors de Melos",
    "missing": "non chargé dans l'ampli",
    "deleted": "supprimé de la bibliothèque",
}
TIPS = {
    "ahead": "Le preset a été modifié dans la bibliothèque depuis son envoi : l'ampli a encore l'ancienne version. Renvoie-le depuis l'éditeur.",
    "changed": "Le contenu de l'emplacement a changé en dehors de Melos : ce n'est plus le preset de la bibliothèque.",
    "missing": "Ce preset n'est chargé dans aucun emplacement de l'ampli : rien ne sera envoyé. Envoie-le d'abord depuis l'éditeur.",
    "deleted": "Ce preset n'existe plus dans la bibliothèque de presets.",
}
WARN = ("ahead", "changed", "missing", "deleted")


def resolve(names, target: dict) -> dict:
    """Où est le preset visé par un changement ? -> {"slot": emplacement (0-6) à envoyer ou None, "name", "status", "note"}.

    status : ok (chargé et à jour) · ahead (chargé mais à renvoyer) · changed (emplacement brut modifié hors de Melos) ·
             missing (pas chargé dans l'ampli) · deleted (supprimé de la bibliothèque) · raw (emplacement brut sans bibliothèque)."""
    eid = target.get("entry")
    if eid:
        e = names.library_entry(eid) if names is not None else None
        if e is None:
            return {"slot": None, "name": target.get("name") or "Preset supprimé", "status": "deleted", "note": NOTES["deleted"]}
        slots = names.slots_of(eid)
        for want, status in (("synced", "ok"), ("ahead", "ahead")):
            slot = next((s for s, st in slots if st == want), None)
            if slot is not None:
                return {"slot": slot, "name": e.name, "status": status, "note": NOTES.get(status, "")}
        return {"slot": None, "name": e.name, "status": "missing", "note": NOTES["missing"]}
    slot = int(target.get("slot", 0))
    state = names.state(slot)[0] if names is not None else "unknown"
    name = names.title(slot) if names is not None else f"Preset {slot + 1}"
    status = state if state in ("ahead", "changed") else "raw"
    return {"slot": slot, "name": name, "status": status, "note": NOTES.get(status, "")}


def slot_color(slot) -> str:
    return SLOT_COLORS[slot % len(SLOT_COLORS)] if slot is not None else pal()["amber"]


def _badge(slot, status: str, parent) -> QLabel:
    """Pastille ronde : numéro de l'emplacement à sa couleur, ou « ! » ambré si le preset n'est pas dans l'ampli."""
    color = slot_color(slot)
    b = QLabel(str(slot + 1) if slot is not None else "!", parent)
    b.setFixedSize(26, 26)
    b.setAlignment(Qt.AlignCenter)
    dash = "dashed" if status in WARN else "solid"
    b.setStyleSheet(f"background:{rgba(color, 0.2)};border:1px {dash} {rgba(color, 0.75)};border-radius:13px;"
                    f"color:{pal()['text']};font-weight:700;font-size:12px")
    b.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    return b


def where(bar: int, beat: int = 0) -> str:
    """« Mes. 5 » ou « Mes. 5 · t3 » quand le changement est au milieu de la mesure (temps 3)."""
    return f"Mes. {bar + 1}" + (f" · t{beat + 1}" if beat else "")


class _MarkRow(QWidget):
    removed = Signal(int, int)             # mesure, temps

    def __init__(self, bar: int, res: dict, hint: str, parent=None, beat: int = 0):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 4, 6, 4)
        lay.setSpacing(8)
        num = _Elided(type("CaptionLabel", (), {}), where(bar, beat), self, fit=True)
        num.setFixedWidth(74)
        num.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        lay.addWidget(num)
        lay.addWidget(_badge(res["slot"], res["status"], self))
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        t = _Elided(type("BodyLabel", (), {}), res["name"], self)
        t.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        col.addWidget(t)
        sub = res["note"] or hint
        if sub:
            h = _Elided(type("CaptionLabel", (), {}), sub, self)
            h.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            h.setToolTip(TIPS.get(res["status"], sub))
            col.addWidget(h)
        lay.addLayout(col, 1)
        if res["status"] in WARN:
            w = QLabel(self)
            w.setPixmap(tab_icons.pixmap("refresh" if res["status"] in ("ahead", "changed") else "close", pal()["amber"], 16))
            w.setToolTip(TIPS.get(res["status"], res["note"]))
            w.setFixedSize(22, 22)
            w.setAlignment(Qt.AlignCenter)
            lay.addWidget(w)
        rm = TabButton("", "close", "ghost", self, height=30)
        rm.setFixedSize(30, 30)
        rm.setToolTip("Retirer ce changement de preset")
        rm.clicked.connect(lambda: self.removed.emit(bar, beat))
        lay.addWidget(rm)


class _EntryRow(QWidget):
    """Une ligne de la bibliothèque : cliquer = placer à la mesure visée ; glisser = déposer sur la partition."""
    picked = Signal(object)
    drag_started = Signal(object, str, str)          # cible, libellé, couleur
    drag_moved = Signal(QPoint)
    drag_dropped = Signal(QPoint)

    def __init__(self, target: dict, res: dict, caption: str, parent=None):
        super().__init__(parent)
        self.target = target
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("Clique pour placer à la mesure visée, ou glisse-le sur la partition")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 4, 12, 4)
        lay.setSpacing(10)
        lay.addWidget(_badge(res["slot"], res["status"], self))
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        for w in (_Elided(type("BodyLabel", (), {}), res["name"], self), _Elided(type("CaptionLabel", (), {}), caption, self)):
            w.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            col.addWidget(w)
        lay.addLayout(col, 1)
        self.res = res
        self.drag = DragSource(self)
        self.drag.clicked.connect(lambda: self.picked.emit(self.target))
        self.drag.started.connect(lambda pos: self.drag_started.emit(self.target, self._label(), slot_color(self.res["slot"])))
        self.drag.started.connect(self.drag_moved)
        self.drag.moved.connect(self.drag_moved)
        self.drag.dropped.connect(self.drag_dropped)

    def _label(self) -> str:
        r = self.res
        return (f"{r['slot'] + 1} · " if r["slot"] is not None else "") + r["name"]


class PresetMarksPopup(PopupCard):
    jump = Signal(int)                 # index de mesure (0 = première)
    auto_changed = Signal(bool)
    add_requested = Signal(object, int, int)       # cible ({"entry":…} ou {"slot":…}), mesure, temps (0 = début de mesure)
    drag_started = Signal(object, str, str)        # cible, libellé, couleur
    drag_moved = Signal(QPoint)
    drag_dropped = Signal(QPoint)

    def __init__(self, library: ScoreLibrary, names=None, name_hint=None, auto: bool = True, parent=None):
        super().__init__(parent)
        self.library, self.names = library, names
        self.name_hint = name_hint or (lambda bar: "")             # titre de section de la mesure, pour s'y repérer
        self.song_id, self.target_bar, self.target_beat = -1, -1, 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 10)
        lay.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.tabs = SegmentedPill(self, height=32)
        self.tabs.addItem("marks", "Sur ce morceau", lambda: self._page("marks"))
        self.tabs.addItem("add", "Ajouter", lambda: self._page("add"))
        top.addWidget(self.tabs)
        top.addStretch(1)
        self.auto_btn = TabButton("Envoi auto", "pedal", "soft", self, height=32)
        self.auto_btn.setCheckable(True)
        self.auto_btn.setChecked(auto)
        self.auto_btn.setToolTip("Envoie automatiquement le preset à l'ampli quand la lecture atteint la mesure\n"
                                 "(et celui qui est en vigueur au moment où l'on relance la lecture)")
        self.auto_btn.toggled.connect(self.auto_changed)
        top.addWidget(self.auto_btn)
        lay.addLayout(top)
        self.stack = QStackedWidget(self)
        lay.addWidget(self.stack)
        # --- page 1 : les changements du morceau
        p1 = QWidget(self.stack)
        l1 = QVBoxLayout(p1)
        l1.setContentsMargins(0, 0, 0, 0)
        l1.setSpacing(6)
        self.warn = _Elided(type("CaptionLabel", (), {}), "", p1)
        l1.addWidget(self.warn)
        self.list = self._make_list(p1)
        self.list.itemClicked.connect(self._clicked)
        l1.addWidget(self.list)
        self.stack.addWidget(p1)
        # --- page 2 : la bibliothèque de presets
        p2 = QWidget(self.stack)
        l2 = QVBoxLayout(p2)
        l2.setContentsMargins(0, 0, 0, 0)
        l2.setSpacing(6)
        self.caption = _Elided(type("CaptionLabel", (), {}), "", p2)
        l2.addWidget(self.caption)
        self.box = QFrame(p2)
        self.box.setFixedHeight(34)
        bl = QHBoxLayout(self.box)
        bl.setContentsMargins(10, 0, 4, 0)
        self.search = SearchField(self.box)
        self.search.setPlaceholderText("Filtrer les presets…")
        self.search.setFixedHeight(30)
        self.search.textChanged.connect(lambda _: self._fill_library())
        bl.addWidget(self.search)
        l2.addWidget(self.box)
        self.lib = self._make_list(p2)
        l2.addWidget(self.lib)
        self.stack.addWidget(p2)
        self.setFixedWidth(WIDTH)
        library.listeners.append(self._changed)
        if names is not None:
            names.changed.connect(self._changed)

    def _make_list(self, parent) -> QListWidget:
        lst = QListWidget(parent)
        lst.setFrameShape(QFrame.NoFrame)
        lst.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lst.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        lst.setFocusPolicy(Qt.NoFocus)
        lst.setMouseTracking(True)
        lst.itemEntered.connect(lambda it, lst=lst: lst.setCurrentItem(it) if it.flags() & Qt.ItemIsSelectable else None)
        return lst

    # ---------- contenu ----------
    def _page(self, key: str):
        self.tabs.setCurrentItem(key)
        self.stack.setCurrentIndex(0 if key == "marks" else 1)
        self.refresh()

    def refresh(self):
        self._fill_marks()
        self._fill_library()
        self.stack.setFixedHeight(self.stack.currentWidget().layout().sizeHint().height())
        self.layout().activate()
        self.resize(WIDTH, self.layout().sizeHint().height())

    def _fill_marks(self):
        marks = self.library.preset_marks(self.song_id)
        self.list.clear()
        warned = []
        if not marks:
            item = QListWidgetItem("Aucun changement de preset sur ce morceau.\nClic droit sur la partition, ou onglet « Ajouter ».")
            item.setFlags(Qt.NoItemFlags)
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor(pal()["muted"]))
            item.setSizeHint(QSize(10, 70))
            self.list.addItem(item)
        for m in marks:
            res = resolve(self.names, m)
            if res["status"] in WARN:
                warned.append(res["name"])
            item = QListWidgetItem()
            item.setData(Qt.UserRole, m["bar"])
            item.setSizeHint(QSize(10, ROW_H))
            self.list.addItem(item)
            row = _MarkRow(m["bar"], res, self.name_hint(m["bar"]), self.list, m.get("beat", 0))
            row.removed.connect(lambda bar, beat: self.library.remove_preset_mark(self.song_id, bar, beat))
            self.list.setItemWidget(item, row)
        if marks:
            self.list.setCurrentRow(0)
        self.list.setFixedHeight((min(MAX_ROWS - 1, len(marks)) * ROW_H + 4) if marks else 76)
        self.warn.setText(("⚠ À vérifier : " + ", ".join(dict.fromkeys(warned))) if warned else "")
        self.warn.setVisible(bool(warned))

    def _candidates(self) -> list[tuple[dict, dict, str]]:
        """[(cible, résolution, légende)] : presets de la bibliothèque, ou les 7 emplacements sans bibliothèque."""
        out = []
        if self.names is not None and self.names.has_library:
            q = self.search.text().strip().lower()
            for e in self.names.library_entries():
                tags = ", ".join(e.tags)
                if q and q not in e.name.lower() and q not in tags.lower():
                    continue
                target = {"entry": e.id, "name": e.name}
                res = resolve(self.names, target)
                where = (f"chargé dans l'emplacement {res['slot'] + 1}" if res["slot"] is not None else "non chargé dans l'ampli")
                if res["status"] == "ahead":
                    where += " (à renvoyer)"
                out.append((target, res, " · ".join(x for x in (where, tags) if x)))
        else:
            for i in range(SLOTS):
                target = {"slot": i}
                res = resolve(self.names, target)
                out.append((target, res, "emplacement de l'ampli"))
        return out

    def _fill_library(self):
        self.lib.clear()
        cands = self._candidates()
        if not cands:
            item = QListWidgetItem("Aucun preset ne correspond." if self.search.text().strip() else
                                   "La bibliothèque de presets est vide.\nCrée ou importe un preset dans l'éditeur.")
            item.setFlags(Qt.NoItemFlags)
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor(pal()["muted"]))
            item.setSizeHint(QSize(10, 70))
            self.lib.addItem(item)
        for target, res, caption in cands:
            item = QListWidgetItem()
            item.setFlags(Qt.ItemIsEnabled)
            item.setSizeHint(QSize(10, ROW_H))
            self.lib.addItem(item)
            row = _EntryRow(target, res, caption, self.lib)
            row.picked.connect(self._picked)
            row.drag_started.connect(self._drag_started)
            row.drag_moved.connect(self.drag_moved)
            row.drag_dropped.connect(self._drag_dropped)
            self.lib.setItemWidget(item, row)
        self.lib.setFixedHeight((min(MAX_ROWS, len(cands)) * ROW_H + 4) if cands else 76)
        bar = self.target_bar
        self.caption.setText(f"Mesure {bar + 1}{f', temps {self.target_beat + 1}' if self.target_beat else ''} : clique un preset pour le placer, ou glisse-le sur la partition"
                             if bar >= 0 else "Glisse un preset sur la partition (ou clique sur une mesure d'abord)")

    # ---------- actions ----------
    def _changed(self):
        if self.isVisible():
            self.refresh()

    def _picked(self, target):
        if self.target_bar < 0:
            return
        self.add_requested.emit(target, self.target_bar, self.target_beat)
        self._page("marks")

    def _drag_started(self, target, label, color):
        self.setWindowOpacity(0.35)               # la partition derrière doit rester visible pendant le glissement
        self.drag_started.emit(target, label, color)

    def _drag_dropped(self, pos):
        self.setWindowOpacity(1.0)
        self.close()
        self.drag_dropped.emit(pos)

    def _clicked(self, item):
        bar = item.data(Qt.UserRole)
        if bar is not None:
            self.close()
            self.jump.emit(int(bar))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
        elif e.key() in (Qt.Key_Down, Qt.Key_Up) and self.list.count() and self.stack.currentIndex() == 0:
            row = self.list.currentRow() + (1 if e.key() == Qt.Key_Down else -1)
            self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter) and self.stack.currentIndex() == 0 and self.list.currentItem() is not None:
            self._clicked(self.list.currentItem())
        else:
            super().keyPressEvent(e)

    def hideEvent(self, e):
        self.setWindowOpacity(1.0)
        super().hideEvent(e)

    def _style(self):
        c = pal()
        qss = (f"QListWidget{{background:transparent;border:none;outline:0}}QListWidget::item{{border-radius:8px}}"
               f"QListWidget::item:selected{{background:{rgba(c['accent'], 0.16)}}}" + scrollbar_qss())
        self.list.setStyleSheet(qss)
        self.lib.setStyleSheet(qss)
        self.box.setObjectName("filterBox")
        self.box.setStyleSheet(f"#filterBox{{background:{c['surface']};border-radius:9px}}")
        self.search.apply_theme()

    def popup_at(self, anchor, song_id: int, bar: int, page: str | None = None, beat: int = 0):
        """Ouvre la fenêtre. `anchor` : un widget (la fenêtre s'ouvre au-dessus) ou un point global (clic droit). `bar` : la
        mesure visée par « Ajouter » ; `page` : « marks » / « add » (par défaut : « Ajouter » tant qu'il n'y a aucun changement)."""
        self.song_id, self.target_bar, self.target_beat = song_id, bar, beat
        self._style()
        page = page or ("marks" if self.library.preset_marks(song_id) else "add")
        self.tabs.setCurrentItem(page)
        self.stack.setCurrentIndex(0 if page == "marks" else 1)
        self.search.clear()
        self.refresh()
        if isinstance(anchor, QPoint):
            self.place_at(anchor)
        else:
            self.place_near(anchor, above=True)
        self.show()
        self.setFocus()