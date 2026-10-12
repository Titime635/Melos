"""
Repousse l'état de l'appli (AmpState) vers le Mighty.

Utilisé au lancement et à chaque reconnexion : le device peut avoir démarré
sur autre chose, ou avoir été débranché pendant que l'utilisateur éditait les
modules (l'UI met alors AmpState à jour sans rien envoyer, cf midi/sender.py).
"""

from PySide6.QtCore import QObject, QTimer

from midi import protocol
from midi.sender import MidiSender
from state.amp_state import AmpState


def send_drum_tempo(state: AmpState, sender: MidiSender):
    sender.drum_set_tempo(state.transport.bpm, state.drum_enabled, state.drum_style, state.drum_level,
                          state.drum_bass, state.drum_middle, state.drum_treble)


def push_state(state: AmpState, sender: MidiSender):
    sender.set_preset(state.current_preset)
    sender.drum_enable(state.drum_enabled)
    sender.drum_set_style(state.drum_style)
    sender.drum_set_level(state.drum_level)
    sender.drum_set_eq(state.drum_bass, state.drum_middle, state.drum_treble)
    send_drum_tempo(state, sender)
    sender.tuner_enable(on=state.tuner_requested, mode=0, ref_pitch=protocol.tuner_ref_byte(state.tuner_ref_hz))


class DeviceSync(QObject):
    """Repousse l'état à chaque passage à "connecté" (hors lancement, géré par
    main.py). À instancier APRÈS le set_connected initial pour ne pas pousser
    deux fois au démarrage."""

    def __init__(self, state: AmpState, sender: MidiSender, parent=None):
        super().__init__(parent)
        self._state = state
        self._sender = sender
        state.connection_changed.connect(self._on_connection_changed)
        # Tempo -> batterie, regroupé : le SysEx embarque tous les réglages, inutile d'en envoyer un par cran
        self._tempo_timer = QTimer(self)
        self._tempo_timer.setSingleShot(True)
        self._tempo_timer.setInterval(250)
        self._tempo_timer.timeout.connect(lambda: send_drum_tempo(state, sender))
        state.transport.changed.connect(lambda name: self._tempo_timer.start() if name == "bpm" else None)

    def _on_connection_changed(self, connected: bool):
        if connected:
            push_state(self._state, self._sender)