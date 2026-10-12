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

IMPORTANT (bug corrigé) : le device n'envoie PAS d'écho de confirmation après une commande
program_change initiée par l'hôte (confirmé empiriquement, cf docs/protocol_notes.md — seuls les
changements physiques sont notifiés spontanément). Attendre cet écho pour rafraîchir l'UI bloquait
l'affichage indéfiniment pour tout clic logiciel. On met donc à jour l'état nous-mêmes juste après
avoir envoyé la commande ; les appuis physiques restent notifiés normalement via listener -> state.
"""

import json
import math
from pathlib import Path

from PySide6.QtCore import Qt, QRectF, QSize, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QApplication, QFrame, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, FluentIcon, LineEdit, PushButton, StrongBodyLabel, TransparentToolButton,
                            isDarkTheme)

from midi.protocol import CHANNELS_COUNT
from midi.sender import MidiSender
from state.amp_state import AmpState
from paths import PRESET_NAMES_FILE
from ui.module_card import MODULE_COLORS, ModuleCard
from ui.popup_utils import show_popup_under

# Fichier à côté de ce module, indépendant du dossier de lancement de l'appli
# (si tu as déjà des presets renommés, déplace l'ancien preset_names.json ici)
NAMES_FILE = PRESET_NAMES_FILE

# Couleur associée à chaque preset (fournie par l'utilisateur)
PRESET_COLORS = {
    0: "#61D149",
    1: "#E98D32",
    2: "#EA5A53",
    3: "#2C75EE",
    4: "#46D1E6",
    5: "#DF74D6",
    6: "#FBB6F4",
}

GAP = 8
MAX_BUTTON_H = 72
MIN_FONT_PX = 15   # en dessous, les noms passent en chiffres plutôt que de devenir illisibles
MAX_FONT_PX = 20


def display_number(index: int) -> int:
    """Index interne (0-6, protocole) -> numéro affiché (1-7)."""
    return index + 1


def default_name(index: int) -> str:
    return f"Preset {display_number(index)}"


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
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)   # cliquer un preset ne doit pas voler le focus du clavier
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_info(self, name: str, custom: bool, active: bool, kind: str, font_px: int | None = None):
        font_px = font_px or self._font_px
        if (name, custom, active, kind, font_px) != (self._name, self._custom, self._active, self._kind, self._font_px):
            self._name, self._custom, self._active, self._kind, self._font_px = name, custom, active, kind, font_px
            self.setToolTip(f"{display_number(self.index)} — {name}")
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
        theme_fg = QColor("#e8e8e8" if isDarkTheme() else "#202020")

        if not enabled:
            color.setAlpha(110)
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

    def __init__(self, state: AmpState, sender: MidiSender, parent=None):
        super().__init__(parent, accent=MODULE_COLORS["presets"])
        self.setTitle("Presets")

        self._state = state
        self._sender = sender
        self._names: dict[int, str] = self._load_names()
        self._buttons: dict[int, PresetButton] = {}
        self._plan_key = None

        self._build_ui()
        self._apply_state()
        self._state.preset_changed.connect(lambda _i: self._apply_state())

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
        popup.setStyleSheet("#PresetRenamePopup { background: palette(window); "
                            "border: 1px solid rgba(128,128,128,0.45); border-radius: 8px; }")
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
        custom = self._names.get(index)
        return (custom, True) if custom else (default_name(index), False)

    def _apply_state(self):
        active = self._state.current_preset
        kinds = getattr(self, "_kinds", {})
        for i, btn in self._buttons.items():
            name, custom = self._name_of(i)
            btn.set_info(name, custom, i == active, kinds.get(i, "card"), getattr(self, "_font_px", MAX_FONT_PX))
        name, custom = self._name_of(active)
        self._strip_btn.index = active
        self._strip_btn._color = QColor(PRESET_COLORS.get(active, "#888888"))
        self._strip_btn.set_info(name, custom, True, "flat", MIN_FONT_PX)
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
        self._names = self._load_names()
        self._relayout()

    def _rename_active(self, text: str):
        text = text.strip()
        if not text:
            return
        self._names[self._state.current_preset] = text
        self._save_names()
        self._relayout()   # un nom plus long peut obliger à réduire la police (ou passer en chiffres)

    def _open_rename_popup(self):
        active = self._state.current_preset
        self._popup_title.setText(f"Renommer le preset {display_number(active)}")
        self._popup_edit.setText(self._names.get(active, ""))
        self._popup_edit.setPlaceholderText(default_name(active))
        if not self._rename_popup.isVisible():
            show_popup_under(self._rename_popup, self._gear_btn, True)
        self._popup_edit.setFocus()
        self._popup_edit.selectAll()

    def _on_popup_validated(self):
        self._rename_active(self._popup_edit.text())
        self._rename_popup.hide()

    # --- Persistance des noms (simple JSON local, à côté du module ; clés = index interne 0-6) ---

    def _load_names(self) -> dict[int, str]:
        if NAMES_FILE.exists():
            try:
                raw = json.loads(NAMES_FILE.read_text(encoding="utf-8"))
                return {int(k): v for k, v in raw.items()}
            except (json.JSONDecodeError, ValueError):
                return {}
        return {}

    def _save_names(self):
        NAMES_FILE.write_text(json.dumps(self._names, ensure_ascii=False, indent=2), encoding="utf-8")