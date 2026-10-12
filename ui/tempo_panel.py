"""
Module Tempo : le tempo, la signature et le métronome, partagés par la loop station et la batterie
(cf state/transport_state.py). Changer le BPM ici le change partout, et DeviceSync l'envoie à
la batterie du Mighty.

Le BPM s'affiche en grand, se règle au curseur (40–240, pas de 1) et avec les boutons − / + (appui
maintenu = répétition, Maj = pas de 5). La mesure se choisit d'un clic (4/4, 6/8, 12/8, 3/4) ou via le
bouton « ⋯ » pour une signature quelconque. Le calage de la batterie et son avance au démarrage sont
dans l'engrenage.

Le module s'adapte à sa taille (`adaptive`, cf ui/dashboard/dock_widget.py) : en tout petit il ne montre
que le BPM et son curseur ; avec plus de place s'ajoutent la mesure, puis le métronome et le tap, puis les
voyants de temps.

Il lit la position dans la mesure sur le moteur du looper (attach_loop_panel). Tempo et mesure sont
verrouillés tant qu'une boucle existe : elle est calée dessus.
"""

import time

from PySide6.QtCore import Qt, QPoint, QSize, QTimer
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QFrame, QLabel, QSizePolicy
from qfluentwidgets import (BodyLabel, CaptionLabel, StrongBodyLabel, SwitchButton, ToolButton,
                            TransparentToolButton, FluentIcon, isDarkTheme, qconfig)

from state.transport_state import TransportState, UNITS
from ui import looper_widgets as lw
from ui.module_card import MODULE_COLORS, ModuleCard
from ui.popup_utils import show_popup_under
from ui.widgets import NoWheelSpinBox, NoWheelComboBox, NoWheelSlider

TAP_RESET_S = 2.5   # au-delà, le prochain appui repart de zéro
TAP_WINDOW = 5      # nombre d'intervalles moyennés
BPM_MIN, BPM_MAX = 40, 240
SIGNATURES = [(4, 4), (6, 8), (12, 8), (3, 4)]   # boutons de choix rapide
ACCENT = "#F2C94C"                               # couleur du module (cf ui/dashboard_interface.py)
ON_ACCENT = "#1b1b1b"                            # texte posé sur l'accent
TAP_TIP = "Tape au rythme voulu (3 appuis ou plus) pour régler le tempo"


class TempoPanel(ModuleCard):
    adaptive = True

    def __init__(self, transport: TransportState, parent=None):
        super().__init__(parent, accent=MODULE_COLORS["tempo"])
        self.setTitle("Tempo")
        self._transport = transport
        self._engine = None
        self._taps: list[float] = []
        self._locked = False

        self._build_ui()
        self._build_settings_popup()
        self._refresh()
        transport.changed.connect(lambda _name: self._refresh())

        self._poll = QTimer(self)
        self._poll.setInterval(33)
        self._poll.timeout.connect(self._poll_engine)
        self._poll.start()

    def attach_loop_panel(self, loop_panel):
        """Branche le looper dont on lit la position (et qui verrouille le tempo)."""
        self._engine = loop_panel.engine

    # --- Construction ---

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(10)
        self.viewLayout.addLayout(layout)

        # BPM en grand + engrenage
        self._bpm_w = QWidget()
        top = QHBoxLayout(self._bpm_w)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        left_slot = QWidget()
        left_slot.setFixedWidth(46)   # contrepoids de la place du métronome réduit : le BPM reste centré
        top.addWidget(left_slot)
        top.addStretch()
        self._bpm_label = QLabel("120")
        self._bpm_label.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        font = self._bpm_label.font()
        font.setPixelSize(44)
        font.setWeight(font.Weight.Bold)
        self._bpm_label.setFont(font)
        self._bpm_label.setMinimumWidth(96)
        self._restyle_bpm_label()
        qconfig.themeChanged.connect(lambda *_: self._restyle_bpm_label())
        top.addWidget(self._bpm_label)
        unit = CaptionLabel("BPM")
        unit.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        unit.setContentsMargins(0, 0, 0, 8)
        top.addWidget(unit)
        top.addStretch()
        mini_slot = QWidget()
        mini_slot.setFixedWidth(46)
        mini_lay = QHBoxLayout(mini_slot)
        mini_lay.setContentsMargins(0, 0, 0, 0)
        # Métronome réduit à son icône, calé à droite du BPM : remplace le gros bouton quand le module
        # est trop petit pour la rangée Métronome / Tap (cf resizeEvent)
        self._click_mini = lw.PillButton("", ACCENT, kind="metronome", checkable=True, on_text=ON_ACCENT)
        self._click_mini.setFixedSize(46, 34)
        self._click_mini.setToolTip("Métronome audible dans la sortie du looper")
        self._click_mini.toggled.connect(lambda c: self._transport.set(click=c))
        mini_lay.addWidget(self._click_mini, alignment=Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(mini_slot)
        self._click_mini.hide()
        self._gear_btn = TransparentToolButton(FluentIcon.SETTING)
        self._gear_btn.setToolTip("Réglages de la batterie")
        self._gear_btn.clicked.connect(self._toggle_settings)
        self.add_header_action(self._gear_btn)   # l'engrenage vit dans l'en-tête du module
        layout.addWidget(self._bpm_w)

        # Voyants de temps : sous le BPM, centrés, toujours visibles
        self._dots = lw.BeatDots()
        layout.addWidget(self._dots, alignment=Qt.AlignHCenter)

        # Curseur − [——o——] +
        self._slider_w = QWidget()
        srow = QHBoxLayout(self._slider_w)
        srow.setContentsMargins(0, 0, 0, 0)
        srow.setSpacing(8)
        self._minus_btn = self._step_button(FluentIcon.REMOVE, -1)
        self._bpm_slider = NoWheelSlider(Qt.Horizontal)
        self._bpm_slider.setRange(BPM_MIN, BPM_MAX)
        self._bpm_slider.setSingleStep(1)
        self._bpm_slider.setPageStep(5)
        self._bpm_slider.valueChanged.connect(lambda v: self._transport.set(bpm=v))
        self._plus_btn = self._step_button(FluentIcon.ADD, +1)
        srow.addWidget(self._minus_btn)
        srow.addWidget(self._bpm_slider, stretch=1)
        srow.addWidget(self._plus_btn)
        layout.addWidget(self._slider_w)

        # Mesure : 4 choix rapides + « ⋯ »
        self._sig_w = QWidget()
        sig = QHBoxLayout(self._sig_w)
        sig.setContentsMargins(0, 0, 0, 0)
        sig.setSpacing(6)
        self._sig_buttons: dict[tuple[int, int], lw.ChoiceButton] = {}
        for beats, unit_ in SIGNATURES:
            btn = lw.ChoiceButton(f"{beats}/{unit_}", ACCENT, ON_ACCENT)
            btn.setToolTip(f"Mesure à {beats}/{unit_}")
            btn.clicked.connect(lambda _c=False, b=beats, u=unit_: self._choose_signature(b, u))
            self._sig_buttons[(beats, unit_)] = btn
            sig.addWidget(btn)
        self._sig_more = lw.ChoiceButton("⋯", ACCENT, ON_ACCENT)
        self._sig_more.setToolTip("Autre mesure…")
        self._sig_more.setMinimumWidth(44)
        self._sig_more.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self._sig_more.clicked.connect(self._toggle_custom_signature)
        sig.addWidget(self._sig_more)
        layout.addWidget(self._sig_w)

        # Métronome + tap
        self._actions_w = QWidget()
        act = QHBoxLayout(self._actions_w)
        act.setContentsMargins(0, 0, 0, 0)
        act.setSpacing(8)
        self._click_switch = lw.PillButton("Métronome", ACCENT, kind="metronome", checkable=True, on_text=ON_ACCENT)
        self._click_switch.setMinimumHeight(42)
        self._click_switch.setToolTip("Métronome audible dans la sortie du looper")
        self._click_switch.toggled.connect(lambda c: self._transport.set(click=c))
        self._tap_btn = lw.PillButton("TAP", ACCENT, kind="tap", on_text=ON_ACCENT)
        self._tap_btn.setMinimumHeight(42)
        self._tap_btn.setToolTip(TAP_TIP)
        self._tap_btn.clicked.connect(self._on_tap)
        act.addWidget(self._click_switch, stretch=3)
        act.addWidget(self._tap_btn, stretch=2)
        layout.addWidget(self._actions_w)

        layout.addStretch()

        self._build_custom_popup()

    def _choose_signature(self, beats: int, unit: int):
        self._transport.set(beats=beats, unit=unit)
        self._refresh()   # recliquer sur le choix actuel ne doit pas le décocher

    def _step_button(self, icon, direction: int) -> ToolButton:
        btn = ToolButton(icon)
        btn.setFixedSize(34, 34)
        btn.setAutoRepeat(True)
        btn.setAutoRepeatDelay(400)
        btn.setAutoRepeatInterval(70)
        btn.setToolTip("−1 BPM (Maj : −5)" if direction < 0 else "+1 BPM (Maj : +5)")
        btn.clicked.connect(lambda _c=False, d=direction: self._nudge(d))
        return btn

    def _nudge(self, direction: int):
        step = 5 if QApplication.keyboardModifiers() & Qt.ShiftModifier else 1
        self._transport.set(bpm=max(BPM_MIN, min(BPM_MAX, self._transport.bpm + direction * step)))

    def _restyle_bpm_label(self):
        self._bpm_label.setStyleSheet(f"color: {'#f5f5f5' if isDarkTheme() else '#1f1f1f'};")

    def _popup_frame(self, name: str) -> QFrame:
        popup = QFrame(self, Qt.Popup)
        popup.setObjectName(name)
        popup.setStyleSheet(
            f"#{name} {{ background: palette(window); border: 1px solid rgba(128,128,128,0.45);"
            " border-radius: 8px; }")
        return popup

    def _build_custom_popup(self):
        """Mesure quelconque : nombre de temps / valeur de la note."""
        popup = self._popup_frame("TempoCustomPopup")
        v = QVBoxLayout(popup)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)
        v.addWidget(StrongBodyLabel("Mesure personnalisée"))
        row = QHBoxLayout()
        self._beats_spin = NoWheelSpinBox()
        self._beats_spin.setRange(1, 16)
        self._beats_spin.valueChanged.connect(lambda v_: self._transport.set(beats=v_))
        row.addWidget(self._beats_spin)
        row.addWidget(BodyLabel("/"))
        self._unit_combo = NoWheelComboBox()
        for unit_ in UNITS:
            self._unit_combo.addItem(str(unit_))
        self._unit_combo.currentIndexChanged.connect(
            lambda i: self._transport.set(unit=UNITS[i]) if i >= 0 else None)
        row.addWidget(self._unit_combo)
        v.addLayout(row)
        self._custom_popup = popup

    def _build_settings_popup(self):
        """Réglages de la batterie, ouverts par l'engrenage."""
        popup = self._popup_frame("TempoSettingsPopup")
        v = QVBoxLayout(popup)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(8)
        v.addWidget(StrongBodyLabel("Batterie"))
        form = QFormLayout()
        form.setSpacing(8)
        self._sync_drums_switch = SwitchButton()
        self._sync_drums_switch.setOnText("Oui")
        self._sync_drums_switch.setOffText("Non")
        self._sync_drums_switch.setToolTip("La batterie démarre au début de la mesure et reçoit ce tempo")
        self._sync_drums_switch.checkedChanged.connect(lambda c: self._transport.set(sync_drums=c))
        form.addRow("Caler la batterie", self._sync_drums_switch)
        self._drum_latency_spin = NoWheelSpinBox()
        self._drum_latency_spin.setRange(0, 500)
        self._drum_latency_spin.setSuffix(" ms")
        self._drum_latency_spin.setToolTip(
            "Temps entre l'ordre MIDI et le premier coup de la batterie. Si elle démarre en retard sur la "
            "mesure, augmente.")
        self._drum_latency_spin.valueChanged.connect(lambda v_: self._transport.set(drum_latency_ms=v_))
        form.addRow("Avance démarrage batterie", self._drum_latency_spin)
        v.addLayout(form)
        self._settings_popup = popup

    def _show_popup_under(self, popup: QFrame, anchor: QWidget, align_right: bool):
        show_popup_under(popup, anchor, align_right)

    def _toggle_settings(self):
        self._show_popup_under(self._settings_popup, self._gear_btn, True)

    def _toggle_custom_signature(self):
        self._refresh()   # le bouton reflète toujours la mesure courante, pas son propre état coché
        if self._locked:
            return
        self._show_popup_under(self._custom_popup, self._sig_more, False)

    # --- Réglages ---

    def _refresh(self):
        t = self._transport
        for widget, value in ((self._bpm_slider, t.bpm), (self._beats_spin, t.beats),
                              (self._drum_latency_spin, t.drum_latency_ms)):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        self._bpm_label.setText(str(t.bpm))
        self._unit_combo.blockSignals(True)
        self._unit_combo.setCurrentIndex(UNITS.index(t.unit))
        self._unit_combo.blockSignals(False)
        for switch, value in ((self._click_switch, t.click), (self._click_mini, t.click),
                              (self._sync_drums_switch, t.sync_drums)):
            switch.blockSignals(True)
            switch.setChecked(value)
            switch.blockSignals(False)

        current = (t.beats, t.unit)
        for sig, btn in self._sig_buttons.items():
            btn.setChecked(sig == current)
        custom = current not in self._sig_buttons
        self._sig_more.setChecked(custom)
        self._sig_more.setText(f"{t.beats}/{t.unit}" if custom else "⋯")

    def _on_tap(self):
        now = time.monotonic()
        if self._taps and now - self._taps[-1] > TAP_RESET_S:
            self._taps = []
        self._taps.append(now)
        self._taps = self._taps[-(TAP_WINDOW + 1):]
        if len(self._taps) >= 3:
            intervals = [b - a for a, b in zip(self._taps, self._taps[1:])]
            self._transport.set(bpm=max(BPM_MIN, min(BPM_MAX, round(60.0 / (sum(intervals) / len(intervals))))))

    # --- Lecture du moteur : voyants + verrouillage ---

    def _poll_engine(self):
        if not self.isVisible():
            return
        engine = self._engine
        if engine is None:
            return
        snap = engine.snapshot()
        self._dots.set_state(snap["beats"], snap["beat"], snap["active"], snap.get("beat_frac", 0.0))
        swing = 0 if snap["beat"] < 0 or not snap["active"] else (1 if snap["beat"] % 2 == 0 else -1)
        self._click_switch.set_swing(swing)
        self._click_mini.set_swing(swing)
        locked = engine.grid_locked
        if locked != self._locked:
            self._locked = locked
            tip = "Efface la boucle pour changer le tempo / la mesure." if locked else ""
            for widget in (self._bpm_slider, self._minus_btn, self._plus_btn, self._sig_more, self._tap_btn,
                           *self._sig_buttons.values()):
                widget.setEnabled(not locked)
            for widget in (self._bpm_slider, self._minus_btn, self._plus_btn, self._sig_w):
                widget.setToolTip(tip)
            self._tap_btn.setToolTip(tip or TAP_TIP)
            self._beats_spin.setEnabled(not locked)
            self._unit_combo.setEnabled(not locked)
            if locked:
                self._custom_popup.hide()
            self._minus_btn.setToolTip("" if locked else "−1 BPM (Maj : −5)")
            self._plus_btn.setToolTip("" if locked else "+1 BPM (Maj : +5)")

    # --- Densité ---

    def _row_h(self, widget: QWidget) -> int:
        return widget.sizeHint().height() + 10

    def _base_height(self) -> int:
        return (self.chrome_height() + 4 + self._bpm_w.sizeHint().height() + self._dots.sizeHint().height() + 10
                + self._row_h(self._slider_w))

    def minimumSizeHint(self) -> QSize:
        return QSize(230, self._base_height())

    def sizeHint(self) -> QSize:
        return QSize(420, self._base_height() + self._row_h(self._sig_w) + self._row_h(self._actions_w)
                     )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        room = self.height() - self._base_height()
        sig_h = self._row_h(self._sig_w)
        act_h = self._row_h(self._actions_w)
        show_actions = room >= sig_h + act_h
        self._sig_w.setVisible(room >= sig_h)
        self._actions_w.setVisible(show_actions)
        self._click_mini.setVisible(not show_actions)   # trop petit : le métronome se réduit à son icône