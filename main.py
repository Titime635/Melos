"""
Point d'entrée de l'application.
"""

import sys

import mido
from PySide6.QtWidgets import QApplication
from qfluentwidgets import setTheme, Theme

from midi.protocol import INPUT_NAME, OUTPUT_NAME, TUNER_REF_PITCH_440HZ
from midi.listener import MidiListener
from midi.sender import MidiSender
from state.amp_state import AmpState
from ui.main_window import MainWindow
from midi.connection_monitor import ConnectionMonitor


def main():
    print("Inputs :", mido.get_input_names())
    print("Outputs:", mido.get_output_names())

    app = QApplication(sys.argv)
    setTheme(Theme.AUTO)  # suit le thème clair/sombre du système

    state = AmpState()  # restaure preset/batterie/tuner depuis app_settings.json

    # --- MIDI : instances persistantes ---
    listener = MidiListener()  # Commence sans port spécifique
    sender = MidiSender(OUTPUT_NAME)  # Garde le nom par défaut pour l'initialisation

    # --- Moniteur de connexion ---
    connection_monitor = ConnectionMonitor(state, sender, listener)

    # Vérification synchrone des ports avant d'afficher la fenêtre
    # Pour éviter le flash "déconnecté" si l'ampli est branché
    input_available = any(name.startswith("NUX NMP-03") for name in mido.get_input_names())
    output_available = any(name.startswith("NUX NMP-03") for name in mido.get_output_names())
    if input_available and output_available:
        state.set_connected(True)  # État initial si device détecté
    else:
        state.set_connected(False)  # État initial si device non détecté

    # Câblage des signaux MIDI -> état (fait une seule fois)
    listener.preset_changed.connect(state.on_preset_changed)
    listener.tuner_note.connect(state.on_tuner_note)
    listener.tuner_cent.connect(state.on_tuner_cent)
    listener.tuner_state.connect(state.on_tuner_state)
    listener.drum_cc_received.connect(state.on_drum_cc)

    # Démarrer le moniteur de connexion
    connection_monitor.start()

    # --- UI ---
    window = MainWindow(state, sender)
    window.show()

    exit_code = app.exec()

    # Arrêt propre
    connection_monitor.stop()
    listener.stop()
    sender.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()