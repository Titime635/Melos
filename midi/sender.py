"""
Envoi de commandes vers le Mighty Plug Pro.

Séparé du listener : ceci est synchrone et rapide (pas besoin de thread),
on ouvre le port de sortie une fois et on envoie à la demande.
"""

import mido

from . import protocol


class MidiSender:
    def __init__(self, output_port_name: str):
        self._port = mido.open_output(output_port_name)

    def close(self):
        self._port.close()

    # --- Presets ---
    def set_preset(self, index: int):
        self._port.send(mido.Message("program_change", program=index))

    # --- Tuner ---
    def tuner_enable(self, on: bool, mode: int = 0, ref_pitch: int = 10):
        payload = protocol.build_tuner_sysex(tuner_on=on, mode=mode, ref_pitch=ref_pitch)
        self._port.send(mido.Message("sysex", data=payload))

    # --- Batterie d'accompagnement ---
    def drum_enable(self, on: bool):
        self._send_cc(protocol.CC_DRUMENABLE, 1 if on else 0)

    def drum_set_style(self, style: int):
        self._send_cc(protocol.CC_DRUMTYPE, style)

    def drum_set_level(self, level: int):
        self._send_cc(protocol.CC_DRUMLEVEL, level)

    def drum_set_eq(self, bass: int, middle: int, treble: int):
        self._send_cc(protocol.CC_DRUM_BASS, bass)
        self._send_cc(protocol.CC_DRUM_MIDDLE, middle)
        self._send_cc(protocol.CC_DRUM_TREBLE, treble)

    # TODO: sendDrumsTempo nécessite un SysEx différent (kSYX_DRUM,
    # tempo encodé sur 2 bytes 7-bit) — pas encore testé empiriquement,
    # à valider avant de l'exposer dans l'UI.

    def _send_cc(self, control: int, value: int):
        self._port.send(mido.Message("control_change", control=control, value=value))
