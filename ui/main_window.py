"""
Fenêtre principale.

Deux onglets : "Dashboard" (positionnement libre des modules, cf
ui/dashboard_interface.py) est la vue principale désormais. "Classique"
garde l'ancien affichage empilé tel quel, comme vue de secours/référence —
pas de conflit entre les deux : ce sont des instances de panneaux séparées
mais branchées sur les mêmes AmpState/MidiSender, donc toujours synchronisées.
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
from ui.dashboard_interface import DashboardInterface


class HomeInterface(QScrollArea):
    """Vue de secours/référence — l'ancien affichage empilé, conservé tel
    quel. Les panneaux sont des instances séparées de celles du Dashboard,
    mais pointent vers les mêmes AmpState/MidiSender donc restent synchro.
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
        self.resize(1150, 900)

        # Ajouté en premier : c'est la vue par défaut à l'ouverture
        self.dashboard_interface = DashboardInterface(state, sender)
        self.addSubInterface(self.dashboard_interface, FluentIcon.LAYOUT, "Dashboard")

        self.home_interface = HomeInterface(state, sender)
        self.addSubInterface(self.home_interface, FluentIcon.VIEW, "Classique")

    def closeEvent(self, event):
        # Coupe proprement les flux audio des DEUX vues (instances séparées,
        # chacune la sienne) et désenregistre les touches globales
        self.home_interface.loop_panel.stop()
        self.home_interface.setlist_panel.stop()
        self.dashboard_interface.stop()
        super().closeEvent(event)