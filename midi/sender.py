"""
Envoi de commandes vers le Mighty Plug Pro.

Une SEULE instance vit pendant toute la durée de l'appli : l'UI en garde la
référence dès la construction des panneaux. C'est le port MIDI interne qui est
ouvert / fermé / remplacé au fil des connexions (cf midi/connection_monitor.py),
jamais le sender lui-même.

Garanties :
  - aucune méthode d'envoi ne lève d'exception : sans port, c'est un no-op
    silencieux (l'UI met à jour AmpState normalement, l'état est repoussé au
    device à la reconnexion, cf midi/sync.py) ;
  - si un envoi échoue (câble arraché), le port est fermé et considéré mort ;
    le moniteur le voit via `is_open` et bascule en "déconnecté" ;
  - le port est protégé par un verrou : l'UI envoie depuis le thread Qt pendant
    que le moniteur peut l'ouvrir/fermer depuis son propre thread.
"""

import threading

import mido

from . import protocol


class MidiSender:
    def __init__(self):
        self._port = None
        self._lock = threading.Lock()

    # --- Cycle de vie du port (appelé par le ConnectionMonitor) ---

    @property
    def is_open(self) -> bool:
        return self._port is not None

    def attach(self, port_name: str):
        """Ouvre `port_name` et remplace l'éventuel port précédent.
        Peut lever (OSError...) : c'est au moniteur de gérer l'échec."""
        port = mido.open_output(port_name)
        with self._lock:
            old, self._port = self._port, port
        self._close_quietly(old)

    def detach(self):
        with self._lock:
            old, self._port = self._port, None
        self._close_quietly(old)

    def close(self):
        self.detach()

    @staticmethod
    def _close_quietly(port):
        if port is None:
            return
        try:
            port.close()
        except Exception:
            pass  # port déjà mort, rien à faire de plus

    # --- Presets ---
    def set_preset(self, index: int):
        self._send(mido.Message("program_change", program=index))

    # --- Tuner ---
    def tuner_enable(self, on: bool, mode: int = 0, ref_pitch: int = 10):
        payload = protocol.build_tuner_sysex(tuner_on=on, mode=mode, ref_pitch=ref_pitch)
        self._send(mido.Message("sysex", data=payload))

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
        self._send(mido.Message("control_change", control=control, value=value))

    def _send(self, msg: mido.Message) -> bool:
        with self._lock:
            port = self._port
            if port is None:
                return False
            try:
                port.send(msg)
                return True
            except Exception:
                # Device probablement débranché : on lâche le port, le
                # moniteur constatera is_open == False au prochain tour.
                self._port = None
        self._close_quietly(port)
        return False
