"""
Surveillance de la connexion au Mighty Plug Pro.

Responsabilités:
- Poll tous les secondes pour détecter la présence du device (prefixe "NUX NMP-03")
- Gère l'ouverture/fermeture des ports MIDI sous verrou
- Démarre/arrête le thread du listener
- Synchronise l'état vers le device lors (re)connexion
- Met à jour AmpState.connected (source unique de vérité)
"""
import time
from PySide6.QtCore import QThread, Signal
import mido

from state.amp_state import AmpState
from midi.sender import MidiSender
from midi.listener import MidiListener


class ConnectionMonitor(QThread):
    """Moniteur de connexion qui tourne en arrière-plan."""

    # Signal émis lorsque l'état de connexion change
    # Connecté à AmpState.connection_changed dans main.py
    connection_changed = Signal(bool)

    def __init__(self, state: AmpState, sender: MidiSender, listener: MidiListener):
        super().__init__()
        self._state = state
        self._sender = sender
        self._listener = listener
        self._running = False
        self._device_connected = False  # État interne du moniteur

        # Prefixes pour la détection des ports (séparés pour input et output)
        self._input_prefix = "NUX NMP-03"
        self._output_prefix = "NUX NMP-03"

    def run(self):
        """Boucle principale de surveillance."""
        self._running = True
        while self._running:
            # Vérifier la présence du device
            input_available = self._find_port_with_prefix(
                mido.get_input_names(), self._input_prefix
            )
            output_available = self._find_port_with_prefix(
                mido.get_output_names(), self._output_prefix
            )
            device_available = input_available and output_available

            # Gérer les changements d'état de connexion
            if device_available and not self._device_connected:
                self._on_device_connected(input_available, output_available)
            elif not device_available and self._device_connected:
                self._on_device_disconnected()

            # Attendre avant la prochaine vérification
            self.msleep(1000)  # 1 seconde

    def _find_port_with_prefix(self, port_names, prefix):
        """Trouve un port dont le nom commence par le préfixe spécifié."""
        for port_name in port_names:
            if port_name.startswith(prefix):
                return port_name
        return None

    def _on_device_connected(self, input_port_name, output_port_name):
        """Appelé lorsque le device est détecté."""
        self._device_connected = True

        # Mettre à jour l'état de connexion (source unique de vérité)
        self._state.set_connected(True)
        self.connection_changed.emit(True)

        # Ouvrir le port de sortie du sender (thread-safe)
        if output_port_name:
            self._sender._output_port_name = output_port_name
            self._sender.open_port()

        # Démarrer le listener avec le port d'entrée résolu
        if input_port_name:
            self._listener._input_port_name = input_port_name
            if not self._listener.isRunning():
                self._listener.start()

        # Délai court avant de pousser l'état vers le device
        self.msleep(400)  # ~400 ms

        # Synchroniser l'état vers le device
        self._sync_state_to_device()

    def _on_device_disconnected(self):
        """Appelé lorsque le device n'est plus détecté."""
        self._device_connected = False

        # Mettre à jour l'état de connexion
        self._state.set_connected(False)
        self.connection_changed.emit(False)

        # Arrêter le listener
        if self._listener.isRunning():
            self._listener.stop()

        # Fermer le port du sender
        self._sender.close()

    def _sync_state_to_device(self):
        """Envoie l'état actuel de AmpState vers le device."""
        from midi.protocol import TUNER_REF_PITCH_440HZ
        sender = self._sender
        state = self._state

        # Renvoie au device les réglages actuels (même fonction qu'au lancement)
        sender.set_preset(state.current_preset)
        sender.drum_enable(state.drum_enabled)
        sender.drum_set_style(state.drum_style)
        sender.drum_set_level(state.drum_level)
        sender.drum_set_eq(state.drum_bass, state.drum_middle, state.drum_treble)
        sender.tuner_enable(on=state.tuner_requested, mode=state.tuner_mode, ref_pitch=TUNER_REF_PITCH_440HZ)

    def stop(self):
        """Arrête le moniteur proprement."""
        self._running = False
        self.wait()