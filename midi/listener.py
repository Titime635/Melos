"""
Écoute MIDI en tâche de fond (QThread) pour ne jamais bloquer l'UI.

Le thread et ses signaux vivent pendant toute la durée de l'appli : les
signaux sont câblés UNE fois vers AmpState dans main.py. C'est le port d'entrée
qui est ouvert / fermé / remplacé au fil des connexions (cf attach/detach,
appelés par midi/connection_monitor.py) — recréer le listener obligerait à
recâbler les signaux et risquerait des connexions en double.

Si la lecture échoue (câble arraché), le port est lâché, `broken` passe à True
et connection_lost est émis ; le moniteur bascule alors en "déconnecté".
"""

import threading

import mido
from PySide6.QtCore import QThread, Signal

from . import protocol


class MidiListener(QThread):
    # Signaux émis vers l'UI/l'état — câblés vers state/amp_state.py dans main.py
    preset_changed = Signal(int)                 # program change reçu
    tuner_note = Signal(int)                      # CC_TUNER_NOTE
    tuner_cent = Signal(int)                       # CC_TUNER_CENT
    tuner_state = Signal(bool)                     # CC_TUNER_STATE
    drum_cc_received = Signal(int, int)            # (control, value) brut, à trier côté state
    connection_lost = Signal()                     # la lecture du port a échoué

    def __init__(self):
        super().__init__()
        self._running = False
        self._port = None
        self._broken = False
        self._lock = threading.Lock()

    # --- Cycle de vie du port (appelé par le ConnectionMonitor) ---

    @property
    def is_open(self) -> bool:
        return self._port is not None

    @property
    def broken(self) -> bool:
        """True si la lecture a échoué depuis le dernier attach()."""
        return self._broken

    def attach(self, port_name: str):
        """Ouvre `port_name` et remplace l'éventuel port précédent.
        Peut lever (OSError...) : c'est au moniteur de gérer l'échec."""
        port = mido.open_input(port_name)
        with self._lock:
            old, self._port = self._port, port
            self._broken = False
        self._close_quietly(old)

    def detach(self):
        with self._lock:
            old, self._port = self._port, None
        self._close_quietly(old)

    @staticmethod
    def _close_quietly(port):
        if port is None:
            return
        try:
            port.close()
        except Exception:
            pass

    # --- Boucle de lecture ---

    def run(self):
        self._running = True
        while self._running:
            messages = []
            lost = False
            with self._lock:
                port = self._port
                if port is not None:
                    try:
                        messages = list(port.iter_pending())
                    except Exception:
                        self._port = None
                        self._broken = True
                        lost = True
            if lost:
                self._close_quietly(port)
                self.connection_lost.emit()
            for msg in messages:
                self._dispatch(msg)
            self.msleep(5)  # évite de saturer le CPU

    def _dispatch(self, msg: mido.Message):
        if msg.type == "program_change":
            self.preset_changed.emit(msg.program)

        elif msg.type == "control_change":
            if msg.control == protocol.CC_TUNER_NOTE:
                self.tuner_note.emit(msg.value)
            elif msg.control == protocol.CC_TUNER_CENT:
                self.tuner_cent.emit(msg.value)
            elif msg.control == protocol.CC_TUNER_STATE:
                self.tuner_state.emit(msg.value == 1)
            elif msg.control in (
                protocol.CC_DRUMENABLE,
                protocol.CC_DRUMTYPE,
                protocol.CC_DRUMLEVEL,
                protocol.CC_DRUM_BASS,
                protocol.CC_DRUM_MIDDLE,
                protocol.CC_DRUM_TREBLE,
            ):
                self.drum_cc_received.emit(msg.control, msg.value)

        # TODO: gérer les messages sysex entrants si un jour on a besoin
        # de lire une confirmation autre que le tuner (actuellement pas
        # nécessaire, cf protocol_notes.md)

    def stop(self):
        self._running = False
        self.wait()
        self.detach()
