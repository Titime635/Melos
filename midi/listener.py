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

    def __init__(self, input_port_name: str = None):
        super().__init__()
        # If input_port_name is None, use default from protocol
        self._input_port_name = input_port_name if input_port_name is not None else protocol.INPUT_NAME
        self._running = False

    def run(self):
        self._running = True
        while self._running:
            try:
                with mido.open_input(self._input_port_name) as inport:
                    # Successfully opened port, now listen for messages
                    while self._running:
                        for msg in inport.iter_pending():
                            self._dispatch(msg)
                        self.msleep(5)  # évite de saturer le CPU
                # If we exit the inner while loop normally (without exception),
                # it means _running was set to False
                break
            except (IOError, OSError):
                # Port not available or disconnected
                self.connection_lost.emit()
                # Wait before retrying to avoid excessive CPU usage
                self.msleep(1000)  # 1 second delay before retry

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
