"""
Module Tuner (unique : plus de version compacte séparée).

- Cadran en arc (♭ … ♯) avec l'aiguille, la note détectée en énorme au centre et l'écart en cents dessous.
- Rangée des 6 cordes de l'accordage choisi, toujours visible. Aucune corde choisie = détection automatique
  (la corde reconnue s'allume) ; cliquer une corde la vise à la main, recliquer revient en auto.
  Une corde accordée (±3 cents tenus un instant) s'entoure de vert, est cochée, et un petit tintement joue.
- Accordage : Standard / Eb standard / Drop D en direct, « … » pour la liste complète (midi/tunings.py).
- Bouton diapason (en-tête) : active l'accordeur ; engrenage : référence (Hz), son, calibration de l'écart.

L'ampli reste toujours en mode chromatique : c'est l'appli (state/tuner_session.py) qui compare ce que dit
l'ampli à la note cible de chaque corde.

Pas de confirmation matérielle fiable pour l'activation (CC 11 reflète plutôt la détection d'un signal) :
l'interrupteur reflète `AmpState.tuner_requested`, mis à jour au clic.
"""

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QScrollArea, QSizePolicy, QVBoxLayout, QWidget)
from qfluentwidgets import FluentIcon, PushButton, StrongBodyLabel, SwitchButton, TransparentToolButton, CaptionLabel

from midi import protocol, tunings
from midi.sender import MidiSender
from state.amp_state import AmpState
from ui import looper_widgets as lw
from ui.module_card import MODULE_COLORS, ModuleCard
from ui.popup_utils import show_popup_under
from ui.power_pill import text_color
from ui.tuner_widgets import ForkToggle, StringChip, TunerGauge, _font, _faint
from ui.widgets import NoWheelSpinBox

ACCENT = MODULE_COLORS["tuner"]
ON_ACCENT = "#1b1b1b"
GAP = 8
CHIP_H = 40
ROW_H = 34


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class TuningItem(QAbstractButton):
    """Un accordage dans la liste « … » : nom et notes."""

    def __init__(self, name: str, current: bool, parent=None):
        super().__init__(parent)
        self.name, self._current = name, current
        self.setFixedHeight(46)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self._current:
            fill = QColor(ACCENT); fill.setAlpha(60); p.setPen(QPen(QColor(ACCENT), 1.3)); p.setBrush(fill)
        elif self.underMouse():
            p.setPen(Qt.NoPen); p.setBrush(_faint(24))
        else:
            p.setPen(Qt.NoPen); p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 8, 8)
        p.setPen(text_color()); p.setFont(_font(14, True))
        p.drawText(QRectF(10, 3, r.width() - 14, 22), Qt.AlignVCenter | Qt.AlignLeft, self.name)
        p.setPen(_faint(160)); p.setFont(_font(12))
        p.drawText(QRectF(10, 24, r.width() - 14, 18), Qt.AlignVCenter | Qt.AlignLeft,
                   "  ".join(tunings.TUNINGS[self.name].split()))
        p.end()


class TunerPanel(ModuleCard):
    adaptive = True

    def __init__(self, state: AmpState, sender: MidiSender, parent=None):
        super().__init__(parent, accent=ACCENT)
        self.setTitle("Tuner")
        self._state = state
        self._sender = sender
        self._session = state.tuner

        self._build_ui()
        self._build_settings_popup()
        self._build_tuning_popup()

        state.tuner_updated.connect(self._refresh)
        self._session.updated.connect(self._refresh)
        self._refresh()

    # --- Construction ---

    def _build_ui(self):
        self._power = ForkToggle(ACCENT)
        self._power.toggled.connect(self._on_toggle)
        self.headerLayout.addWidget(self._power)
        self._gear_btn = TransparentToolButton(FluentIcon.SETTING)
        self._gear_btn.setToolTip("Réglages de l'accordeur")
        self._gear_btn.clicked.connect(lambda: show_popup_under(self._settings_popup, self._gear_btn, True))
        self.add_header_action(self._gear_btn)

        layout = QVBoxLayout()
        layout.setSpacing(GAP)
        self.viewLayout.addLayout(layout)

        self._gauge = TunerGauge(ACCENT)
        layout.addWidget(self._gauge, stretch=1)

        self._chips_w = QWidget()
        row = QHBoxLayout(self._chips_w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self._chips: list[StringChip] = []
        for i, s in enumerate(tunings.strings_of(self._state.tuner_tuning)):
            chip = StringChip(i, s.label, s.number, ACCENT)
            chip.setFixedHeight(CHIP_H)
            chip.clicked.connect(lambda _c=False, idx=i: self._session.select(idx))
            self._chips.append(chip)
            row.addWidget(chip)
        layout.addWidget(self._chips_w)

        self._tuning_w = QWidget()
        trow = QHBoxLayout(self._tuning_w)
        trow.setContentsMargins(0, 0, 0, 0)
        trow.setSpacing(6)
        self._tuning_buttons: dict[str, lw.ChoiceButton] = {}
        for name in tunings.QUICK:
            btn = lw.ChoiceButton(name, ACCENT, ON_ACCENT)
            btn.setToolTip("  ".join(tunings.TUNINGS[name].split()))
            btn.clicked.connect(lambda _c=False, n=name: self._choose_tuning(n))
            self._tuning_buttons[name] = btn
            trow.addWidget(btn)
        self._more_btn = lw.ChoiceButton("⋯", ACCENT, ON_ACCENT)
        self._more_btn.setToolTip("Autres accordages…")
        self._more_btn.setMinimumWidth(44)
        self._more_btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self._more_btn.clicked.connect(self._open_tunings)
        trow.addWidget(self._more_btn)
        layout.addWidget(self._tuning_w)

    def _build_settings_popup(self):
        popup = QFrame(self, Qt.Popup)
        popup.setObjectName("TunerSettingsPopup")
        popup.setStyleSheet("#TunerSettingsPopup { background: palette(window); "
                            "border: 1px solid rgba(128,128,128,0.45); border-radius: 8px; }")
        v = QVBoxLayout(popup)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(8)
        v.addWidget(StrongBodyLabel("Accordeur"))
        form = QFormLayout()
        form.setSpacing(8)
        self._ref_spin = NoWheelSpinBox()
        self._ref_spin.setRange(protocol.TUNER_REF_HZ_MIN, protocol.TUNER_REF_HZ_MAX)
        self._ref_spin.setSuffix(" Hz")
        self._ref_spin.setToolTip("Fréquence du La de référence (440 Hz par défaut)")
        self._ref_spin.valueChanged.connect(self._on_ref_changed)
        form.addRow("Référence (La)", self._ref_spin)
        self._sound_switch = SwitchButton()
        self._sound_switch.setOnText("Oui")
        self._sound_switch.setOffText("Non")
        self._sound_switch.checkedChanged.connect(lambda c: self._state.set_tuner_options(sound=c))
        form.addRow("Son quand c'est accordé", self._sound_switch)
        v.addLayout(form)

        v.addWidget(StrongBodyLabel("Calibration de l'écart"))
        note = CaptionLabel("Joue une corde que tu sais juste (autre accordeur) puis « Zéro de cette note » : "
                            "l'ampli peut avoir un petit écart différent selon la note. L'échelle règle l'amplitude de l'aiguille.")
        note.setWordWrap(True)
        note.setMaximumWidth(320)
        v.addWidget(note)
        cal = QHBoxLayout()
        zero_btn = PushButton("Zéro de cette note")
        zero_btn.clicked.connect(self._on_set_zero)
        reset_btn = PushButton("Réinitialiser")
        reset_btn.clicked.connect(self._on_reset_calibration)
        cal.addWidget(zero_btn)
        cal.addWidget(reset_btn)
        v.addLayout(cal)
        form2 = QFormLayout()
        self._scale_spin = NoWheelDoubleSpinBox()
        self._scale_spin.setRange(0.2, 8.0)
        self._scale_spin.setSingleStep(0.1)
        self._scale_spin.setDecimals(1)
        self._scale_spin.setPrefix("× ")
        self._scale_spin.valueChanged.connect(lambda x: self._state.set_tuner_options(cent_scale=round(x, 1)))
        form2.addRow("Échelle", self._scale_spin)
        self._zero_label = QLabel("")
        form2.addRow("Zéro (brut)", self._zero_label)
        self._shift_spin = NoWheelSpinBox()
        self._shift_spin.setRange(-12, 12)
        self._shift_spin.setSuffix(" demi-tons")
        self._shift_spin.setToolTip("Correction fine de la note envoyée par l'ampli (normalement 0)")
        self._shift_spin.valueChanged.connect(lambda x: (self._state.set_tuner_options(note_shift=int(x)), self._session.reset()))
        form2.addRow("Décalage de note", self._shift_spin)
        v.addLayout(form2)
        v.addWidget(StrongBodyLabel("Valeurs brutes de l'ampli"))
        self._raw_label = QLabel("")
        self._raw_label.setStyleSheet("font-family: Consolas, monospace;")
        v.addWidget(self._raw_label)
        self._settings_popup = popup

    def _build_tuning_popup(self):
        popup = QFrame(self, Qt.Popup)
        popup.setObjectName("TunerTuningPopup")
        popup.setStyleSheet("#TunerTuningPopup { background: palette(window); "
                            "border: 1px solid rgba(128,128,128,0.45); border-radius: 10px; }")
        popup.setFixedWidth(420)
        v = QVBoxLayout(popup)
        v.setContentsMargins(10, 10, 10, 10)
        self._tuning_scroll = QScrollArea()
        self._tuning_scroll.setWidgetResizable(True)
        self._tuning_scroll.setFrameShape(QFrame.NoFrame)
        self._tuning_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._tuning_scroll.setFixedHeight(5 * 46 + 4 * 4 + 2)
        self._tuning_scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        v.addWidget(self._tuning_scroll)
        self._tuning_popup = popup

    def _open_tunings(self):
        self._refresh()   # le bouton « … » reflète toujours l'accordage courant
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        for i, name in enumerate(tunings.TUNINGS):
            item = TuningItem(name, name == self._state.tuner_tuning)
            item.clicked.connect(lambda _c=False, n=name: self._choose_tuning(n, close=True))
            grid.addWidget(item, i // 2, i % 2)
        grid.setRowStretch(len(tunings.TUNINGS) // 2 + 1, 1)
        self._tuning_scroll.setWidget(body)
        show_popup_under(self._tuning_popup, self._more_btn, True)

    # --- Actions ---

    def _on_toggle(self, checked: bool):
        self._sender.tuner_enable(on=checked, mode=0, ref_pitch=protocol.tuner_ref_byte(self._state.tuner_ref_hz))
        self._state.set_tuner_requested(checked)

    def _choose_tuning(self, name: str, close: bool = False):
        if close:
            self._tuning_popup.hide()
        self._session.set_tuning(name)
        self._refresh()

    def _on_ref_changed(self, hz: int):
        self._state.set_tuner_options(ref_hz=int(hz))
        if self._state.tuner_requested:   # l'ampli reçoit la nouvelle référence
            self._sender.tuner_enable(on=True, mode=0, ref_pitch=protocol.tuner_ref_byte(hz))

    def _on_set_zero(self):
        if not (self._state.tuner_requested and self._session.signal):
            return   # sans corde jouée, la valeur brute n'a aucun sens (ça mettait le zéro à 0)
        pc = protocol.tuner_pitch_class(self._state.tuner_note, self._state.tuner_note_shift)
        zeros = dict(self._state.tuner_cent_zero_notes)
        zeros[pc] = int(self._state.tuner_cent)   # propre à cette note : l'ampli n'a pas le même biais sur toutes
        self._state.set_tuner_options(cent_zero_notes=zeros)
        self._session.reset()

    def _on_reset_calibration(self):
        from state.amp_state import _legacy_cent_zero
        self._state.set_tuner_options(cent_zero=_legacy_cent_zero(), cent_scale=1.0, note_shift=0, cent_zero_notes={})
        self._session.reset()

    # --- État ---

    def _refresh(self):
        s, sess = self._state, self._session
        active = s.tuner_requested
        for widget, value in ((self._power, active), (self._ref_spin, s.tuner_ref_hz),
                              (self._sound_switch, s.tuner_sound), (self._scale_spin, s.tuner_cent_scale),
                              (self._shift_spin, s.tuner_note_shift)):
            widget.blockSignals(True)
            widget.setValue(value) if hasattr(widget, "setValue") else widget.setChecked(value)
            widget.blockSignals(False)
        self._power.update()
        self._sound_switch.update()
        self._zero_label.setText(f"{s.tuner_cent_zero}" + (f"  (+ {len(s.tuner_cent_zero_notes)} note(s) calibrée(s))"
                                                          if s.tuner_cent_zero_notes else ""))
        self._raw_label.setText(f"note CC12 = {s.tuner_note} → {tunings.SHARP_NAMES[protocol.tuner_pitch_class(s.tuner_note, s.tuner_note_shift)]}\n"
                                f"écart CC72 = {s.tuner_cent}\ncorde CC71 = {s.tuner_string}\n"
                                f"état  CC11 = {int(s.tuner_enabled)}")

        # accordage : boutons directs / « … »
        for name, btn in self._tuning_buttons.items():
            btn.setChecked(name == s.tuner_tuning)
        custom = s.tuner_tuning not in self._tuning_buttons
        self._more_btn.setChecked(custom)
        self._more_btn.setText(s.tuner_tuning if custom else "⋯")
        self._more_btn.setSizePolicy(QSizePolicy.Preferred if custom else QSizePolicy.Minimum, QSizePolicy.Fixed)
        strings = tunings.strings_of(s.tuner_tuning)
        for chip, gs in zip(self._chips, strings):
            chip.set_string(gs.label, gs.number)

        r = sess.reading if active else None
        signal = active and sess.signal and r is not None
        for chip in self._chips:
            i = chip.index
            on_it = signal and r.string == i
            chip.set_flags(auto=on_it and sess.selected is None, selected=sess.selected == i,
                           tuned=active and i in sess.tuned, live=bool(on_it and r.in_tune))
        if signal:
            self._gauge.set_reading(True, True, r.label, r.cents, r.in_tune)
        else:
            hint = "Joue une corde" if sess.selected is None else f"Joue la corde {strings[sess.selected].number}"
            self._gauge.set_reading(active, False, r.label if r else "—", r.cents if r else 0.0, False, hint)

    # --- Taille / densité ---

    GAUGE_MIN = 96

    def _base_height(self) -> int:
        return self.chrome_height() + 4 + self.GAUGE_MIN

    def minimumSizeHint(self) -> QSize:
        return QSize(230, self._base_height())

    def sizeHint(self) -> QSize:
        return QSize(380, self._base_height() + 100 + GAP + CHIP_H + GAP + ROW_H)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        room = self.height() - self._base_height()
        chips_h = GAP + CHIP_H
        tuning_h = GAP + ROW_H
        self._chips_w.setVisible(room >= chips_h + 30)
        self._tuning_w.setVisible(room >= chips_h + tuning_h + 50)