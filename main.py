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


def main():
    print("Inputs :", mido.get_input_names())
    print("Outputs:", mido.get_output_names())

    app = QApplication(sys.argv)
    setTheme(Theme.AUTO)  # suit le thème clair/sombre du système

    state = AmpState()  # restaure preset/batterie/tuner depuis app_settings.json

    # --- MIDI ---
    listener = MidiListener(INPUT_NAME)
    sender = MidiSender(OUTPUT_NAME)

    # Câblage des signaux MIDI -> état
    listener.preset_changed.connect(state.on_preset_changed)
    listener.tuner_note.connect(state.on_tuner_note)
    listener.tuner_cent.connect(state.on_tuner_cent)
    listener.tuner_state.connect(state.on_tuner_state)
    listener.drum_cc_received.connect(state.on_drum_cc)

    listener.start()

    # Renvoie au device les réglages restaurés (le device peut avoir démarré
    # sur autre chose, ou avoir été débranché entre deux sessions)
    sender.set_preset(state.current_preset)
    sender.drum_enable(state.drum_enabled)
    sender.drum_set_style(state.drum_style)
    sender.drum_set_level(state.drum_level)
    sender.drum_set_eq(state.drum_bass, state.drum_middle, state.drum_treble)
    sender.tuner_enable(on=state.tuner_requested, mode=state.tuner_mode, ref_pitch=TUNER_REF_PITCH_440HZ)

    # --- UI ---
    window = MainWindow(state, sender)
    window.show()

    exit_code = app.exec()

    listener.stop()
    sender.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()