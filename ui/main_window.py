"""
Fenêtre principale.

Onglet unique pour l'instant : presets, tuner, batterie/EQ, loop station PC,
setlist. Passera à une navigation par onglets si ça devient trop chargé.
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QScrollArea
from qfluentwidgets import FluentWindow, FluentIcon

from state.amp_state import AmpState
from midi.sender import MidiSender
from ui.preset_panel import PresetPanel
from ui.tuner_panel import TunerPanel
from ui.drum_panel import DrumPanel
from ui.loop_panel import LoopPanel
from ui.setlist_panel import SetlistPanel


class HomeInterface(QScrollArea):
    """Onglet unique pour l'instant — deviendra le premier de plusieurs.

    Passé en QScrollArea : avec 5 panneaux (dont batterie/EQ et loop station
    qui ont pas mal de contrôles chacun), le contenu dépasse largement la
    hauteur de la fenêtre.
    """

    def __init__(self, state: AmpState, sender: MidiSender, parent=None):
        super().__init__(parent)
        self.setObjectName("HomeInterface")  # requis par FluentWindow pour la navigation
        self.setWidgetResizable(True)
        # Fond transparent : une QScrollArea garde sinon la couleur "Base" de
        # la palette (souvent blanche), ce qui casserait le thème sombre.
        self.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        self.preset_panel = PresetPanel(state, sender)
        layout.addWidget(self.preset_panel)

        self.tuner_panel = TunerPanel(state, sender)
        layout.addWidget(self.tuner_panel)

        self.drum_panel = DrumPanel(state, sender)
        layout.addWidget(self.drum_panel)

        # Panneau 100% logiciel, ne dépend ni de state ni de sender (pas de MIDI)
        self.loop_panel = LoopPanel()
        layout.addWidget(self.loop_panel)

        # Contrairement à loop_panel, la setlist parle bien au device (elle
        # envoie le preset de chaque étape) : elle a donc besoin de state+sender
        self.setlist_panel = SetlistPanel(state, sender)
        layout.addWidget(self.setlist_panel)

        layout.addStretch()
        self.setWidget(content)


class MainWindow(FluentWindow):
    def __init__(self, state: AmpState, sender: MidiSender):
        super().__init__()
        self.setWindowTitle("Mighty Control")
        self.resize(900, 700)

        self.home_interface = HomeInterface(state, sender)
        self.addSubInterface(self.home_interface, FluentIcon.HOME, "Accueil")

    def closeEvent(self, event):
        # Coupe proprement le flux audio de la loop station (sinon PortAudio
        # peut rester accroché) et désenregistre les touches globales
        self.home_interface.loop_panel.stop()
        self.home_interface.setlist_panel.stop()
        super().closeEvent(event)