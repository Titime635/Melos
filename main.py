"""
Point d'entrée de l'application.
"""

import logging
import sys

import mido
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from qfluentwidgets import setTheme, Theme

from midi.connection_monitor import ConnectionMonitor
from midi.listener import MidiListener
from midi.sender import MidiSender
from midi.sync import DeviceSync, push_state
from shortcuts.manager import ShortcutManager
from state.amp_state import AmpState
from ui.main_window import MainWindow


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        print("Inputs :", mido.get_input_names())
        print("Outputs:", mido.get_output_names())
    except Exception as exc:
        print("Énumération des ports MIDI impossible :", exc)

    app = QApplication(sys.argv)
    setTheme(Theme.AUTO)  # suit le thème clair/sombre du système

    state = AmpState()  # restaure preset/batterie/tuner depuis app_settings.json

    # --- MIDI ---
    # Listener et sender vivent toute la durée de l'appli ; seuls leurs ports
    # sont ouverts/fermés par le moniteur (cf midi/connection_monitor.py).
    listener = MidiListener()
    sender = MidiSender()
    monitor = ConnectionMonitor(listener, sender)

    # Câblage des signaux MIDI -> état (une seule fois, jamais refait)
    listener.preset_changed.connect(state.on_preset_changed)
    listener.tuner_note.connect(state.on_tuner_note)
    listener.tuner_cent.connect(state.on_tuner_cent)
    listener.tuner_state.connect(state.on_tuner_state)
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
    window = MainWindow(state, sender, shortcuts)
    window.show()

    exit_code = app.exec()

    shortcuts.shutdown()
    monitor.stop()
    listener.stop()
    sender.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
