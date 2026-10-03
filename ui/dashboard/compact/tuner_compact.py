"""
Version compacte du tuner, pour le dashboard (coexiste avec
ui/tuner_panel.py, gardé intact pour l'onglet Classique — cf discussion).

Va à l'essentiel pour tenir dans un petit module : note + jauge de cents
toujours visibles, le choix du mode (rarement changé en live) passe dans un
menu icône plutôt qu'un ComboBox pleine largeur, la calibration reste un
bouton icône (utile juste avant de jouer, pas assez secondaire pour la
cacher). Même AmpState/MidiSender que la version complète, et même fichier
de calibration (ui/tuner_panel.load_tuner_offset/save_tuner_offset) — les
deux vues restent cohérentes entre elles.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy
from qfluentwidgets import (
    TransparentToggleToolButton, TransparentToolButton, TransparentDropDownToolButton,
    RoundMenu, Action, FluentIcon, BodyLabel,
)

from state.amp_state import AmpState
from midi.sender import MidiSender
from midi.protocol import note_name, TUNER_REF_PITCH_440HZ
from ui.tuner_panel import TUNER_MODES, load_tuner_offset, save_tuner_offset

ICON_SIZE = 20


class _CompactCentsGauge(QWidget):
    """Jauge minimaliste : la valeur en cents est dessinée dans le widget
    lui-même (pas de label séparé), pour économiser de la hauteur."""

    TOLERANCE_CENTS = 5
    DISPLAY_RANGE = 50

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(24)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._cents = 0
        self._active = False

    def set_cents(self, cents: int, active: bool):
        self._cents = max(-self.DISPLAY_RANGE, min(self.DISPLAY_RANGE, cents))
        self._active = active
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        mid_y = h - 6

        painter.setPen(QPen(QColor("#888888"), 1))
        painter.drawLine(4, mid_y, w - 4, mid_y)
        painter.setPen(QPen(QColor("#aaaaaa"), 1))
        painter.drawLine(w // 2, mid_y - 5, w // 2, mid_y + 5)

        if self._active:
            ratio = self._cents / self.DISPLAY_RANGE
            x = int(w / 2 + ratio * (w / 2 - 8))
            in_tune = abs(self._cents) <= self.TOLERANCE_CENTS
            color = QColor("#2ecc71") if in_tune else QColor("#e67e22")
            painter.setPen(QPen(color, 3))
            painter.drawLine(x, mid_y - 9, x, mid_y + 9)

            painter.setPen(QColor("#cccccc"))
            small_font = QFont(painter.font().family(), 7)
            painter.setFont(small_font)
            sign = "+" if self._cents > 0 else ""
            painter.drawText(0, 0, w, 12, Qt.AlignHCenter | Qt.AlignTop, f"{sign}{self._cents}")
        painter.end()


class CompactTunerPanel(QWidget):
    def __init__(self, state: AmpState, sender: MidiSender, parent=None):
        super().__init__(parent)
        self._state = state
        self._sender = sender
        self._cent_offset = load_tuner_offset()
        self.setMinimumSize(150, 64)

        self._build_ui()
        self._state.tuner_updated.connect(self._refresh)
        self._refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 2)
        layout.setSpacing(2)

        top_row = QHBoxLayout()
        top_row.setSpacing(2)

        self._toggle_btn = TransparentToggleToolButton(FluentIcon.MICROPHONE, self)
        self._toggle_btn.setFixedSize(ICON_SIZE + 6, ICON_SIZE + 6)
        self._toggle_btn.setToolTip("Activer/couper le tuner")
        self._toggle_btn.toggled.connect(self._on_toggle)
        top_row.addWidget(self._toggle_btn)

        note_font = QFont()
        note_font.setPointSize(note_font.pointSize() + 6)
        note_font.setBold(True)
        self._note_label = BodyLabel("--")
        self._note_label.setFont(note_font)
        self._note_label.setAlignment(Qt.AlignCenter)
        top_row.addWidget(self._note_label, stretch=1)

        self._mode_btn = TransparentDropDownToolButton(FluentIcon.SETTING, self)
        self._mode_btn.setFixedSize(ICON_SIZE + 6, ICON_SIZE + 6)
        self._mode_btn.setToolTip("Mode du tuner")
        self._build_mode_menu()
        top_row.addWidget(self._mode_btn)

        self._calibrate_btn = TransparentToolButton(FluentIcon.FLAG, self)
        self._calibrate_btn.setFixedSize(ICON_SIZE + 6, ICON_SIZE + 6)
        self._calibrate_btn.setToolTip("Définir comme référence (0 cent)")
        self._calibrate_btn.clicked.connect(self._on_calibrate)
        top_row.addWidget(self._calibrate_btn)

        layout.addLayout(top_row)

        self._gauge = _CompactCentsGauge(self)
        layout.addWidget(self._gauge)

    def _build_mode_menu(self):
        menu = RoundMenu(parent=self)
        for label, value in TUNER_MODES:
            action = Action(label)
            action.triggered.connect(lambda checked=False, v=value: self._on_mode_selected(v))
            menu.addAction(action)
        self._mode_btn.setMenu(menu)

    # --- Actions utilisateur ---

    def _on_toggle(self, checked: bool):
        mode = self._state.tuner_mode
        self._sender.tuner_enable(on=checked, mode=mode, ref_pitch=TUNER_REF_PITCH_440HZ)
        self._state.set_tuner_requested(checked)

    def _on_mode_selected(self, mode: int):
        self._state.set_tuner_mode(mode)
        if self._toggle_btn.isChecked():
            self._sender.tuner_enable(on=True, mode=mode, ref_pitch=TUNER_REF_PITCH_440HZ)

    def _on_calibrate(self):
        self._cent_offset = self._state.tuner_cent
        save_tuner_offset(self._cent_offset)
        self._refresh()

    # --- Réaction à l'état ---

    def _refresh(self):
        active = self._state.tuner_requested
        self._toggle_btn.blockSignals(True)
        self._toggle_btn.setChecked(active)
        self._toggle_btn.blockSignals(False)

        if not active:
            self._note_label.setText("--")
            self._gauge.set_cents(0, active=False)
            return

        self._note_label.setText(note_name(self._state.tuner_note))
        relative_cents = self._state.tuner_cent - self._cent_offset
        self._gauge.set_cents(relative_cents, active=True)
