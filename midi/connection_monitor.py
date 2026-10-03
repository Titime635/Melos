"""
Surveillance de la connexion au Mighty Plug Pro.

Un thread unique qui, toutes les ~1 s :
  - déconnecté : cherche les ports MIDI du Mighty (par mot-clé, cf
    protocol.find_port) et, s'ils sont là, les ouvre via listener.attach() /
    sender.attach() ;
  - connecté   : vérifie que le lien tient toujours (ports encore listés,
    lecture ou envoi pas en erreur) et sinon libère les ports.

Le moniteur ne touche ni à AmpState ni à l'UI : il émet seulement
`connected_changed(bool)`, que main.py relie à AmpState.set_connected. Le
repoussage de l'état vers le device à la (re)connexion est fait ailleurs (cf
midi/sync.py).

Sous Windows, la liste des ports peut rester périmée tant qu'un port est
ouvert : la détection ne repose donc pas que sur la liste, elle regarde aussi
les erreurs de lecture (listener.broken) et d'envoi (sender.is_open).
"""

import logging
import threading

import mido
from PySide6.QtCore import QThread, Signal

from . import protocol

log = logging.getLogger("melos.midi")


class ConnectionMonitor(QThread):
    connected_changed = Signal(bool)

    def __init__(self, listener, sender, poll_interval: float = 1.0, settle_delay: float = 0.4):
        super().__init__()
        self._listener = listener
        self._sender = sender
        self._poll_interval = poll_interval
        self._settle_delay = settle_delay  # pause après ouverture, avant de dire "connecté"
        self._stop_event = threading.Event()
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    # --- Détection / ouverture ---

    @staticmethod
    def _find_ports() -> tuple[str, str] | None:
        """(entrée, sortie) du Mighty si les deux sont listés, sinon None."""
        try:
            in_name = protocol.find_port(mido.get_input_names())
            out_name = protocol.find_port(mido.get_output_names())
        except Exception as exc:
            log.warning("énumération des ports MIDI impossible : %s", exc)
            return None
        if in_name is None or out_name is None:
            return None
        return in_name, out_name

    def try_connect(self) -> bool:
        """Tentative synchrone (utilisable avant start()). Ne lève jamais."""
        ports = self._find_ports()
        if ports is None:
            return False
        in_name, out_name = ports
        try:
            self._listener.attach(in_name)
            self._sender.attach(out_name)
        except Exception as exc:
            log.warning("ouverture des ports MIDI impossible : %s", exc)
            self._release()
            return False
        self._connected = True
        log.info("Mighty connecté (entrée=%r, sortie=%r)", in_name, out_name)
        return True

    def _release(self):
        self._listener.detach()
        self._sender.detach()

    def _link_lost(self) -> bool:
        if not self._sender.is_open or not self._listener.is_open or self._listener.broken:
            return True
        return self._find_ports() is None

    # --- Boucle ---

    def run(self):
        while not self._stop_event.wait(self._poll_interval):
            try:
                if not self._tick():
                    break
            except Exception:
                # Une exception non gérée tuerait le thread : plus aucune
                # (re)connexion détectée jusqu'au redémarrage de l'appli.
                log.exception("erreur inattendue dans la surveillance MIDI")

    def _tick(self) -> bool:
        """Un tour de surveillance. False si l'arrêt a été demandé."""
        if self._connected:
            if self._link_lost():
                self._release()
                self._connected = False
                log.warning("Mighty déconnecté")
                self.connected_changed.emit(False)
        elif self.try_connect():
            # Laisse Windows finir d'énumérer le device avant que l'appli
            # lui repousse son état.
            if self._stop_event.wait(self._settle_delay):
                return False
            self.connected_changed.emit(True)
        return True

    def stop(self):
        self._stop_event.set()
        self.wait()
        self._release()
        self._connected = False
