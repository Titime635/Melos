"""
Panneau de contrôle des presets.

Affiche les 7 presets du Mighty Plug Pro ; le preset actif est rempli de SA couleur, et se met à jour
tout seul que le changement vienne d'un clic ici ou d'un appui physique sur le device (grâce à
AmpState.preset_changed).

NUMÉROTATION : en interne (AmpState, MidiSender, noms sauvegardés, setlist) les presets sont indexés
0 à 6, comme le protocole MIDI. À l'écran ils s'appellent 1 à 7 (comme les raccourcis et la setlist).
Toute conversion passe par `display_number(index)` : ne jamais afficher un index brut.

Module adaptatif (`adaptive`, cf ui/dashboard/dock_widget.py) : selon la place, il choisit
  - une grille de boutons avec les NOMS (4+3, puis 3 colonnes, 2...) : le texte passe à la ligne aux
    espaces, avec UNE SEULE taille de police pour tous les presets (la plus grande où tous les noms
    tiennent). Si même la taille minimale (MIN_FONT_PX) ne suffit pas, on passe aux chiffres ;
  - sinon une rangée de pastilles 1 à 7 ;
  - sinon (très étroit) « ◀ nom du preset actif ▶ ».
Renommer : crayon de l'en-tête ou double-clic sur un preset (renomme le preset actif).

NOMS : ils viennent de `SlotNames` (en bas de ce fichier d'en-têtes), partagé avec l'onglet Éditeur et la setlist : un
emplacement lié à la bibliothèque porte le nom du preset de la bibliothèque (renommer ici renomme là-bas), sinon
l'ancien nom perso de preset_names.json, sinon « Preset N ». Une pastille signale un emplacement « à renvoyer »
(bibliothèque modifiée) ou « modifié sur l'ampli » (changé hors de Melos).

IMPORTANT (bug corrigé) : le device n'envoie PAS d'écho de confirmation après une commande
program_change initiée par l'hôte (confirmé empiriquement, cf docs/protocol_notes.md — seuls les
changements physiques sont notifiés spontanément). Attendre cet écho pour rafraîchir l'UI bloquait
l'affichage indéfiniment pour tout clic logiciel. On met donc à jour l'état nous-mêmes juste après
avoir envoyé la commande ; les appuis physiques restent notifiés normalement via listener -> state.
"""

import json
import math
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, Qt, QRectF, QSize, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QApplication, QFrame, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, FluentIcon, LineEdit, PushButton, StrongBodyLabel, TransparentToolButton,
                            isDarkTheme)

from midi.protocol import CHANNELS_COUNT
from midi.sender import MidiSender
from state.amp_state import AmpState
from paths import PRESET_NAMES_FILE
from ui.module_card import MODULE_COLORS, ModuleCard
from ui.theme import PRESET_COLORS, STATE_COLORS, qc, style_popup
from ui.popup_utils import show_popup_under

# Fichier à côté de ce module, indépendant du dossier de lancement de l'appli
# (si tu as déjà des presets renommés, déplace l'ancien preset_names.json ici)
NAMES_FILE = PRESET_NAMES_FILE

# Couleur associée à chaque preset : palette douce commune (ui/theme.py), la même que sur la partition

GAP = 8
MAX_BUTTON_H = 72
MIN_FONT_PX = 15   # en dessous, les noms passent en chiffres plutôt que de devenir illisibles
MAX_FONT_PX = 20


def display_number(index: int) -> int:
    """Index interne (0-6, protocole) -> numéro affiché (1-7)."""
    return index + 1


def default_name(index: int) -> str:
    return f"Preset {display_number(index)}"


# États d'un emplacement par rapport à la bibliothèque (cf editor/workbench.py) qui méritent d'être signalés ici
FLAG_TIPS = {
    "ahead": ("À renvoyer", STATE_COLORS["warn"], "le preset de la bibliothèque a été modifié depuis son envoi vers l'ampli"),
    "changed": ("Modifié sur l'ampli", STATE_COLORS["error"],
                "le contenu de l'ampli a changé en dehors de Melos (différent de ce qui y a été envoyé)"),
}


class SlotNames(QObject):
    """Source UNIQUE des noms d'emplacements, partagée par le Dashboard, l'onglet Classique, la setlist et l'éditeur.

    Un emplacement lié à un preset de la bibliothèque porte le NOM de ce preset (c'est le même objet : le renommer
    ici ou dans l'éditeur change les deux). Sinon : l'ancien nom perso (preset_names.json), sinon « Preset N ».
    `changed` n'est émis que si un nom ou un état affiché a réellement changé (regroupé, thread Qt)."""

    changed = Signal()
    _poke = Signal()

    def __init__(self, service=None, library=None, parent=None):
        super().__init__(parent)
        self._service, self._library = service, library
        self._legacy: dict[int, str] = self._load_legacy()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._check)
        self._poke.connect(self._schedule)                  # file d'attente Qt : sûr depuis le thread de travail
        self._last = self.snapshot()
        if service is not None:
            service.slot_updated.connect(self._schedule)
            service.entry_updated.connect(self._schedule)
            service.loaded.connect(self._schedule)
        if library is not None:
            library.listeners.append(self._poke.emit)

    # --- lecture ---
    def state(self, index: int) -> tuple[str, str | None]:
        """(état, identifiant du preset de la bibliothèque) ; « unknown » sans éditeur."""
        if self._service is None:
            return "unknown", None
        try:
            return self._service.wb.slot_state(index)
        except Exception:
            return "unknown", None

    def entry(self, index: int):
        state, eid = self.state(index)
        return self._library.get(eid) if (eid and state != "unknown" and self._library is not None) else None

    # --- bibliothèque de presets (utilisée par les marqueurs de la page Partition) ---
    @property
    def has_library(self) -> bool:
        return self._library is not None

    def library_entries(self) -> list:
        """Presets de la bibliothèque, triés par nom."""
        if self._library is None:
            return []
        return sorted(self._library.entries(), key=lambda e: e.name.lower())

    def library_entry(self, entry_id: str):
        return self._library.get(entry_id) if self._library is not None and entry_id else None

    def slots_of(self, entry_id: str) -> list[tuple[int, str]]:
        """Emplacements de l'ampli où ce preset est chargé : [(emplacement, état)], état = synced / ahead / changed."""
        if self._service is None or not entry_id:
            return []
        try:
            return self._service.wb.entry_slots(entry_id)
        except Exception:
            return []

    def legacy(self, index: int) -> str:
        return self._legacy.get(index, "")

    def name(self, index: int) -> tuple[str, bool]:
        """(nom affiché, personnalisé ?)."""
        e = self.entry(index)
        if e is not None:
            return e.name, True
        custom = self._legacy.get(index)
        return (custom, True) if custom else (default_name(index), False)

    def title(self, index: int) -> str:
        return self.name(index)[0]

    def snapshot(self) -> tuple:
        return tuple((*self.name(i), self.state(i)[0]) for i in range(CHANNELS_COUNT))

    # --- écriture ---
    def rename(self, index: int, text: str) -> bool:
        text = text.strip()
        if not text:
            return False
        e = self.entry(index)
        if e is not None:
            self._library.update(e.id, name=text)           # déclenche `changed` via l'écouteur de bibliothèque
        else:
            self._legacy[index] = text
            self._save_legacy()
            self._schedule()
        return True

    def reload(self):
        """Relit le fichier des noms perso (import / réinitialisation depuis les Réglages)."""
        self._legacy = self._load_legacy()
        self._last = None
        self._check()

    # --- interne ---
    def _schedule(self, *_args):
        if not self._timer.isActive():
            self._timer.start()

    def _check(self):
        snap = self.snapshot()
        if snap != self._last:
            self._last = snap
            self.changed.emit()

    @staticmethod
    def _load_legacy() -> dict[int, str]:
        if NAMES_FILE.exists():
            try:
                raw = json.loads(NAMES_FILE.read_text(encoding="utf-8"))
                return {int(k): v for k, v in raw.items()}
            except (json.JSONDecodeError, ValueError, AttributeError):
                return {}
        return {}

    def _save_legacy(self):
        NAMES_FILE.write_text(json.dumps(self._legacy, ensure_ascii=False, indent=2), encoding="utf-8")


def _contrast(color: QColor) -> QColor:
    luma = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    return QColor("#1b1b1b") if luma > 150 else QColor("#ffffff")


class PresetButton(QAbstractButton):
    """Bouton de preset dessiné à la main : mis à jour en place (pas recréé à chaque changement).
    kind : "card" (numéro + nom), "flat" (nom), "number" (numéro seul)."""

    double_clicked = Signal()

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self._color = QColor(PRESET_COLORS.get(index, "#888888"))
        self._name, self._custom, self._active, self._kind = default_name(index), False, False, "card"
        self._font_px = MAX_FONT_PX
        self._flag = None   # "ahead" / "changed" : pastille d'alerte (cf FLAG_TIPS)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)   # cliquer un preset ne doit pas voler le focus du clavier
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_info(self, name: str, custom: bool, active: bool, kind: str, font_px: int | None = None, flag=None):
        font_px = font_px or self._font_px
        if (name, custom, active, kind, font_px, flag) != (self._name, self._custom, self._active, self._kind,
                                                           self._font_px, self._flag):
            self._name, self._custom, self._active, self._kind, self._font_px = name, custom, active, kind, font_px
            self._flag = flag
            tip = f"{display_number(self.index)} — {name}"
            if flag in FLAG_TIPS:
                tip += f"\n{FLAG_TIPS[flag][0]} : {FLAG_TIPS[flag][2]}"
            self.setToolTip(tip)
            self.update()

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit()

    def sizeHint(self) -> QSize:
        return QSize(80, 44)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        enabled = self.isEnabled()
        hover = self.underMouse() and enabled
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = min(10.0, rect.height() / 2)
        color = QColor(self._color)
        theme_fg = qc("text")

        if not enabled:
            color.setAlpha(110)
        if self._active and enabled:
            # halo : trois liserés de plus en plus pâles autour du bouton plein (comme le voyant de l'ampli)
            base = rect.adjusted(3, 3, -3, -3)
            for grow, alpha in ((2.6, 38), (1.6, 70), (0.8, 120)):
                glow = QColor(color); glow.setAlpha(alpha)
                gp = QPen(glow); gp.setWidthF(1.6)
                p.setPen(gp); p.setBrush(Qt.NoBrush)
                r = base.adjusted(-grow, -grow, grow, grow)
                p.drawRoundedRect(r, radius + grow, radius + grow)
            rect = base
            radius = min(radius, rect.height() / 2)
        if self._active:
            bg, border, fg = QColor(color), QColor(color), _contrast(color)
        else:
            bg = QColor(color); bg.setAlpha(64 if hover else 34)
            border = QColor(color); border.setAlpha(190 if hover else 130)
            fg = theme_fg
        if not enabled:
            fg = QColor(128, 128, 128, 170)
        if self.isDown() and enabled:
            bg = bg.darker(115)
        pen = QPen(border); pen.setWidthF(1.4)
        p.setPen(pen)
        p.setBrush(bg)
        p.drawRoundedRect(rect, radius, radius)

        number = str(display_number(self.index))
        font = QFont(QApplication.font()); font.setBold(True)
        p.setPen(fg)
        if self._kind == "number":
            font.setPixelSize(max(13, int(min(rect.height() * 0.5, 20))))
            p.setFont(font)
            p.drawText(rect, Qt.AlignCenter, number)
        else:
            font.setPixelSize(self._font_px)   # même taille pour tous les presets (cf PresetPanel._plan)
            p.setFont(font)
            p.drawText(text_rect(rect), int(Qt.AlignCenter | Qt.TextWordWrap), self._name)
            if self._kind == "card" and self._custom:   # le numéro reste lisible quand le preset a un nom perso
                small = QFont(font); small.setPixelSize(10); small.setBold(False)
                p.setFont(small)
                p.drawText(rect.adjusted(9, 5, -8, 0), Qt.AlignTop | Qt.AlignLeft, number)
        if self._flag in FLAG_TIPS and enabled:   # pastille d'alerte : l'emplacement n'est plus identique à la bibliothèque
            dot = QColor(FLAG_TIPS[self._flag][1])
            ring = QPen(qc("surface")); ring.setWidthF(1.6)
            p.setPen(ring); p.setBrush(dot)
            p.drawEllipse(rect.topRight() + QPointF(-9, 9), 4.5, 4.5)
        p.end()


def text_rect(rect: QRectF) -> QRectF:
    """Zone où s'écrit le nom d'un preset dans son bouton."""
    return rect.adjusted(8, 4, -8, -4)


def fit_font_px(names: list[str], rect_w: float, rect_h: float) -> int | None:
    """Plus grande taille de police (MAX_FONT_PX à MIN_FONT_PX) pour laquelle TOUS les noms tiennent dans
    une zone `rect_w` x `rect_h` (retour à la ligne aux espaces seulement). None si même la plus petite
    taille ne suffit pas pour l'un d'eux : on passe alors aux chiffres."""
    font = QFont(QApplication.font()); font.setBold(True)
    for size in range(MAX_FONT_PX, MIN_FONT_PX - 1, -1):
        font.setPixelSize(size)
        fm = QFontMetrics(font)
        if all(fm.boundingRect(0, 0, int(rect_w), 10000, int(Qt.AlignCenter | Qt.TextWordWrap), n).height() <= rect_h
               and fm.boundingRect(0, 0, int(rect_w), 10000, int(Qt.AlignCenter | Qt.TextWordWrap), n).width() <= rect_w + 1
               for n in names):
            return size
    return None


class _Area(QWidget):
    """Zone de contenu : prévient le panneau quand elle change de taille (il y replace ses widgets à la main)."""

    def __init__(self, on_resize, parent=None):
        super().__init__(parent)
        self._on_resize = on_resize
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._on_resize()


class PresetPanel(ModuleCard):
    adaptive = True

    def __init__(self, state: AmpState, sender: MidiSender, parent=None, names: SlotNames | None = None):
        super().__init__(parent, accent=MODULE_COLORS["presets"])
        self.setTitle("Presets")

        self._state = state
        self._sender = sender
        self.names = names if names is not None else SlotNames(parent=self)   # partagé avec l'éditeur quand il est fourni
        self._buttons: dict[int, PresetButton] = {}
        self._plan_key = None

        self._build_ui()
        self._apply_state()
        self._state.preset_changed.connect(lambda _i: self._apply_state())
        self.names.changed.connect(self._relayout)   # nom ou état modifié (ici, dans l'éditeur ou sur l'ampli)

    @property
    def _names(self) -> dict[int, str]:
        """Noms perso historiques (hors bibliothèque), lecture seule : sert aux tests et à la compatibilité."""
        return self.names._legacy

    # --- Construction ---

    def _build_ui(self):
        self._area = _Area(self._relayout)
        self.viewLayout.addWidget(self._area)

        for i in range(CHANNELS_COUNT):
            btn = PresetButton(i, self._area)
            btn.clicked.connect(lambda _c=False, idx=i: self._on_button_clicked(idx))
            btn.double_clicked.connect(self._open_rename_popup)
            self._buttons[i] = btn

        # Niveau minuscule : ◀ nom ▶
        self._prev_btn = TransparentToolButton(FluentIcon.PAGE_LEFT, self._area)
        self._next_btn = TransparentToolButton(FluentIcon.PAGE_RIGHT, self._area)
        self._prev_btn.setToolTip("Preset précédent")
        self._next_btn.setToolTip("Preset suivant")
        self._prev_btn.clicked.connect(lambda: self._step(-1))
        self._next_btn.clicked.connect(lambda: self._step(+1))
        self._strip_btn = PresetButton(0, self._area)
        self._strip_btn.double_clicked.connect(self._open_rename_popup)

        # Engrenage de l'en-tête : renommer le preset actif (niveaux moyen / petit / minuscule)
        self._gear_btn = TransparentToolButton(FluentIcon.EDIT)
        self._gear_btn.setToolTip("Renommer le preset actif")
        self._gear_btn.clicked.connect(self._open_rename_popup)
        self.add_header_action(self._gear_btn)

        popup = QFrame(self, Qt.Popup)
        popup.setObjectName("PresetRenamePopup")
        style_popup(popup)
        v = QVBoxLayout(popup)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)
        self._popup_title = StrongBodyLabel("Renommer")
        v.addWidget(self._popup_title)
        row2 = QHBoxLayout()
        self._popup_edit = LineEdit()
        self._popup_edit.setMinimumWidth(180)
        self._popup_edit.returnPressed.connect(self._on_popup_validated)
        ok = PushButton("Enregistrer")
        ok.clicked.connect(self._on_popup_validated)
        row2.addWidget(self._popup_edit, stretch=1)
        row2.addWidget(ok)
        v.addLayout(row2)
        self._rename_popup = popup

    # --- Taille ---

    def minimumSizeHint(self) -> QSize:
        return QSize(190, self.chrome_height() + 4 + 38)

    def sizeHint(self) -> QSize:
        return QSize(440, self.chrome_height() + 4 + 2 * 64 + GAP)

    # --- Choix de la présentation selon la place ---

    @staticmethod
    def _plan(width: int, height: int, names: list[str]):
        """(mode, colonnes, taille de police). Les noms restent affichés tant qu'ils tiennent TOUS à une
        taille lisible (même taille pour tous les presets) ; sinon une rangée de pastilles numérotées, puis
        « ◀ nom ▶ » quand c'est très étroit."""
        for cols in (4, 7, 3, 2, 1):
            rows = math.ceil(CHANNELS_COUNT / cols)
            bw = (width - (cols - 1) * GAP) / cols
            bh = min(MAX_BUTTON_H, (height - (rows - 1) * GAP) / rows)
            if bw < 58 or bh < 40:
                continue
            size = fit_font_px(names, text_rect(QRectF(0, 0, bw - 2, bh - 2)).width(),
                               text_rect(QRectF(0, 0, bw - 2, bh - 2)).height())
            if size is not None:
                return "grid", cols, size
        if width >= 7 * 26 + 6 * 4 and height >= 30:
            return "numbers", 7, 0
        return "strip", 0, 0

    def _relayout(self):
        """Replace les widgets selon la place (appelé au redimensionnement et quand un nom change)."""
        w, h = self._area.width(), self._area.height()
        if w < 10 or h < 10:
            return
        names = [self._name_of(i)[0] for i in range(CHANNELS_COUNT)]
        mode, cols, size = self._plan(w, h, names)
        for widget in (self._prev_btn, self._next_btn, self._strip_btn, *self._buttons.values()):
            widget.hide()

        kinds = {}
        if mode == "grid":
            rows = math.ceil(CHANNELS_COUNT / cols)
            bw = (w - (cols - 1) * GAP) / cols
            bh = min(MAX_BUTTON_H, (h - (rows - 1) * GAP) / rows)
            kind = "card" if bh >= 52 else "flat"
            for i, btn in self._buttons.items():
                r, c = divmod(i, cols)
                btn.setGeometry(round(c * (bw + GAP)), round(r * (bh + GAP)), round(bw), round(bh))
                kinds[i] = kind
                btn.show()
        elif mode == "numbers":
            bw = (w - 6 * 4) / 7
            bh = min(h, 40)
            for i, btn in self._buttons.items():
                btn.setGeometry(round(i * (bw + 4)), round((h - bh) / 2), round(bw), round(bh))
                kinds[i] = "number"
                btn.show()
        else:
            bh = min(h, 44)
            y = round((h - bh) / 2)
            self._prev_btn.setGeometry(0, y, 34, bh)
            self._next_btn.setGeometry(w - 34, y, 34, bh)
            self._strip_btn.setGeometry(38, y, w - 76, bh)
            for widget in (self._prev_btn, self._next_btn, self._strip_btn):
                widget.show()
        self._kinds, self._font_px = kinds, size or MIN_FONT_PX
        self._apply_state()

    # --- État ---

    def _name_of(self, index: int) -> tuple[str, bool]:
        return self.names.name(index)

    def _apply_state(self):
        active = self._state.current_preset
        kinds = getattr(self, "_kinds", {})
        for i, btn in self._buttons.items():
            name, custom = self._name_of(i)
            flag = self.names.state(i)[0]
            btn.set_info(name, custom, i == active, kinds.get(i, "card"), getattr(self, "_font_px", MAX_FONT_PX),
                         flag if flag in FLAG_TIPS else None)
        name, custom = self._name_of(active)
        flag = self.names.state(active)[0]
        self._strip_btn.index = active
        self._strip_btn._color = QColor(PRESET_COLORS.get(active, "#888888"))
        self._strip_btn.set_info(name, custom, True, "flat", MIN_FONT_PX, flag if flag in FLAG_TIPS else None)
        self._strip_btn.update()

    # --- Actions ---

    def _on_button_clicked(self, index: int):
        self._sender.set_preset(index)
        # Pas d'écho matériel pour une commande initiée par l'hôte (cf docstring du module) :
        # on met à jour l'état nous-mêmes.
        self._state.on_preset_changed(index)

    def _step(self, direction: int):
        self._on_button_clicked((self._state.current_preset + direction) % CHANNELS_COUNT)

    def reload_names(self):
        """Relit les noms depuis le fichier (import / réinitialisation depuis la page Réglages)."""
        self.names.reload()
        self._relayout()

    def _rename_active(self, text: str):
        if self.names.rename(self._state.current_preset, text):
            self._relayout()   # un nom plus long peut obliger à réduire la police (ou passer en chiffres)

    def _open_rename_popup(self):
        active = self._state.current_preset
        linked = self.names.entry(active) is not None
        self._popup_title.setText(f"Renommer le preset {display_number(active)}"
                                  + (" (aussi dans la bibliothèque)" if linked else ""))
        name, custom = self.names.name(active)
        self._popup_edit.setText(name if custom else "")
        self._popup_edit.setPlaceholderText(default_name(active))
        if not self._rename_popup.isVisible():
            show_popup_under(self._rename_popup, self._gear_btn, True)
        self._popup_edit.setFocus()
        self._popup_edit.selectAll()

    def _on_popup_validated(self):
        self._rename_active(self._popup_edit.text())
        self._rename_popup.hide()