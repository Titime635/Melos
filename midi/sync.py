"""
Repousse l'état de l'appli (AmpState) vers le Mighty.

Utilisé au lancement et à chaque reconnexion : le device peut avoir démarré
sur autre chose, ou avoir été débranché pendant que l'utilisateur éditait les
modules (l'UI met alors AmpState à jour sans rien envoyer, cf midi/sender.py).
"""

from PySide6.QtCore import QObject

from midi.protocol import TUNER_REF_PITCH_440HZ
from midi.sender import MidiSender
from state.amp_state import AmpState


def push_state(state: AmpState, sender: MidiSender):
    sender.set_preset(state.current_preset)
    sender.drum_enable(state.drum_enabled)
    sender.drum_set_style(state.drum_style)
    sender.drum_set_level(state.drum_level)
    sender.drum_set_eq(state.drum_bass, state.drum_middle, state.drum_treble)
    sender.tuner_enable(on=state.tuner_requested, mode=state.tuner_mode, ref_pitch=TUNER_REF_PITCH_440HZ)


class DeviceSync(QObject):
    """Repousse l'état à chaque passage à "connecté" (hors lancement, géré par
    main.py). À instancier APRÈS le set_connected initial pour ne pas pousser
    deux fois au démarrage."""

    def __init__(self, state: AmpState, sender: MidiSender, parent=None):
        super().__init__(parent)
        self._state = state
        self._sender = sender
        state.connection_changed.connect(self._on_connection_changed)

    def _on_connection_changed(self, connected: bool):
        if connected:
            push_state(self._state, self._sender)
