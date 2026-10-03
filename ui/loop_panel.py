"""
Panneau loop station PC.

100% logiciel (le Plug Pro n'a pas de looper hardware, cf docs/protocol_notes.md) :
le moteur audio (audio/loop_engine.py) est un pipeline par callback
sounddevice. Ce panneau ne connaît rien du MIDI ni d'AmpState — il pourrait
vivre dans une autre appli. Il partage uniquement settings.py (JSON unique)
pour se souvenir de ses réglages d'une session à l'autre.

Chaque prise (base + overdubs) est une piste séparée dans le moteur,
affichée ici sous forme de liste avec un bouton de suppression individuel.

Tous les SpinBox/Slider/ComboBox de ce panneau utilisent les variantes
NoWheel* (ui/widgets.py) : la molette ne doit pas changer une valeur par
erreur pendant qu'on scrolle la page.
"""

import sounddevice as sd
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QFrame
from qfluentwidgets import HeaderCardWidget, PushButton, BodyLabel, SwitchButton, TransparentToolButton, FluentIcon

from audio.loop_engine import LoopEngine
from settings import load_settings, update_settings
from ui.widgets import NoWheelSpinBox, NoWheelSlider, NoWheelComboBox

STATE_LABELS = {
    "idle": "Prêt",
    "counting_in": "Décompte...",
    "recording": "Enregistrement (1er tour)...",
    "playing": "Lecture en boucle",
    "overdubbing": "Overdub en cours...",
    "stopped": "Arrêté (nombre de répétitions atteint)",
}


class LoopPanel(HeaderCardWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Loop station PC")

        self._settings = load_settings()

        self._engine = LoopEngine()
        # QueuedConnection explicite : ces signaux peuvent être émis depuis le
        # thread callback de PortAudio, pas seulement depuis ce thread Qt.
        self._engine.state_changed.connect(self._on_state_changed, Qt.QueuedConnection)
        self._engine.loop_length_changed.connect(self._on_length_changed, Qt.QueuedConnection)
        self._engine.stream_error.connect(self._on_stream_error, Qt.QueuedConnection)
        self._engine.tracks_changed.connect(self._refresh_tracks, Qt.QueuedConnection)

        self._input_devices: list[tuple[int, str]] = []
        self._output_devices: list[tuple[int, str]] = []
        self._loop_seconds = 0.0
        self._audio_ok = True
        self._audio_lost = False        # flux coupé parce que l'interface audio a disparu
        self._restore_attempts = 0
        self._restore_generation = 0    # invalide les tentatives en attente quand l'état change

        self._build_ui()
        self._populate_devices()
        self._apply_remembered_loop_settings()
        self._start_engine()
        self._on_state_changed("idle")
        self._refresh_tracks()

    def _build_ui(self):
        layout = QVBoxLayout()
        self.viewLayout.addLayout(layout)

        device_row = QHBoxLayout()
        device_row.addWidget(BodyLabel("Entrée :"))
        self._input_combo = NoWheelComboBox()
        self._input_combo.currentIndexChanged.connect(self._on_device_changed)
        device_row.addWidget(self._input_combo)

        device_row.addWidget(BodyLabel("Sortie :"))
        self._output_combo = NoWheelComboBox()
        self._output_combo.currentIndexChanged.connect(self._on_device_changed)
        device_row.addWidget(self._output_combo)
        device_row.addStretch()
        layout.addLayout(device_row)

        form = QFormLayout()
        form.setSpacing(10)

        self._volume_slider = NoWheelSlider(Qt.Horizontal)
        self._volume_slider.setRange(0, 150)
        self._volume_label = BodyLabel("100%")
        self._volume_slider.valueChanged.connect(self._on_volume_changed)
        form.addRow("Volume du looper", self._wrap(self._volume_slider, self._volume_label))

        self._repeat_spin = NoWheelSpinBox()
        self._repeat_spin.setRange(0, 999)
        self._repeat_spin.setSpecialValueText("Infini")
        self._repeat_spin.valueChanged.connect(self._on_repeat_changed)
        form.addRow("Répétitions", self._repeat_spin)

        self._overdub_passes_spin = NoWheelSpinBox()
        self._overdub_passes_spin.setRange(0, 99)
        self._overdub_passes_spin.setSpecialValueText("Illimité")
        self._overdub_passes_spin.valueChanged.connect(self._on_overdub_passes_changed)
        form.addRow("Passes d'overdub avant arrêt auto", self._overdub_passes_spin)

        layout.addLayout(form)

        count_in_row = QHBoxLayout()
        self._count_in_switch = SwitchButton()
        self._count_in_switch.setOnText("Actif")
        self._count_in_switch.setOffText("Coupé")
        self._count_in_switch.checkedChanged.connect(self._on_count_in_toggled)
        count_in_row.addWidget(BodyLabel("Décompte avant 1er enregistrement :"))
        count_in_row.addWidget(self._count_in_switch)

        self._count_in_bpm_spin = NoWheelSpinBox()
        self._count_in_bpm_spin.setRange(40, 240)
        self._count_in_bpm_spin.setSuffix(" BPM")
        self._count_in_bpm_spin.valueChanged.connect(self._on_count_in_bpm_changed)
        count_in_row.addWidget(self._count_in_bpm_spin)
        count_in_row.addStretch()
        layout.addLayout(count_in_row)

        self._status_label = BodyLabel(STATE_LABELS["idle"])
        layout.addWidget(self._status_label)

        btn_row = QHBoxLayout()
        self._record_btn = PushButton("Enregistrer")
        self._record_btn.clicked.connect(self._on_record_clicked)
        btn_row.addWidget(self._record_btn)

        self._overdub_btn = PushButton("Overdub")
        self._overdub_btn.clicked.connect(self._on_overdub_clicked)
        btn_row.addWidget(self._overdub_btn)

        self._play_btn = PushButton("Rejouer")
        self._play_btn.clicked.connect(self._on_play_clicked)
        btn_row.addWidget(self._play_btn)

        self._clear_btn = PushButton("Tout effacer")
        self._clear_btn.clicked.connect(self._on_clear_clicked)
        btn_row.addWidget(self._clear_btn)

        layout.addLayout(btn_row)

        layout.addWidget(BodyLabel("Pistes :"))
        self._tracks_layout = QVBoxLayout()
        self._tracks_layout.setSpacing(4)
        layout.addLayout(self._tracks_layout)

    @staticmethod
    def _wrap(widget, label) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(widget)
        row_layout.addWidget(label)
        return row

    # --- Sélection des interfaces audio ---

    def _populate_devices(self):
        self._input_combo.blockSignals(True)
        self._output_combo.blockSignals(True)
        self._input_combo.clear()   # rappelé à la reconnexion : repart d'une liste vide
        self._output_combo.clear()
        try:
            devices = sd.query_devices()
            self._input_devices = [
                (i, d["name"]) for i, d in enumerate(devices) if d["max_input_channels"] > 0
            ]
            self._output_devices = [
                (i, d["name"]) for i, d in enumerate(devices) if d["max_output_channels"] > 0
            ]
        except Exception as exc:
            self._input_devices, self._output_devices = [], []
            self._on_stream_error(str(exc))

        for _, name in self._input_devices:
            self._input_combo.addItem(name)
        for _, name in self._output_devices:
            self._output_combo.addItem(name)

        self._select_remembered(
            self._input_combo, self._input_devices, self._settings["loop"]["input_device_name"]
        )
        self._select_remembered(
            self._output_combo, self._output_devices, self._settings["loop"]["output_device_name"]
        )

        self._input_combo.blockSignals(False)
        self._output_combo.blockSignals(False)

    @staticmethod
    def _select_remembered(combo, devices: list[tuple[int, str]], remembered_name):
        if not remembered_name:
            return
        for i, (_, name) in enumerate(devices):
            if name == remembered_name:
                combo.setCurrentIndex(i)
                return

    def _apply_remembered_loop_settings(self):
        s = self._settings["loop"]

        self._volume_slider.blockSignals(True)
        self._volume_slider.setValue(round(s["volume"] * 100))
        self._volume_slider.blockSignals(False)
        self._volume_label.setText(f"{self._volume_slider.value()}%")
        self._engine.set_volume(s["volume"])

        self._repeat_spin.blockSignals(True)
        self._repeat_spin.setValue(s["repeat_target"])
        self._repeat_spin.blockSignals(False)
        self._engine.set_repeat_target(s["repeat_target"])

        self._overdub_passes_spin.blockSignals(True)
        self._overdub_passes_spin.setValue(s["overdub_passes_target"])
        self._overdub_passes_spin.blockSignals(False)
        self._engine.set_overdub_passes_target(s["overdub_passes_target"])

        self._count_in_switch.blockSignals(True)
        self._count_in_switch.setChecked(s["count_in_enabled"])
        self._count_in_switch.blockSignals(False)

        self._count_in_bpm_spin.blockSignals(True)
        self._count_in_bpm_spin.setValue(s["count_in_bpm"])
        self._count_in_bpm_spin.blockSignals(False)

    def _selected_device(self, combo, devices: list[tuple[int, str]]):
        if not devices:
            return None
        idx = combo.currentIndex()
        return devices[idx if idx >= 0 else 0][0]

    def _start_engine(self):
        if not self._input_devices or not self._output_devices:
            self._on_stream_error("aucune entrée et/ou sortie audio détectée")
            return
        self._audio_ok = True
        self._engine.start(
            input_device=self._selected_device(self._input_combo, self._input_devices),
            output_device=self._selected_device(self._output_combo, self._output_devices),
        )

    def _save_loop_settings(self):
        def name_or_none(combo, devices):
            idx = combo.currentIndex()
            return devices[idx][1] if devices and idx >= 0 else None

        self._settings["loop"] = {
            "input_device_name": name_or_none(self._input_combo, self._input_devices),
            "output_device_name": name_or_none(self._output_combo, self._output_devices),
            "volume": self._volume_slider.value() / 100,
            "repeat_target": self._repeat_spin.value(),
            "overdub_passes_target": self._overdub_passes_spin.value(),
            "count_in_enabled": self._count_in_switch.isChecked(),
            "count_in_bpm": self._count_in_bpm_spin.value(),
        }
        update_settings({"loop": self._settings["loop"]})  # seulement notre section (cf settings.py)

    # --- Actions utilisateur : réglages ---

    def _on_device_changed(self, _index: int):
        self._start_engine()
        if self._audio_ok:
            self._on_state_changed(self._engine.state)
        self._save_loop_settings()

    def _on_volume_changed(self, value: int):
        self._volume_label.setText(f"{value}%")
        self._engine.set_volume(value / 100)
        self._save_loop_settings()

    def _on_repeat_changed(self, value: int):
        self._engine.set_repeat_target(value)
        self._save_loop_settings()

    def _on_overdub_passes_changed(self, value: int):
        self._engine.set_overdub_passes_target(value)
        self._save_loop_settings()

    def _on_count_in_toggled(self, _checked: bool):
        self._save_loop_settings()

    def _on_count_in_bpm_changed(self, _value: int):
        self._save_loop_settings()

    # --- Actions utilisateur : transport ---

    def _on_record_clicked(self):
        state = self._engine.state
        if state in ("idle", "stopped"):
            if self._count_in_switch.isChecked():
                self._engine.record_with_count_in(bpm=self._count_in_bpm_spin.value())
            else:
                self._engine.record()
        elif state == "recording":
            self._engine.stop_record()

    def _on_overdub_clicked(self):
        if self._engine.state == "playing":
            self._engine.overdub()
        elif self._engine.state == "overdubbing":
            self._engine.stop_overdub()

    def _on_play_clicked(self):
        self._engine.play()

    def _on_clear_clicked(self):
        self._engine.clear()

    def _on_delete_track_clicked(self, index: int):
        self._engine.delete_track(index)

    # --- Raccourcis clavier (cf shortcuts/router.py) ---
    # Mêmes règles que les boutons : une action n'a d'effet que dans les états
    # où le bouton correspondant serait actif, et rien si l'audio est coupé.

    def run_shortcut(self, action_id: str):
        if not self._audio_ok:
            return
        state = self._engine.state
        if action_id == "loop_record":
            self._on_record_clicked()
        elif action_id == "loop_overdub":
            self._on_overdub_clicked()
        elif action_id == "loop_play":
            if state == "playing":
                self._engine.stop()
            elif state == "stopped":
                self._engine.play()
        elif action_id == "loop_clear":
            if state in ("playing", "overdubbing", "stopped"):
                self._engine.clear()
        elif action_id == "loop_cycle":
            # Comme une pédale de looper : rec -> (fin du 1er tour) play -> overdub -> play...
            if state == "idle":
                self._on_record_clicked()
            elif state == "recording":
                self._engine.stop_record()
            elif state == "playing":
                self._engine.overdub()
            elif state == "overdubbing":
                self._engine.stop_overdub()
            elif state == "stopped":
                self._engine.play()
            # "counting_in" : on laisse le décompte finir, un 2e appui ne fait rien

    # --- Réaction à l'état du moteur ---

    def _on_state_changed(self, state: str):
        if not self._audio_ok:
            return

        suffix = f" ({self._loop_seconds:.1f}s)" if state != "idle" and self._loop_seconds else ""
        self._status_label.setText(STATE_LABELS.get(state, state) + suffix)

        self._record_btn.setText("Stop" if state == "recording" else "Enregistrer")
        self._record_btn.setEnabled(state in ("idle", "recording", "stopped"))

        self._overdub_btn.setText("Stop overdub" if state == "overdubbing" else "Overdub")
        self._overdub_btn.setEnabled(state in ("playing", "overdubbing"))

        self._play_btn.setEnabled(state == "stopped")

        self._clear_btn.setEnabled(state in ("playing", "overdubbing", "stopped"))

    def _on_length_changed(self, seconds: float):
        self._loop_seconds = seconds
        self._on_state_changed(self._engine.state)

    def _on_stream_error(self, message: str):
        self._audio_ok = False
        self._status_label.setText(f"Pas d'audio : {message}")
        for btn in (self._record_btn, self._overdub_btn, self._play_btn, self._clear_btn):
            btn.setEnabled(False)

    def _refresh_tracks(self):
        while self._tracks_layout.count():
            item = self._tracks_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        count = self._engine.track_count
        if count == 0:
            self._tracks_layout.addWidget(BodyLabel("(aucune piste)"))
            return

        for i in range(count):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            label = "Piste 1 (base)" if i == 0 else f"Piste {i + 1} (overdub)"
            row_layout.addWidget(BodyLabel(label))
            row_layout.addStretch()
            delete_btn = TransparentToolButton(FluentIcon.DELETE)
            delete_btn.clicked.connect(lambda checked=False, idx=i: self._on_delete_track_clicked(idx))
            row_layout.addWidget(delete_btn)
            self._tracks_layout.addWidget(row)

    # --- Nettoyage ---

    # --- Disparition / retour de l'interface audio ---
    # Le panneau ne connaît ni le MIDI ni AmpState : il reçoit juste "l'appareil
    # identifié par `name_hint` est (de nouveau) là / n'est plus là" depuis
    # l'extérieur (cf ui/main_window.py, ui/dashboard_interface.py).

    def _selected_names(self) -> list[str]:
        return [
            combo.currentText() for combo in (self._input_combo, self._output_combo) if combo.currentIndex() >= 0
        ]

    @staticmethod
    def _mentions(names, hint: str) -> bool:
        return any(hint.lower() in (n or "").lower() for n in names)

    def on_device_availability_changed(self, available: bool, name_hint: str = ""):
        if not name_hint:
            return
        self._restore_generation += 1  # annule toute tentative de restauration en attente
        if not available:
            # Ne réagit que si la loop station utilise bien cet appareil
            if not self._mentions(self._selected_names(), name_hint):
                return
            self._engine.stop_stream()
            self._engine.abort_capture()  # après stop_stream : plus de callback concurrent
            self._audio_lost = True
            self._on_stream_error("interface audio déconnectée")
            return

        remembered = [
            self._settings["loop"]["input_device_name"],
            self._settings["loop"]["output_device_name"],
        ]
        if self._audio_lost or self._mentions(remembered, name_hint):
            self._restore_attempts = 0
            self._try_restore_audio(self._restore_generation)

    def _try_restore_audio(self, generation: int):
        """Relance le flux sur les interfaces mémorisées. Windows déclare
        souvent l'audio du Mighty un peu après son MIDI, d'où les nouvelles
        tentatives espacées."""
        if generation != self._restore_generation:
            return
        self._restore_attempts += 1
        self._engine.stop_stream()  # PortAudio ne peut se réinitialiser qu'avec zéro flux ouvert
        try:
            # PortAudio ne rafraîchit sa liste de devices qu'à la réinitialisation
            sd._terminate()
            sd._initialize()
        except Exception:
            pass
        self._populate_devices()

        remembered_in = self._settings["loop"]["input_device_name"]
        remembered_out = self._settings["loop"]["output_device_name"]
        found = (
            any(n == remembered_in for _, n in self._input_devices)
            and any(n == remembered_out for _, n in self._output_devices)
        )
        if found:
            self._audio_lost = False
            self._start_engine()
            if self._audio_ok:
                self._on_state_changed(self._engine.state)
        elif self._restore_attempts < 8:
            QTimer.singleShot(1500, lambda: self._try_restore_audio(generation))
        else:
            self._on_stream_error("interface audio introuvable")

    def stop(self):
        self._engine.stop_stream()