"""
Module Setlist.

Une séquence nommée = un morceau : une liste ordonnée d'étapes, chaque étape = un preset (0-6) + un label
facultatif ("Couplet", "Refrain"...). Deux modes dans le même module :

- **Jeu** (par défaut) : l'étape courante en grand (couleur du preset), les deux suivantes en dessous (clic =
  y sauter), Précédent / Suivant. Le module s'adapte à sa taille (2 suivantes -> 1 -> aucune, choix de la
  séquence masqué quand c'est trop petit, boutons réduits à leurs flèches).
- **Édition** (crayon de l'en-tête) : créer / renommer / supprimer la séquence, ajouter, régler, réordonner
  et supprimer les étapes.

L'interrupteur « Active / Coupée » (en-tête) dit si la navigation pilote le preset du device ; sans lui on garde
sa position dans la séquence sans reprendre la main (utile pour répéter). Il est partagé entre Dashboard et
Classique via AmpState.

Le panneau connaît AmpState/MidiSender : avancer d'une étape change réellement le preset sur le device, avec la
même mise à jour optimiste que preset_panel.py (pas d'écho matériel pour une commande host).
"""

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QApplication, QFrame, QHBoxLayout, QLabel, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)
from qfluentwidgets import (BodyLabel, FluentIcon, LineEdit, PushButton, TransparentToolButton, isDarkTheme)

from midi.protocol import CHANNELS_COUNT
from midi.sender import MidiSender
from settings import load_settings, update_settings
from setlist.model import Sequence, Step, load_sequences, save_sequences
from setlist.player import SetlistPlayer
from state.amp_state import AmpState
from ui.module_card import MODULE_COLORS, ModuleCard
from ui.power_pill import PowerPill as _BasePill
from ui.preset_panel import PRESET_COLORS, _contrast
from ui.widgets import NoWheelComboBox, NoWheelSpinBox

ACCENT = MODULE_COLORS["setlist"]
CURRENT_MIN_H, CURRENT_MAX_H = 56, 78
NEXT_H, GAP = 34, 6
NAV_H = 44
COMBO_ROW_H = 36


def _font(px: int, bold: bool = False) -> QFont:
    f = QFont(QApplication.font())
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def _text_color() -> QColor:
    return QColor("#f2f2f2" if isDarkTheme() else "#1f1f1f")


class PowerPill(_BasePill):
    """Interrupteur « Active / Coupée » de l'en-tête."""

    def __init__(self, parent=None):
        super().__init__(ACCENT, "Active : suivant / précédent changent le preset de l'ampli.\n"
                                 "Coupée : on se déplace dans la séquence sans toucher au preset.", parent=parent)


class StepsView(QWidget):
    """Étape courante en grand + les suivantes. Un clic sur une suivante y saute."""

    step_clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._steps: list[Step] = []
        self._index = 0
        self._enabled = True
        self._message = ""
        self._hits: list[tuple[QRectF, int]] = []
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_data(self, steps: list[Step], index: int, enabled: bool, message: str = ""):
        self._steps, self._index, self._enabled, self._message = list(steps), index, enabled, message
        self.update()

    def next_count(self) -> int:
        """Nombre d'étapes suivantes affichables dans la hauteur actuelle."""
        n = len(self._steps)
        if n <= 1:
            return 0
        fit = max(0, int((self.height() - CURRENT_MIN_H + GAP) // (NEXT_H + GAP)))
        return min(2, n - 1, fit)

    def _step_title(self, step: Step) -> str:
        return step.label or f"Preset {step.preset + 1}"

    def mousePressEvent(self, event):
        pos = event.position()
        for rect, idx in self._hits:
            if rect.contains(pos):
                self.step_clicked.emit(idx)
                return

    def mouseMoveEvent(self, event):
        pos = event.position()
        over = any(r.contains(pos) for r, _i in self._hits)
        self.setCursor(Qt.PointingHandCursor if over else Qt.ArrowCursor)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._hits = []
        w, h = self.width(), self.height()
        text = _text_color()
        if not self._steps:
            faint = QColor(text); faint.setAlpha(150)
            p.setPen(faint)
            msg = self._message
            if h < 70:   # tout petit : une seule phrase, plus petite
                msg = msg.split(".")[0] + "."
            p.setFont(_font(14 if h >= 70 else 12))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter | Qt.TextWordWrap, msg)
            p.end()
            return
        self.setMouseTracking(True)

        n = len(self._steps)
        nexts = self.next_count()
        cur_h = max(CURRENT_MIN_H, min(CURRENT_MAX_H, h - nexts * (NEXT_H + GAP))) if nexts else min(h, CURRENT_MAX_H + 20)
        cur_h = min(cur_h, h)
        step = self._steps[self._index]
        color = QColor(PRESET_COLORS.get(step.preset, "#888888"))

        # --- étape courante ---
        rect = QRectF(0, 0, w, cur_h)
        if self._enabled:
            p.setPen(Qt.NoPen); p.setBrush(color); fg = _contrast(color)
        else:
            fill = QColor(color); fill.setAlpha(55)
            border = QColor(color); border.setAlpha(170)
            p.setPen(QPen(border, 1.5)); p.setBrush(fill); fg = text
        p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 10, 10)
        num_w = min(64, cur_h + 6)
        p.setPen(fg)
        p.setFont(_font(max(22, min(36, int(cur_h * 0.55))), True))
        p.drawText(QRectF(8, 0, num_w - 8, cur_h), Qt.AlignCenter, str(step.preset + 1))
        body = QRectF(num_w + 4, 4, w - num_w - 14, cur_h - 8)
        title_font = _font(16, True)
        pos_text = f"{self._index + 1}/{n}"
        p.setFont(_font(12))
        pos_w = QFontMetrics(p.font()).horizontalAdvance(pos_text) + 4
        p.drawText(QRectF(w - pos_w - 10, 6, pos_w, 16), Qt.AlignRight | Qt.AlignTop, pos_text)
        two_lines = bool(step.label) and cur_h >= 62
        p.setFont(title_font)
        title = QFontMetrics(title_font).elidedText(self._step_title(step), Qt.ElideRight, int(body.width() - pos_w - 6))
        title_rect = QRectF(body.left(), body.top(), body.width() - pos_w - 6, body.height() - (16 if two_lines else 0))
        p.drawText(title_rect, Qt.AlignVCenter | Qt.AlignLeft, title)
        if two_lines:
            sub = QColor(fg); sub.setAlpha(190)
            p.setPen(sub); p.setFont(_font(12))
            p.drawText(QRectF(body.left(), body.bottom() - 18, body.width(), 16), Qt.AlignLeft | Qt.AlignVCenter,
                       f"Preset {step.preset + 1}")

        # --- suivantes ---
        y = cur_h + GAP
        for k in range(1, nexts + 1):
            idx = (self._index + k) % n
            st = self._steps[idx]
            c = QColor(PRESET_COLORS.get(st.preset, "#888888"))
            r = QRectF(0, y, w, NEXT_H)
            fill = QColor(c); fill.setAlpha(46)
            p.setPen(Qt.NoPen); p.setBrush(fill)
            p.drawRoundedRect(r.adjusted(1, 0, -1, 0), 8, 8)
            chip = QRectF(8, y + (NEXT_H - 20) / 2, 20, 20)
            p.setBrush(c); p.drawEllipse(chip)
            p.setPen(_contrast(c)); p.setFont(_font(12, True))
            p.drawText(chip, Qt.AlignCenter, str(st.preset + 1))
            tcol = QColor(text); tcol.setAlpha(220 if k == 1 else 170)
            p.setPen(tcol); p.setFont(_font(14, k == 1))
            label = QFontMetrics(p.font()).elidedText(self._step_title(st), Qt.ElideRight, int(w - 80))
            p.drawText(QRectF(36, y, w - 80, NEXT_H), Qt.AlignVCenter | Qt.AlignLeft, label)
            idx_col = QColor(text); idx_col.setAlpha(120)
            p.setPen(idx_col); p.setFont(_font(12))
            p.drawText(QRectF(w - 44, y, 34, NEXT_H), Qt.AlignVCenter | Qt.AlignRight, f"{idx + 1}")
            self._hits.append((r, idx))
            y += NEXT_H + GAP
        p.end()


class StepRow(QFrame):
    """Une ligne de l'éditeur : n°, preset (couleur + valeur), label, ▲ ▼ supprimer."""

    preset_edited = Signal(int, int)    # (étape, preset 0-6)
    label_edited = Signal(int, str)
    move_requested = Signal(int, int)   # (étape, ±1)
    delete_requested = Signal(int)

    def __init__(self, index: int, step: Step, count: int, current: bool, parent=None):
        super().__init__(parent)
        self._index = index
        self.setObjectName("StepRow")
        self.setStyleSheet("#StepRow { background: rgba(44,117,238,0.14); border-radius: 6px; }" if current
                           else "#StepRow { background: transparent; }")
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(6)
        num = QLabel(str(index + 1))
        num.setFixedWidth(18)
        num.setAlignment(Qt.AlignCenter)
        num.setStyleSheet("color: gray;")
        row.addWidget(num)
        self._swatch = QLabel()
        self._swatch.setFixedSize(10, 24)
        row.addWidget(self._swatch)
        self._spin = NoWheelSpinBox()
        self._spin.setRange(1, CHANNELS_COUNT)     # affiché 1-7
        self._spin.setFixedWidth(120)
        self._spin.setValue(step.preset + 1)
        self._spin.valueChanged.connect(self._on_spin)
        row.addWidget(self._spin)
        self._edit = LineEdit()
        self._edit.setPlaceholderText("Label (Couplet, Refrain…)")
        self._edit.setText(step.label)
        self._edit.editingFinished.connect(lambda: self.label_edited.emit(self._index, self._edit.text().strip()))
        row.addWidget(self._edit, stretch=1)
        for icon, tip, handler, enabled in (
                (FluentIcon.UP, "Monter", lambda: self.move_requested.emit(self._index, -1), index > 0),
                (FluentIcon.DOWN, "Descendre", lambda: self.move_requested.emit(self._index, +1), index < count - 1),
                (FluentIcon.DELETE, "Supprimer l'étape", lambda: self.delete_requested.emit(self._index), True)):
            btn = TransparentToolButton(icon)
            btn.setFixedSize(28, 28)
            btn.setToolTip(tip)
            btn.setEnabled(enabled)
            btn.clicked.connect(lambda _c=False, h=handler: h())
            row.addWidget(btn)
        self._paint_swatch()

    def _paint_swatch(self):
        color = PRESET_COLORS.get(self._spin.value() - 1, "#888888")
        self._swatch.setStyleSheet(f"background: {color}; border-radius: 3px;")

    def _on_spin(self, value: int):
        self._paint_swatch()
        self.preset_edited.emit(self._index, value - 1)


class SetlistPanel(ModuleCard):
    adaptive = True

    def __init__(self, state: AmpState, sender: MidiSender, parent=None):
        super().__init__(parent, accent=ACCENT)
        self.setTitle("Setlist")

        self._state = state
        self._sender = sender
        self._settings = load_settings()
        self._editing = False
        self._delete_armed = False

        self._player = SetlistPlayer()
        self._player.step_changed.connect(self._on_step_changed)
        self._player.sequence_changed.connect(self._refresh_all)

        self._build_ui()
        self._restore_settings()

    # --- Construction ---

    def _build_ui(self):
        # En-tête : interrupteur + crayon
        self._enabled_switch = PowerPill()
        self._enabled_switch.toggled.connect(self._on_enabled_toggled)
        # Interrupteur partagé entre Dashboard et Classique (via AmpState)
        self._state.setlist_enabled_changed.connect(self._on_shared_enabled_changed)
        self.headerLayout.addWidget(self._enabled_switch)
        self._edit_btn = TransparentToolButton(FluentIcon.EDIT)
        self._edit_btn.setToolTip("Modifier les séquences")
        self._edit_btn.clicked.connect(lambda: self._set_editing(not self._editing))
        self.add_header_action(self._edit_btn)

        root = QVBoxLayout()
        root.setSpacing(GAP + 2)
        root.setContentsMargins(0, 0, 0, 0)
        self.viewLayout.addLayout(root)

        # Ligne du haut : choix de la séquence (+ nouvelle / supprimer en édition)
        self._top_w = QWidget()
        top = QHBoxLayout(self._top_w)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        self._sequence_combo = NoWheelComboBox()
        self._sequence_combo.currentIndexChanged.connect(self._on_sequence_selected)
        top.addWidget(self._sequence_combo, stretch=1)
        self._new_btn = TransparentToolButton(FluentIcon.ADD)
        self._new_btn.setToolTip("Nouvelle séquence")
        self._new_btn.setFixedSize(32, 32)
        self._new_btn.clicked.connect(self._on_new_sequence)
        self._delete_btn = TransparentToolButton(FluentIcon.DELETE)
        self._delete_btn.setToolTip("Supprimer la séquence (deux clics)")
        self._delete_btn.setFixedSize(32, 32)
        self._delete_btn.clicked.connect(self._on_delete_sequence)
        top.addWidget(self._new_btn)
        top.addWidget(self._delete_btn)
        root.addWidget(self._top_w)

        # --- Jeu ---
        self._play_w = QWidget()
        play = QVBoxLayout(self._play_w)
        play.setContentsMargins(0, 0, 0, 0)
        play.setSpacing(GAP + 2)
        self._steps_view = StepsView()
        self._steps_view.step_clicked.connect(self._player.go_to)
        play.addWidget(self._steps_view, stretch=1)
        nav = QHBoxLayout()
        nav.setSpacing(8)
        self._prev_btn = PushButton("◀  Précédent")
        self._next_btn = PushButton("Suivant  ▶")
        for btn in (self._prev_btn, self._next_btn):
            btn.setMinimumHeight(NAV_H - 4)
        self._prev_btn.clicked.connect(self._player.previous_step)
        self._next_btn.clicked.connect(self._player.next_step)
        nav.addWidget(self._prev_btn)
        nav.addWidget(self._next_btn)
        play.addLayout(nav)
        root.addWidget(self._play_w, stretch=1)

        # --- Édition ---
        self._edit_w = QWidget()
        edit = QVBoxLayout(self._edit_w)
        edit.setContentsMargins(0, 0, 0, 0)
        edit.setSpacing(GAP + 2)
        self._name_edit = LineEdit()
        self._name_edit.setPlaceholderText("Nom du morceau")
        self._name_edit.editingFinished.connect(self._on_rename)
        edit.addWidget(self._name_edit)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._rows_w = QWidget()
        self._rows_w.setStyleSheet("background: transparent;")
        self._rows = QVBoxLayout(self._rows_w)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(2)
        self._rows.addStretch()
        self._scroll.setWidget(self._rows_w)
        edit.addWidget(self._scroll, stretch=1)
        self._add_step_btn = PushButton("＋  Ajouter une étape")
        self._add_step_btn.clicked.connect(self._on_add_step)
        edit.addWidget(self._add_step_btn)
        root.addWidget(self._edit_w, stretch=1)

        self._delete_timer = QTimer(self)
        self._delete_timer.setSingleShot(True)
        self._delete_timer.setInterval(3000)
        self._delete_timer.timeout.connect(self._disarm_delete)

        self._apply_mode()

    # --- Taille / densité ---

    def _base_height(self) -> int:
        return self.chrome_height() + 4 + CURRENT_MIN_H + GAP + 2 + NAV_H

    def minimumSizeHint(self) -> QSize:
        return QSize(220, self._base_height())

    def sizeHint(self) -> QSize:
        return QSize(420, self._base_height() + COMBO_ROW_H + GAP + 2 + 2 * (NEXT_H + GAP) + 24)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_density()

    def _apply_density(self):
        if self._editing:
            self._top_w.setVisible(True)
            return
        room = self.height() - self._base_height()
        show_combo = room >= COMBO_ROW_H + GAP + 2 + NEXT_H + GAP
        self._top_w.setVisible(show_combo)
        compact = self.width() < 300
        self._prev_btn.setText("◀" if compact else "◀  Précédent")
        self._next_btn.setText("▶" if compact else "Suivant  ▶")
        self._update_title()

    def _update_title(self):
        seq = self._player.active_sequence
        suffix = f" — {seq.name}" if seq is not None and not self._top_w.isVisible() and not self._editing else ""
        self.setTitle("Setlist" + suffix)

    # --- Modes ---

    def _set_editing(self, editing: bool):
        self._editing = editing
        self._disarm_delete()
        self._apply_mode()
        self._refresh_all()

    def _apply_mode(self):
        e = self._editing
        self._play_w.setVisible(not e)
        self._edit_w.setVisible(e)
        self._new_btn.setVisible(e)
        self._delete_btn.setVisible(e)
        self._edit_btn.setIcon(FluentIcon.ACCEPT if e else FluentIcon.EDIT)
        self._edit_btn.setToolTip("Terminer l'édition" if e else "Modifier les séquences")
        self._apply_density()

    # --- Restauration au lancement ---

    def _restore_settings(self):
        s = self._settings["setlist"]
        self._enabled_switch.blockSignals(True)
        self._enabled_switch.setChecked(self._state.setlist_enabled)
        self._enabled_switch.blockSignals(False)

        sequences = load_sequences()
        self._player.set_sequences(sequences)  # déclenche _refresh_all via le signal

        active_name = s["active_sequence_name"]
        if active_name:
            for i, seq in enumerate(sequences):
                if seq.name == active_name:
                    self._player.set_active(i)  # renvoie aussi le preset de l'étape (si activée)
                    break
        self._refresh_all()

    def _save_setlist_settings(self):
        seq = self._player.active_sequence
        self._settings["setlist"] = {
            "active_sequence_name": seq.name if seq else None,
            "enabled": self._enabled_switch.isChecked(),
        }
        update_settings({"setlist": self._settings["setlist"]})  # seulement notre section (cf settings.py)

    # --- Séquences ---

    def _unique_name(self, base: str, ignore: Sequence | None = None) -> str:
        names = {s.name for s in self._player.sequences if s is not ignore}
        if base not in names:
            return base
        k = 2
        while f"{base} {k}" in names:
            k += 1
        return f"{base} {k}"

    def _on_new_sequence(self):
        sequences = list(self._player.sequences)
        sequences.append(Sequence(name=self._unique_name("Nouveau morceau"), steps=[]))
        save_sequences(sequences)
        self._player.set_sequences(sequences)
        self._player.set_active(len(sequences) - 1)
        self._save_setlist_settings()
        self._name_edit.setFocus()
        self._name_edit.selectAll()

    def _on_rename(self):
        seq = self._player.active_sequence
        name = self._name_edit.text().strip()
        if seq is None or not name or name == seq.name:
            if seq is not None:
                self._name_edit.setText(seq.name)
            return
        seq.name = self._unique_name(name, ignore=seq)
        save_sequences(self._player.sequences)
        self._save_setlist_settings()
        self._name_edit.setText(seq.name)
        self._fill_combo()

    def _disarm_delete(self):
        self._delete_armed = False
        self._delete_timer.stop()
        self._delete_btn.setIcon(FluentIcon.DELETE)

    def _on_delete_sequence(self):
        idx = self._player.active_index
        if idx is None:
            return
        seq = self._player.active_sequence
        if seq.steps and not self._delete_armed:   # une séquence non vide : deuxième clic pour confirmer
            self._delete_armed = True
            self._delete_btn.setIcon(FluentIcon.CANCEL)
            self._delete_btn.setToolTip("Clique encore pour supprimer")
            self._delete_timer.start()
            return
        self._disarm_delete()
        sequences = list(self._player.sequences)
        del sequences[idx]
        save_sequences(sequences)
        self._player.set_sequences(sequences)
        self._player.set_active(None)
        self._save_setlist_settings()

    def _on_sequence_selected(self, index: int):
        self._disarm_delete()
        # index 0 = "(aucune)" : permet explicitement de ne rien sélectionner
        self._player.set_active(None if index <= 0 else index - 1)
        self._save_setlist_settings()

    # --- Étapes (édition) ---

    def _persist_steps(self):
        save_sequences(self._player.sequences)

    def _on_add_step(self):
        seq = self._player.active_sequence
        if seq is None:
            return
        preset = (seq.steps[-1].preset + 1) % CHANNELS_COUNT if seq.steps else 0
        seq.steps.append(Step(preset=preset, label=""))
        self._persist_steps()
        self._refresh_steps()
        if len(seq.steps) == 1:  # c'était vide : personne n'a encore activé l'étape 0
            self._player.refresh_current()
        self._scroll.verticalScrollBar().setValue(self._scroll.verticalScrollBar().maximum() + 100)

    def _on_delete_step(self, index: int):
        seq = self._player.active_sequence
        if seq is None or not (0 <= index < len(seq.steps)):
            return
        del seq.steps[index]
        self._persist_steps()
        self._player.notify_step_removed(index)  # recale l'étape courante + notifie
        self._refresh_steps()

    def _on_move_step(self, index: int, delta: int):
        if self._player.move_step(index, delta):
            self._persist_steps()
            self._refresh_steps()
            self._refresh_current_step()

    def _on_step_preset_edited(self, index: int, preset: int):
        seq = self._player.active_sequence
        if seq is None or not (0 <= index < len(seq.steps)):
            return
        seq.steps[index].preset = preset
        self._persist_steps()
        self._refresh_current_step()
        if index == self._player.step_index:
            self._on_step_changed(index)   # l'étape courante a changé de preset : on le renvoie

    def _on_step_label_edited(self, index: int, text: str):
        seq = self._player.active_sequence
        if seq is None or not (0 <= index < len(seq.steps)) or seq.steps[index].label == text:
            return
        seq.steps[index].label = text
        self._persist_steps()
        self._refresh_current_step()

    # --- Navigation : c'est ICI qu'on parle au device (le player, lui, ne connaît pas le MIDI) ---

    def _on_step_changed(self, _index: int):
        step = self._player.current_step()
        if step is not None and self._enabled_switch.isChecked():
            self._sender.set_preset(step.preset)
            self._state.on_preset_changed(step.preset)  # mise à jour optimiste, cf preset_panel.py
        self._refresh_current_step()
        if self._editing:
            self._refresh_steps()

    def _on_shared_enabled_changed(self, enabled: bool):
        """L'autre vue a basculé l'interrupteur : on s'aligne sans réémettre."""
        if self._enabled_switch.isChecked() != enabled:
            self._enabled_switch.blockSignals(True)
            self._enabled_switch.setChecked(enabled)
            self._enabled_switch.blockSignals(False)
            self._enabled_switch.update()
            self._refresh_current_step()

    def _on_enabled_toggled(self, checked: bool):
        self._state.set_setlist_enabled(checked)  # persiste + prévient l'autre vue
        self._save_setlist_settings()
        self._refresh_current_step()
        if checked:
            # Resynchronise immédiatement le device sur l'étape courante qu'on vient de réactiver
            step = self._player.current_step()
            if step is not None:
                self._sender.set_preset(step.preset)
                self._state.on_preset_changed(step.preset)

    # --- Raccourcis clavier (cf shortcuts/router.py) ---

    def is_navigation_active(self) -> bool:
        """True si suivant/précédent doivent piloter la setlist : interrupteur sur "Active" ET une séquence
        avec au moins une étape sélectionnée."""
        return self._enabled_switch.isChecked() and self._player.current_step() is not None

    def navigate(self, direction: int):
        if direction > 0:
            self._player.next_step()
        else:
            self._player.previous_step()

    # --- Rafraîchissement UI ---

    def _fill_combo(self):
        self._sequence_combo.blockSignals(True)
        self._sequence_combo.clear()
        self._sequence_combo.addItem("(aucune séquence)")
        for seq in self._player.sequences:
            self._sequence_combo.addItem(seq.name)
        self._sequence_combo.setCurrentIndex(
            self._player.active_index + 1 if self._player.active_index is not None else 0)
        self._sequence_combo.blockSignals(False)

    def _refresh_all(self):
        self._fill_combo()
        seq = self._player.active_sequence
        self._delete_btn.setEnabled(seq is not None)
        self._name_edit.setEnabled(seq is not None)
        self._add_step_btn.setEnabled(seq is not None)
        if not self._name_edit.hasFocus():
            self._name_edit.setText(seq.name if seq else "")
        self._refresh_steps()
        self._refresh_current_step()
        self._update_title()

    def _refresh_current_step(self):
        seq = self._player.active_sequence
        enabled = self._enabled_switch.isChecked()
        if seq is None:
            msg = "Aucune séquence.\nChoisis-en une, ou crée-la avec le crayon ✎."
        elif not seq.steps:
            msg = f"« {seq.name} » est vide.\nAjoute des étapes avec le crayon ✎."
        else:
            msg = ""
        steps = seq.steps if seq is not None else []
        self._steps_view.set_data(steps, self._player.step_index if steps else 0, enabled, msg)
        has_steps = bool(steps)
        self._prev_btn.setEnabled(has_steps)
        self._next_btn.setEnabled(has_steps)

    def _refresh_steps(self):
        """Reconstruit les lignes de l'éditeur."""
        while self._rows.count() > 1:   # garde le stretch final
            item = self._rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        seq = self._player.active_sequence
        if seq is None:
            return
        for i, step in enumerate(seq.steps):
            row = StepRow(i, step, len(seq.steps), i == self._player.step_index)
            row.preset_edited.connect(self._on_step_preset_edited)
            row.label_edited.connect(self._on_step_label_edited)
            row.move_requested.connect(self._on_move_step)
            row.delete_requested.connect(self._on_delete_step)
            self._rows.insertWidget(self._rows.count() - 1, row)