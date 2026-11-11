"""
Dialogue bloquant avec le Mighty (lecture, envoi, sauvegarde). À appeler depuis un thread de travail, jamais
depuis le thread Qt (cf editor/service.py). Mesures faites sur l'ampli (tools/probe_presets.py) :
lectures 2-3 ms, rafale complète de CC 24 ms sans pause, ordre des blocs acquitté en ~0,5 s,
sauvegarde en flash acquittée en 0,25-1 s.
"""

import threading
import time
from collections import deque

from . import wire
from .catalog import PRESET_LEN
from .preset import Preset


class AmpError(Exception):
    """L'ampli n'a pas répondu / a refusé (message destiné à l'utilisateur)."""


class MidiTransport:
    """Branche AmpIO sur le MidiSender / MidiListener de l'appli (pas de port supplémentaire)."""

    def __init__(self, sender, listener, inbox_size: int = 64):
        self._sender = sender
        self._inbox: deque = deque(maxlen=inbox_size)
        self._cond = threading.Condition()
        listener.add_raw_handler(self._on_message)

    @property
    def connected(self) -> bool:
        return self._sender.is_open

    def _on_message(self, msg):                       # thread du listener
        if msg.type == "sysex":
            with self._cond:
                self._inbox.append(list(msg.data))
                self._cond.notify_all()

    def send_cc(self, control, value):
        return self._sender.send_cc(control, value)

    def send_sysex(self, data):
        return self._sender.send_sysex(data)

    def send_pc(self, program):
        # MidiSender.set_preset() ne rend rien : on juge l'envoi à l'état du port (il se ferme si l'envoi échoue)
        ret = self._sender.set_preset(program)
        return self._sender.is_open if ret is None else bool(ret)

    def clear_inbox(self):
        with self._cond:
            self._inbox.clear()

    def wait_sysex(self, parse, timeout: float):
        """Premier SysEx reçu pour lequel `parse(data)` ne rend pas None (rend ce résultat), sinon None."""
        end = time.monotonic() + timeout
        with self._cond:
            while True:
                for i, d in enumerate(list(self._inbox)):
                    r = parse(d)
                    if r is not None:
                        del self._inbox[i]
                        return r
                left = end - time.monotonic()
                if left <= 0:
                    return None
                self._cond.wait(left)


class AmpIO:
    def __init__(self, transport, cc_pause: float = 0.002, sleep=time.sleep):
        self.t = transport
        self.cc_pause = cc_pause
        self._sleep = sleep
        self.lock = threading.RLock()            # une seule conversation à la fois avec l'ampli

    # --- Envoi ---
    def _send(self, msgs):
        for kind, a, *rest in msgs:
            ok = self.t.send_cc(a, rest[0]) if kind == "cc" else self.t.send_sysex(a)
            if not ok:
                raise AmpError("Mighty non connecté")
            if self.cc_pause:
                self._sleep(self.cc_pause)

    # --- Lecture ---
    def read_slot(self, slot: int, timeout: float = 1.0) -> Preset:
        """Preset ENREGISTRÉ dans l'emplacement (0x0B) — ignore les modifications en cours."""
        with self.lock:
            self.t.clear_inbox()
            self._send([wire.request_preset(slot)])
            r = self.t.wait_sysex(lambda d: (x if (x := wire.parse_preset_reply(d)) and x[0] == slot else None), timeout)
        if r is None:
            raise AmpError(f"Pas de réponse de l'ampli pour l'emplacement {slot + 1}")
        return Preset(r[1])

    def read_current(self, timeout: float = 1.0) -> tuple[int, Preset]:
        """(emplacement courant, preset COURANT avec les modifications non sauvegardées) (0x0C)."""
        with self.lock:
            self.t.clear_inbox()
            self._send([wire.request_current()])
            r = self.t.wait_sysex(wire.parse_current_reply, timeout)
        if r is None:
            raise AmpError("Pas de réponse de l'ampli (preset courant)")
        return r[0], Preset(r[1])

    # --- Actions ---
    def select(self, slot: int):
        """Change de preset (les modifications non sauvegardées de l'ampli sont perdues) et attend que l'ampli
        annonce le bon emplacement."""
        with self.lock:
            self.t.clear_inbox()
            if not self.t.send_pc(slot):
                raise AmpError("Mighty non connecté")
            end = time.monotonic() + 3.0
            while time.monotonic() < end:
                try:
                    cur, _ = self.read_current(timeout=0.4)
                except AmpError:
                    continue
                if cur == slot:
                    return
                self._sleep(0.01)
        raise AmpError(f"L'ampli n'a pas basculé sur l'emplacement {slot + 1}")

    def push(self, preset: Preset, current: Preset | None = None):
        """Fait du preset courant de l'ampli une copie de `preset`. Avec `current` (ce que l'ampli a déjà),
        n'envoie que les différences."""
        msgs = wire.diff_messages(current, preset) if current is not None else wire.full_messages(preset)
        with self.lock:
            self._send(msgs)
            if any(m[0] == "syx" for m in msgs):          # l'ordre des blocs est acquitté (~0,5 s)
                self.t.wait_sysex(wire.parse_order_reply, 1.5)

    def verify_current(self, expected: Preset) -> bool:
        _, cur = self.read_current()
        return cur.wire_bytes() == expected.wire_bytes()

    def save(self, slot: int, timeout: float = 3.0):
        """Écrit en flash le preset courant dans `slot` (à appeler quand l'ampli est sur `slot`)."""
        with self.lock:
            self.t.clear_inbox()
            self._send([wire.save_slot(slot)])
            if self.t.wait_sysex(lambda d: True if wire.is_save_ack(d, slot) else None, timeout) is None:
                raise AmpError(f"L'ampli n'a pas confirmé la sauvegarde de l'emplacement {slot + 1}")