"""
Panneau batterie d'accompagnement + EQ.

Tout passe en CC direct, pas de SysEx (cf docs/protocol_notes.md). Comme
pour les presets (bug déjà corrigé) et le tuner, on ne peut pas compter sur
un écho fiable du device après une commande envoyée depuis l'host : chaque
action appelle donc un setter dédié sur AmpState en plus d'envoyer le CC,
pour ne pas reproduire le bug de sélection qu'on a eu sur les presets.

Le nombre et les noms des styles de batterie ne sont pas documentés
empiriquement (CC_DRUMTYPE accepte une valeur brute, plage réelle inconnue) :
exposé ici comme un simple SpinBox à tester au fur et à mesure, comme les
presets avant renommage. Le tempo (SysEx différent, non testé) n'est pas
inclus dans ce panneau.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFormLayout
from qfluentwidgets import HeaderCardWidget, SwitchButton, BodyLabel

from state.amp_state import AmpState
from midi.sender import MidiSender
from ui.widgets import NoWheelSpinBox, NoWheelSlider


class DrumPanel(HeaderCardWidget):
    def __init__(self, state: AmpState, sender: MidiSender, parent=None):
        super().__init__(parent)
        self.setTitle("Batterie d'accompagnement")

        self._state = state
        self._sender = sender

        self._build_ui()

        self._state.drum_updated.connect(self._refresh)
        self._refresh()

    def _build_ui(self):
        layout = QVBoxLayout()
        self.viewLayout.addLayout(layout)

        top_row = QHBoxLayout()
        self._switch = SwitchButton()
        self._switch.setOnText("Actif")
        self._switch.setOffText("Coupé")
        self._switch.checkedChanged.connect(self._on_enable_toggled)
        top_row.addWidget(self._switch)
        top_row.addStretch()
        layout.addLayout(top_row)

        form = QFormLayout()
        form.setSpacing(10)

        self._style_spin = NoWheelSpinBox()
        self._style_spin.setRange(1, 67)  # 67 styles confirmés ; CC brut = valeur affichée - 1
        self._style_spin.valueChanged.connect(self._on_style_changed)
        form.addRow("Style", self._style_spin)

        self._level_slider, self._level_label = self._make_slider()
        self._level_slider.valueChanged.connect(self._on_level_changed)
        form.addRow("Volume", self._wrap_slider(self._level_slider, self._level_label))

        self._bass_slider, self._bass_label = self._make_slider()
        self._bass_slider.valueChanged.connect(self._on_eq_changed)
        form.addRow("Grave", self._wrap_slider(self._bass_slider, self._bass_label))

        self._middle_slider, self._middle_label = self._make_slider()
        self._middle_slider.valueChanged.connect(self._on_eq_changed)
        form.addRow("Médium", self._wrap_slider(self._middle_slider, self._middle_label))

        self._treble_slider, self._treble_label = self._make_slider()
        self._treble_slider.valueChanged.connect(self._on_eq_changed)
        form.addRow("Aigu", self._wrap_slider(self._treble_slider, self._treble_label))

        layout.addLayout(form)

    @staticmethod
    def _make_slider():
        slider = NoWheelSlider(Qt.Horizontal)
        slider.setRange(0, 127)
        label = BodyLabel("0")
        slider.valueChanged.connect(lambda v: label.setText(str(v)))
        return slider, label

    @staticmethod
    def _wrap_slider(slider, label) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(slider)
        row_layout.addWidget(label)
        return row

    # --- Actions utilisateur : on envoie ET on met à jour AmpState nous-mêmes ---
    # (pas d'écho garanti pour une commande host, même logique que le fix presets)

    def _on_enable_toggled(self, checked: bool):
        self._sender.drum_enable(checked)
        self._state.set_drum_enabled(checked)

    def _on_style_changed(self, displayed_value: int):
        raw = displayed_value - 1  # affiché 1-67, CC brut 0-66
        self._sender.drum_set_style(raw)
        self._state.set_drum_style(raw)

    def _on_level_changed(self, value: int):
        self._sender.drum_set_level(value)
        self._state.set_drum_level(value)

    def _on_eq_changed(self, _value: int):
        # Les 3 curseurs EQ partagent ce handler : MidiSender.drum_set_eq
        # envoie toujours les 3 valeurs courantes ensemble
        bass = self._bass_slider.value()
        middle = self._middle_slider.value()
        treble = self._treble_slider.value()
        self._sender.drum_set_eq(bass, middle, treble)
        self._state.set_drum_eq(bass, middle, treble)

    # --- Réaction à l'état (couvre aussi les changements physiques éventuels) ---

    def _refresh(self):
        self._switch.blockSignals(True)
        self._switch.setChecked(self._state.drum_enabled)
        self._switch.blockSignals(False)

        self._style_spin.blockSignals(True)
        self._style_spin.setValue(self._state.drum_style + 1)  # CC brut -> affiché 1-67
        self._style_spin.blockSignals(False)

        for widget, label, value in (
            (self._level_slider, self._level_label, self._state.drum_level),
            (self._bass_slider, self._bass_label, self._state.drum_bass),
            (self._middle_slider, self._middle_label, self._state.drum_middle),
            (self._treble_slider, self._treble_label, self._state.drum_treble),
        ):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
            label.setText(str(value))