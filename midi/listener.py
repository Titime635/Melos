"""
Écoute MIDI en tâche de fond (QThread) pour ne jamais bloquer l'UI.

Contrairement au script de test (boucle synchrone dans le main), ici on tourne
dans un thread séparé et on émet des signaux Qt à chaque message reçu.
L'UI n'a jamais besoin de poller quoi que ce soit — elle écoute juste
les signaux `preset_changed`, `tuner_data`, `drum_cc_received`, etc.
"""

import mido
from PySide6.QtCore import QThread, Signal

from . import protocol


class MidiListener(QThread):
    # Signaux émis vers l'UI/l'état — à connecter dans state/amp_state.py
    preset_changed = Signal(int)                 # program change reçu
    tuner_note = Signal(int)                      # CC_TUNER_NOTE
    tuner_cent = Signal(int)                       # CC_TUNER_CENT
    tuner_state = Signal(bool)                     # CC_TUNER_STATE
    drum_cc_received = Signal(int, int)            # (control, value) brut, à trier côté state
    connection_lost = Signal()

    def __init__(self, input_port_name: str):
        super().__init__()
        self._input_port_name = input_port_name
        self._running = False

    def run(self):
        self._running = True
        try:
            with mido.open_input(self._input_port_name) as inport:
                while self._running:
                    for msg in inport.iter_pending():
                        self._dispatch(msg)
                    self.msleep(5)  # évite de saturer le CPU
        except (IOError, OSError):
            self.connection_lost.emit()

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
