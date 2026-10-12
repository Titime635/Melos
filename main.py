"""
Point d'entrée de l'application.
"""

import faulthandler
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

import mido
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

from audio import portaudio_utils
from midi.connection_monitor import ConnectionMonitor
from midi import port_graveyard
from midi.listener import MidiListener
from midi.sender import MidiSender
from midi.sync import DeviceSync, push_state
from shortcuts.manager import ShortcutManager
from state.amp_state import AmpState
from ui.main_window import MainWindow
from ui.theme import apply_theme
from settings import load_settings
from paths import CRASH_FILE, LOG_FILE


FREEZE_TIMEOUT_S = 10


def setup_diagnostics():
    """Journal + détecteur de gel. Si l'appli se fige, la pile de chaque thread est
    écrite dans melos_crash.log : c'est ce fichier qu'il faut transmettre pour comprendre où ça bloque."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            RotatingFileHandler(LOG_FILE, maxBytes=500_000, backupCount=1, encoding="utf-8"),
        ],
    )
    crash_fh = open(CRASH_FILE, "a", encoding="utf-8")
    crash_fh.write(f"\n=== lancement pid {os.getpid()} ===\n")
    crash_fh.flush()
    faulthandler.enable(file=crash_fh)  # plantage natif (segfault...)
    return crash_fh


def start_freeze_watchdog(crash_fh) -> QTimer:
    """Le thread Qt relance un compte à rebours chaque seconde ; s'il est bloqué plus de
    FREEZE_TIMEOUT_S, faulthandler écrit les piles de tous les threads."""
    def beat():
        faulthandler.dump_traceback_later(FREEZE_TIMEOUT_S, repeat=False, file=crash_fh)

    beat()
    timer = QTimer()
    timer.setInterval(1000)
    timer.timeout.connect(beat)
    timer.start()
    return timer


def main():
    crash_fh = setup_diagnostics()
    try:
        print("Inputs :", mido.get_input_names())
        print("Outputs:", mido.get_output_names())
    except Exception as exc:
        print("Énumération des ports MIDI impossible :", exc)

    app = QApplication(sys.argv)
    apply_theme(load_settings()["ui"]["theme"])  # « auto » suit le thème clair/sombre du système
    watchdog = start_freeze_watchdog(crash_fh)  # noqa: F841 (garde la référence)

    state = AmpState()  # restaure preset/batterie/tuner depuis app_settings.json

    # --- MIDI ---
    # Listener et sender vivent toute la durée de l'appli ; seuls leurs ports
    # sont ouverts/fermés par le moniteur (cf midi/connection_monitor.py).
    listener = MidiListener()
    sender = MidiSender()
    monitor = ConnectionMonitor(listener, sender)

    # Câblage des signaux MIDI -> état (une seule fois, jamais refait)
    listener.preset_changed.connect(state.on_preset_changed)
    listener.preset_changed.connect(lambda i: logging.getLogger("melos.midi").info("preset reçu de l'ampli : %d", i))
    listener.tuner_note.connect(state.on_tuner_note)
    listener.tuner_cent.connect(state.on_tuner_cent)
    listener.tuner_state.connect(state.on_tuner_state)
    listener.tuner_string.connect(state.on_tuner_string)
    listener.drum_cc_received.connect(state.on_drum_cc)
    listener.start()

    # Tentative synchrone AVANT de créer la fenêtre : si le Mighty est branché,
    # l'UI naît directement "connectée" (pas de flash "déconnecté" d'une seconde).
    # L'appli se lance de toute façon, branché ou non.
    connected = monitor.try_connect()
    state.set_connected(connected)
    if connected:
        # Renvoie au device les réglages restaurés (le device peut avoir démarré
        # sur autre chose)
        push_state(state, sender)

    # Les reconnexions ultérieures repoussent l'état via DeviceSync
    sync = DeviceSync(state, sender)  # noqa: F841 (garde la référence)
    monitor.connected_changed.connect(state.set_connected, Qt.QueuedConnection)
    monitor.start()

    # --- UI ---
    shortcuts = ShortcutManager()  # touches globales : aucune par défaut, réglées dans l'onglet Raccourcis
    window = MainWindow(state, sender, shortcuts, monitor)
    window.show()

    exit_code = app.exec()

    faulthandler.cancel_dump_traceback_later()
    shortcuts.shutdown()
    monitor.stop()
    listener.stop()
    sender.close()
    if portaudio_utils.closing_in_progress() or port_graveyard.has_abandoned():
        # Flux audio coincé ou ports MIDI abandonnés (Mighty débranché) : la sortie normale de Python
        # les détruirait (donc les fermerait) et se figerait, on quitte donc sans cérémonie.
        logging.shutdown()
        os._exit(exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()