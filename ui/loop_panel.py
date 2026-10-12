"""
Panneau loop station PC.

100% logiciel (le Plug Pro n'a pas de looper hardware, cf docs/protocol_notes.md) :
le moteur audio (audio/loop_engine.py) est un pipeline par callback
sounddevice. Ce panneau ne parle pas MIDI : le tempo, la signature et les
options de quantification viennent d'un TransportState partagé (cf
state/transport_state.py), et le démarrage de la batterie calé sur la mesure
passe par `request_drum_start` appelé par le DrumPanel. Il partage settings.py
(JSON unique) pour se souvenir de ses réglages d'une session à l'autre.

Chaque prise (base + overdubs) est une piste séparée dans le moteur,
affichée ici sous forme de liste avec un bouton de suppression individuel.

Tous les SpinBox/Slider/ComboBox de ce panneau utilisent les variantes
NoWheel* (ui/widgets.py) : la molette ne doit pas changer une valeur par
erreur pendant qu'on scrolle la page.
"""

import logging
import threading
import time

from PySide6.QtCore import Qt, QPoint, QSize, QTimer, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QFrame, QScrollArea, QSizePolicy)
from qfluentwidgets import (BodyLabel, CaptionLabel, StrongBodyLabel, SwitchButton,
                            TransparentToolButton, FluentIcon)

from audio import portaudio_utils as pa
from audio.audio_config import AudioConfig
from audio.loop_engine import LoopEngine
from settings import load_settings, update_settings
from state.transport_state import TransportState
from ui import looper_widgets as lw
from ui.module_card import MODULE_COLORS, ModuleCard
from ui.popup_utils import show_popup_under
from ui.widgets import NoWheelSpinBox, NoWheelSlider

STATE_LABELS = {
    "idle": "Prêt",
    "counting_in": "Décompte...",
    "recording": "Enregistrement (1er tour)...",
    "playing": "Lecture en boucle",
    "overdubbing": "Overdub en cours...",
    "stopped": "Arrêté (nombre de répétitions atteint)",
}

# Texte affiché sur la barre de position pendant l'attente de la mesure
PENDING_BAR_TEXT = {
    "record": "Rec à la mesure…",
    "stop_record": "Fin à la mesure…",
    "overdub": "Overdub à la mesure…",
    "stop_overdub": "Fin à la mesure…",
    "stop": "Stop à la mesure…",
    "play": "Play à la mesure…",
}

PENDING_LABELS = {
    "record": "début de l'enregistrement",
    "stop_record": "fin de l'enregistrement",
    "overdub": "début de l'overdub",
    "stop_overdub": "fin de l'overdub",
    "stop": "arrêt",
    "play": "reprise",
}


log = logging.getLogger("melos.audio")


class LoopPanel(ModuleCard):
    # Fin d'une réinitialisation de PortAudio faite dans un thread de travail : (génération, statut)
    _audio_refreshed = Signal(int, str)

    # Le module s'adapte lui-même à sa taille (cf _apply_density) : le dock n'a pas à le mettre dans une
    # zone de défilement (cf ui/dashboard/dock_widget.py).
    adaptive = True

    def __init__(self, transport: TransportState | None = None, engine: LoopEngine | None = None,
                 audio: AudioConfig | None = None, parent=None):
        super().__init__(parent, accent=MODULE_COLORS["loop"])
        self.setTitle("Loop station PC")

        self._settings = load_settings()
        # Tempo / quantification : partagé avec l'autre vue et la batterie s'il est fourni
        self._transport = transport if transport is not None else TransportState(self)
        self._drum_start_callback = None

        # Moteur partagé par les deux vues (Dashboard / Classique) quand il est fourni : une seule loop
        # station, un seul flux audio, un seul clic. Sinon (tests, usage seul) le panneau a le sien.
        self._engine = engine if engine is not None else LoopEngine()
        # QueuedConnection explicite : ces signaux peuvent être émis depuis le
        # thread callback de PortAudio, pas seulement depuis ce thread Qt.
        self._engine.state_changed.connect(self._on_state_changed, Qt.QueuedConnection)
        self._engine.loop_length_changed.connect(self._on_length_changed, Qt.QueuedConnection)
        self._engine.stream_error.connect(self._on_stream_error, Qt.QueuedConnection)
        self._engine.tracks_changed.connect(self._refresh_tracks, Qt.QueuedConnection)
        self._engine.pending_changed.connect(self._on_pending_changed, Qt.QueuedConnection)
        self._engine.drum_start_due.connect(self._on_drum_start_due, Qt.QueuedConnection)

        # Périphériques + tampon : choisis dans la page Réglages (cf audio/audio_config.py), partagés par les deux vues
        self._audio = audio if audio is not None else AudioConfig(self._engine, self)
        self._audio.engine_restarted.connect(self._on_engine_restarted)
        self._loop_seconds = 0.0
        self._audio_ok = True
        self._audio_lost = False        # flux coupé parce que l'interface audio a disparu
        self._restore_attempts = 0
        self._restore_generation = 0    # invalide les tentatives en attente quand l'état change

        self._audio_refreshed.connect(self._on_audio_refreshed, Qt.QueuedConnection)

        self._build_ui()
        self._apply_remembered_loop_settings()
        self._apply_transport()
        self._transport.changed.connect(self._on_transport_changed)
        if not self._engine.running:  # l'autre vue a peut-être déjà ouvert le flux
            self._start_engine()
        self._on_state_changed(self._engine.state)
        self._refresh_tracks()

        # Photo du moteur ~30 fois/s pour la barre de position (inutile si le module est caché)
        self._poll = QTimer(self)
        self._poll.setInterval(33)
        self._poll.timeout.connect(self._poll_engine)
        self._poll.start()

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(8)
        self.viewLayout.addLayout(layout)

        # --- Ligne d'état + engrenage (volet de réglages) ---
        self._head_w = QWidget()
        head = QHBoxLayout(self._head_w)
        head.setContentsMargins(0, 0, 0, 0)
        self._status_label = BodyLabel(STATE_LABELS["idle"])
        head.addWidget(self._status_label, stretch=1)
        self._gear_btn = TransparentToolButton(FluentIcon.SETTING)
        self._gear_btn.setToolTip("Réglages du looper")
        self._gear_btn.clicked.connect(self._toggle_settings)
        self.add_header_action(self._gear_btn)   # l'engrenage vit dans l'en-tête du module
        layout.addWidget(self._head_w)

        # --- Barre de position ---
        self._bar = lw.PositionBar()
        layout.addWidget(self._bar)

        # --- Touches de transport ---
        self._transport_w = QWidget()
        btn_row = QHBoxLayout(self._transport_w)
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(8)
        self._record_btn = lw.TransportButton("record", "Enregistrer", lw.REC)
        self._record_btn.clicked.connect(self._on_record_clicked)
        self._overdub_btn = lw.TransportButton("overdub", "Overdub", lw.OVERDUB)
        self._overdub_btn.clicked.connect(self._on_overdub_clicked)
        self._play_btn = lw.TransportButton("play", "Play", lw.PLAY)
        self._play_btn.clicked.connect(self._on_play_clicked)
        self._clear_btn = lw.TransportButton("clear", "Effacer", lw.NEUTRAL)
        self._clear_btn.clicked.connect(self._on_clear_clicked)
        for btn in (self._record_btn, self._overdub_btn, self._play_btn, self._clear_btn):
            btn_row.addWidget(btn)
        layout.addWidget(self._transport_w)

        # --- Réglages de jeu rapides : décompte, durée de la 1re prise (le calage est dans l'engrenage) ---
        self._chips_w = QWidget()
        chips = QHBoxLayout(self._chips_w)
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(8)
        self._count_in_switch = lw.PillButton("Décompte", lw.WAIT, kind="countin", checkable=True)
        self._count_in_switch.setToolTip("Décompte avant la 1re prise : quelques clics, calés sur la batterie si elle tourne, "
                                         "puis l'enregistrement démarre tout seul")
        self._count_in_switch.setMinimumWidth(120)
        self._count_in_switch.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._count_in_switch.toggled.connect(lambda _c: self._save_loop_settings())
        chips.addWidget(self._count_in_switch)
        chips.addStretch()
        chips.addWidget(CaptionLabel("1re prise"))
        self._bars_spin = NoWheelSpinBox()
        self._bars_spin.setRange(0, 64)
        self._bars_spin.setSpecialValueText("Manuelle")
        self._bars_spin.setSuffix(" mes.")
        self._bars_spin.setToolTip("Durée de la 1re prise : le looper s'arrête pile après ce nombre de mesures")
        self._bars_spin.valueChanged.connect(lambda v: self._transport.set(bars=v))
        chips.addWidget(self._bars_spin)
        layout.addWidget(self._chips_w)

        # --- Volume du looper ---
        self._volume_w = QWidget()
        vol = QHBoxLayout(self._volume_w)
        vol.setContentsMargins(0, 0, 0, 0)
        vol.addWidget(CaptionLabel("Volume"))
        self._volume_slider = NoWheelSlider(Qt.Horizontal)
        self._volume_slider.setRange(0, 150)
        self._volume_slider.valueChanged.connect(self._on_volume_changed)
        vol.addWidget(self._volume_slider, stretch=1)
        self._volume_label = BodyLabel("100%")
        self._volume_label.setMinimumWidth(40)
        vol.addWidget(self._volume_label)
        layout.addWidget(self._volume_w)

        # --- Pistes (défilement interne de la liste seulement) ---
        self._tracks_scroll = QScrollArea()
        self._tracks_scroll.setWidgetResizable(True)
        self._tracks_scroll.setFrameShape(QFrame.NoFrame)
        self._tracks_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._tracks_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._tracks_scroll.viewport().setAutoFillBackground(False)
        tracks_body = QWidget()
        tracks_body.setStyleSheet("background: transparent;")
        self._tracks_layout = QVBoxLayout(tracks_body)
        self._tracks_layout.setContentsMargins(0, 0, 0, 0)
        self._tracks_layout.setSpacing(2)
        self._tracks_layout.addStretch()
        self._tracks_scroll.setWidget(tracks_body)
        self._tracks_scroll.setMinimumHeight(48)
        layout.addWidget(self._tracks_scroll, stretch=1)

        self._build_settings_popup()

    def _build_settings_popup(self):
        """Volet des réglages rares, ouvert par l'engrenage. Les périphériques audio et le tampon sont
        dans la page Réglages."""
        popup = QFrame(self, Qt.Popup)
        popup.setObjectName("LoopSettingsPopup")
        popup.setStyleSheet(
            "#LoopSettingsPopup { background: palette(window); border: 1px solid rgba(128,128,128,0.45);"
            " border-radius: 8px; }")
        v = QVBoxLayout(popup)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(8)

        v.addWidget(StrongBodyLabel("Audio"))
        audio = QFormLayout()
        audio.setSpacing(8)
        self._latency_comp_spin = NoWheelSpinBox()
        self._latency_comp_spin.setRange(0, 500)
        self._latency_comp_spin.setSuffix(" ms")
        self._latency_comp_spin.setToolTip(
            "Décalage entre ce que tu joues et ce que le looper enregistre (aller-retour de la carte son). "
            "Si les prises sonnent en retard sur le clic, augmente.")
        self._latency_comp_spin.valueChanged.connect(lambda v: self._transport.set(latency_comp_ms=v))
        audio.addRow("Latence à compenser", self._latency_comp_spin)
        v.addLayout(audio)

        v.addWidget(StrongBodyLabel("Prise"))
        take = QFormLayout()
        take.setSpacing(8)
        self._quantize_switch = SwitchButton()
        self._quantize_switch.setOnText("Oui")
        self._quantize_switch.setOffText("Non")
        self._quantize_switch.setToolTip("Rec / Overdub / Stop attendent le début de la mesure suivante "
                                         "(et suivent la batterie si elle tourne)")
        self._quantize_switch.checkedChanged.connect(lambda c: self._transport.set(quantize=c))
        take.addRow("Caler sur la mesure", self._quantize_switch)
        self._repeat_spin = NoWheelSpinBox()
        self._repeat_spin.setRange(0, 999)
        self._repeat_spin.setSpecialValueText("Infini")
        self._repeat_spin.valueChanged.connect(self._on_repeat_changed)
        take.addRow("Répétitions", self._repeat_spin)
        self._overdub_passes_spin = NoWheelSpinBox()
        self._overdub_passes_spin.setRange(0, 99)
        self._overdub_passes_spin.setSpecialValueText("Illimité")
        self._overdub_passes_spin.valueChanged.connect(self._on_overdub_passes_changed)
        take.addRow("Tours d'overdub", self._overdub_passes_spin)
        v.addLayout(take)
        self._settings_popup = popup

    @property
    def engine(self) -> LoopEngine:
        return self._engine

    def _toggle_settings(self):
        show_popup_under(self._settings_popup, self._gear_btn, True)

    # --- Densité : le module montre plus ou moins de choses selon la place disponible ---

    def _base_height(self) -> int:
        """Hauteur du strict nécessaire : en-tête du module, état, barre, touches."""
        spacing = 8
        return (self.chrome_height() + 4 + self._head_w.sizeHint().height() + self._bar.minimumHeight()
                + self._transport_w.sizeHint().height() + spacing * 2)

    def minimumSizeHint(self) -> QSize:
        # Constant : ne dépend pas des sections affichées, sinon le dock ne pourrait plus rétrécir
        return QSize(230, self._base_height())

    def sizeHint(self) -> QSize:
        # Taille "confortable" (tout visible) pour la vue empilée ; le dock, lui, impose la sienne
        spacing = 8
        full = (self._base_height() + self._chips_w.sizeHint().height() + self._volume_w.sizeHint().height()
                + 150 + spacing * 3)
        return QSize(520, full)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_density()

    def _apply_density(self):
        spacing = 8
        room = self.height() - self._base_height()
        chips_h = self._chips_w.sizeHint().height() + spacing
        volume_h = self._volume_w.sizeHint().height() + spacing
        tracks_h = 48 + spacing
        show_chips = room >= chips_h
        show_volume = room >= chips_h + volume_h
        show_tracks = room >= chips_h + volume_h + tracks_h
        self._chips_w.setVisible(show_chips)
        self._volume_w.setVisible(show_volume)
        self._tracks_scroll.setVisible(show_tracks)
        compact = self.width() < 330
        for btn in (self._record_btn, self._overdub_btn, self._play_btn, self._clear_btn):
            btn.set_compact(compact)

    def _poll_engine(self):
        if not self.isVisible():
            return
        snap = self._engine.snapshot()
        pending = "Décompte…" if snap["state"] == "counting_in" else PENDING_BAR_TEXT.get(snap["pending"], "")
        self._bar.set_snapshot(snap, pending)
        # Pastilles du bouton Décompte : allumées au fil des temps pendant le décompte
        counting = snap["state"] == "counting_in"
        self._count_in_switch.set_marker(snap["beat"] if counting else -1, snap["beats"])

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


    def _start_engine(self):
        self._audio_ok = self._audio.start_engine()

    def _on_engine_restarted(self, ok: bool):
        """Le flux a été (ré)ouvert par la page Réglages ou par l'autre vue."""
        self._audio_ok = ok
        if ok:
            self._audio_lost = False
            self._on_state_changed(self._engine.state)

    def _save_loop_settings(self):
        # Section relue à l'instant : les périphériques / le tampon y sont écrits par AudioConfig
        cfg = load_settings()["loop"]
        cfg.update(
            volume=self._volume_slider.value() / 100,
            repeat_target=self._repeat_spin.value(),
            overdub_passes_target=self._overdub_passes_spin.value(),
            count_in_enabled=self._count_in_switch.isChecked(),
        )
        self._settings["loop"] = cfg
        update_settings({"loop": cfg})  # seulement notre section (cf settings.py)

    # --- Actions utilisateur : réglages ---

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

    # --- Tempo / quantification (TransportState partagé) ---

    def _apply_transport(self):
        """Reflète le TransportState dans les widgets ET dans le moteur."""
        t = self._transport
        for widget, value in ((self._bars_spin, t.bars), (self._latency_comp_spin, t.latency_comp_ms)):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        self._quantize_switch.blockSignals(True)
        self._quantize_switch.setChecked(t.quantize)
        self._quantize_switch.blockSignals(False)

        e = self._engine
        if not e.track_count and e.state in ("idle", "stopped"):
            e.set_grid(t.bpm, t.beats, t.unit)  # une boucle existante garde sa grille
        e.set_quantize(t.quantize)
        e.set_click(t.click)
        e.set_auto_bars(t.bars)
        e.set_latency_comp_ms(t.latency_comp_ms)
        e.set_drum_lead_ms(t.drum_latency_ms)

    def _on_transport_changed(self, _name: str):
        self._apply_transport()


    # --- Batterie calée sur la mesure (appelé par DrumPanel) ---

    def request_drum_start(self, callback) -> bool:
        """Programme `callback` (démarrage de la batterie) au prochain début de mesure.
        False si la synchro est coupée ou l'audio indisponible : l'appelant démarre alors tout de suite."""
        if not self._transport.sync_drums or not self._audio_ok:
            return False
        self._drum_start_callback = callback
        self._engine.schedule_drum_start()
        return True

    def drum_stopped(self):
        """La batterie est coupée (ou son démarrage annulé) : elle ne sert plus de repère."""
        self._drum_start_callback = None
        self._engine.cancel_drum_start()
        self._engine.set_external_reference(False)

    def _on_drum_start_due(self):
        callback, self._drum_start_callback = self._drum_start_callback, None
        if callback is not None:
            self._engine.set_external_reference(True)
            callback()

    def _on_pending_changed(self, _label: str):
        self._on_state_changed(self._engine.state)

    # --- Actions utilisateur : transport ---

    def _cancel_if_pending(self) -> bool:
        """Un 2e appui pendant l'attente de la mesure annule l'action en attente."""
        if self._engine.pending_action and self._engine.state != "counting_in":
            self._engine.cancel_pending()
            return True
        return False

    def _on_record_clicked(self):
        if self._cancel_if_pending():
            return
        state = self._engine.state
        if state in ("idle", "stopped"):
            if self._count_in_switch.isChecked():
                self._engine.record_with_count_in()
            else:
                self._engine.record()
        elif state == "recording":
            self._engine.stop_record()

    def _on_overdub_clicked(self):
        if self._cancel_if_pending():
            return
        if self._engine.state == "playing":
            self._engine.overdub()
        elif self._engine.state == "overdubbing":
            self._engine.stop_overdub()

    def _on_play_clicked(self):
        if self._cancel_if_pending():
            return
        if self._engine.state == "playing":
            self._engine.stop()
        else:
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
            if self._cancel_if_pending():
                return
            if state == "playing":
                self._engine.stop()
            elif state == "stopped":
                self._engine.play()
        elif action_id == "loop_clear":
            if state in ("playing", "overdubbing", "stopped"):
                self._engine.clear()
        elif action_id == "loop_cycle":
            # Comme une pédale de looper : rec -> (fin du 1er tour) play -> overdub -> play...
            if self._cancel_if_pending():
                return
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
        pending = self._engine.pending_action
        waiting = bool(pending) and state != "counting_in"
        wait = f"  —  attente de la mesure : {PENDING_LABELS.get(pending, pending)}" if waiting else ""
        self._status_label.setText(STATE_LABELS.get(state, state) + suffix + wait)

        # Pendant l'attente de la mesure, la touche concernée devient "Annuler"
        if pending in ("record", "stop_record") and state != "counting_in":
            self._record_btn.set_content("cancel", "Annuler", False)
        elif state == "recording":
            self._record_btn.set_content("stop", "Stop", True)
        else:
            self._record_btn.set_content("record", "Enregistrer", False)
        self._record_btn.setEnabled(state in ("idle", "recording", "stopped"))

        if pending in ("overdub", "stop_overdub"):
            self._overdub_btn.set_content("cancel", "Annuler", False)
        elif state == "overdubbing":
            self._overdub_btn.set_content("stop", "Stop overdub", True)
        else:
            self._overdub_btn.set_content("overdub", "Overdub", False)
        self._overdub_btn.setEnabled(state in ("playing", "overdubbing"))

        if pending in ("play", "stop"):
            self._play_btn.set_content("cancel", "Annuler", False)
        elif state == "playing":
            self._play_btn.set_content("stop", "Stop", False)
        else:
            self._play_btn.set_content("play", "Play", False)
        self._play_btn.setEnabled(state in ("stopped", "playing"))

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
        while self._tracks_layout.count() > 1:  # le dernier élément est l'étirement final
            item = self._tracks_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        count = self._engine.track_count
        if count == 0:
            empty = CaptionLabel("Aucune piste : enregistre une première prise.")
            self._tracks_layout.insertWidget(0, empty)
            return

        for i in range(count):
            name = "Base" if i == 0 else f"Overdub {i}"
            row = lw.TrackRow(i, name, self._engine.track_gain(i), self._engine.track_muted(i))
            row.muted_changed.connect(self._engine.set_track_muted)
            row.gain_changed.connect(self._engine.set_track_gain)
            row.delete_requested.connect(self._on_delete_track_clicked)
            self._tracks_layout.insertWidget(i, row)

    # --- Nettoyage ---

    # --- Disparition / retour de l'interface audio ---
    # Le panneau ne connaît ni le MIDI ni AmpState : il reçoit juste "l'appareil
    # identifié par `name_hint` est (de nouveau) là / n'est plus là" depuis
    # l'extérieur (cf ui/main_window.py, ui/dashboard_interface.py).

    def _selected_names(self) -> list[str]:
        return [n for n in (self._audio.input_name, self._audio.output_name) if n]

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
            self._engine.stop_stream()  # sans attendre : peut rester coincé si l'interface vient de disparaître
            self._engine.abort_capture()  # le callback en vol rend du silence (cf LoopEngine._running)
            self._audio_lost = True
            self._on_stream_error("interface audio déconnectée")
            return

        remembered = list(self._audio.remembered_names)
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
        requested_at = time.monotonic()

        def work():
            # PortAudio ne rafraîchit sa liste de devices qu'à la réinitialisation, et celle-ci
            # peut bloquer : jamais dans le thread Qt.
            self._audio_refreshed.emit(generation, pa.refresh_portaudio(requested_at))

        threading.Thread(target=work, name="portaudio-refresh", daemon=True).start()

    def _on_audio_refreshed(self, generation: int, status: str):
        if generation != self._restore_generation:
            return  # l'état a encore changé depuis : cette tentative est périmée
        if status in ("ok", "busy"):
            # "busy" : l'autre vue (Dashboard / Classique) a déjà réinitialisé PortAudio et son flux tourne
            # déjà. La liste des interfaces est donc à jour : on la relit sans réinitialiser une 2e fois
            # (ce qui couperait le flux de l'autre vue).
            self._audio.refresh_devices()
        else:
            log.warning("réinitialisation de PortAudio impossible (%s)", status)
            self._audio.input_devices, self._audio.output_devices = [], []
            self._audio.devices_changed.emit()

        if self._audio.remembered_present:
            self._audio_lost = False
            if not self._engine.running:  # moteur partagé : l'autre vue l'a peut-être déjà relancé
                self._start_engine()
            else:
                self._audio_ok = True
            if self._audio_ok:
                self._on_state_changed(self._engine.state)
        elif self._restore_attempts < 8:
            QTimer.singleShot(1500, lambda: self._try_restore_audio(generation))
        else:
            self._on_stream_error("interface audio introuvable")

    def stop(self):
        self.drum_stopped()
        self._engine.stop_stream()