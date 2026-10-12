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

from settings import load_settings
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
        self._current: tuple[str, str] | None = None
        self._last_enum_error: str | None = None  # pour ne pas répéter le même avertissement chaque seconde
        self._reconnect = False   # reconnexion demandée (changement de port depuis la page Réglages)
        self.mode = "auto"        # "auto" : cherche le Mighty ; "manual" : ports imposés
        self.manual_in: str | None = None
        self.manual_out: str | None = None
        self.reload_preferences()

    @property
    def connected(self) -> bool:
        return self._connected

    # --- Choix du port (page Réglages) ---

    def reload_preferences(self):
        cfg = load_settings()["midi"]
        self.mode = "manual" if cfg.get("mode") == "manual" else "auto"
        self.manual_in = cfg.get("input_name")
        self.manual_out = cfg.get("output_name")

    def apply_preferences(self):
        """Relit le choix de port et force une reconnexion (le lien actuel est refermé au prochain tour)."""
        self.reload_preferences()
        self._reconnect = True

    @staticmethod
    def list_ports() -> tuple[list[str], list[str]]:
        try:
            return list(mido.get_input_names()), list(mido.get_output_names())
        except Exception as exc:
            log.warning("énumération des ports MIDI impossible : %s", exc)
            return [], []

    @property
    def current_ports(self) -> tuple[str, str] | None:
        return self._current

    # --- Détection / ouverture ---

    def _find_ports(self) -> tuple[str, str] | None:
        """(entrée, sortie) du Mighty si les deux sont listés, sinon None."""
        try:
            inputs, outputs = mido.get_input_names(), mido.get_output_names()
            if self.mode == "manual":
                in_name = self.manual_in if self.manual_in in inputs else None
                out_name = self.manual_out if self.manual_out in outputs else None
            else:
                in_name, out_name = protocol.find_port(inputs), protocol.find_port(outputs)
        except Exception as exc:
            if str(exc) != self._last_enum_error:
                log.warning("énumération des ports MIDI impossible : %s", exc)
                self._last_enum_error = str(exc)
            return None
        self._last_enum_error = None
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
        self._current = (in_name, out_name)
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
            if self._reconnect or self._link_lost():
                self._reconnect = False
                self._release()
                self._connected = False
                self._current = None
                log.warning("Mighty déconnecté")
                self.connected_changed.emit(False)
        else:
            self._reconnect = False   # déjà déconnecté : le prochain essai relit de toute façon le choix de port
            if not self.try_connect():
                return True
            # Laisse Windows finir d'énumérer le device avant que l'appli
            # lui repousse son état.
            if self._stop_event.wait(self._settle_delay):
                return False
            self.connected_changed.emit(True)
        return True

    def stop(self):
        self._stop_event.set()
        self.wait(3000)  # jamais d'attente infinie à la fermeture de l'appli
        self._release()
        self._connected = False