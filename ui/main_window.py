"""
Fenêtre principale.

Deux onglets : "Dashboard" (positionnement libre des modules, cf
ui/dashboard_interface.py) est la vue principale désormais. "Classique"
garde l'ancien affichage empilé tel quel, comme vue de secours/référence —
pas de conflit entre les deux : ce sont des instances de panneaux séparées
mais branchées sur les mêmes AmpState/MidiSender, donc toujours synchronisées.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QLabel, QHBoxLayout
from qfluentwidgets import FluentWindow, FluentIcon, InfoBar, InfoBarPosition

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

        # Indicateur de connexion permanent
        self._connection_indicator = QLabel()
        self._connection_indicator.setFixedSize(12, 12)
        self._update_connection_indicator(state.connected)

        # Ajouté en premier : c'est la vue par défaut à l'ouverture
        self.dashboard_interface = DashboardInterface(state, sender)
        self.addSubInterface(self.dashboard_interface, FluentIcon.LAYOUT, "Dashboard")

        self.home_interface = HomeInterface(state, sender)
        self.addSubInterface(self.home_interface, FluentIcon.VIEW, "Classique")

        # Ajouter l'indicateur de connexion dans le coin inférieur droit de la fenêtre
        # Nous allons l'ajouter à la barre de status ou créer un container personnalisé
        # Pour simplifier, nous l'ajouterons comme coin personnalisé de la fenêtre
        # Note: FluentWindow n'a pas de barre de status par défaut, donc nous allons
        # utiliser une approche alternative - ajouter un widget en overlay ou dans le layout
        # Pour cette implémentation, nous allons ajouter l'indicateur dans le coin supérieur droit
        # de chaque sous-interface, mais cela serait complexe.
        # Au lieu de cela, nous allons modifier l'approche: ajouter un indicateur dans la barre de titre
        # ou simplement gérer les indicateurs via InfoBar et un petit widget dans le coin.

        # Pour cette version, nous allons:
        # 1. Utiliser InfoBar pour la bannière d'avertissement persistante (déconnecté)
        # 2. Utiliser InfoBar pour la confirmation brève "Connecté"
        # 3. Ajouter un indicateur permanent simple dans le coin inférieur droit de la fenêtre principale

        # Créer un container pour l'indicateur en bas à droite
        from PySide6.QtWidgets import QStatusBar
        status_bar = QStatusBar()
        status_bar.addPermanentWidget(self._connection_indicator)
        self.setStatusBar(status_bar)

        # Surveillance de l'état de connexion
        state.connection_changed.connect(self._on_connection_state_changed)

        # État initial basé sur l'état actuel
        self._update_connection_indicator(state.connected)

    def closeEvent(self, event):
        # Coupe proprement les flux audio des DEUX vues (instances séparées,
        # chacune la sienne) et désenregistre les touches globales
        self.home_interface.loop_panel.stop()
        self.home_interface.setlist_panel.stop()
        self.dashboard_interface.stop()
        super().closeEvent(event)

    def _update_connection_indicator(self, connected: bool):
        """Met à jour l'indicateur permanent de connexion."""
        if connected:
            # Vert pour connecté
            self._connection_indicator.setStyleSheet(
                "background-color: #22c55e; border-radius: 6px;"
            )  # vert-500
        else:
            # Rouge pour déconnecté
            self._connection_indicator.setStyleSheet(
                "background-color: #ef4444; border-radius: 6px;"
            )  # rouge-500

    def _on_connection_state_changed(self, connected: bool):
        """Gère les changements d'état de connexion."""
        # Mettre à jour l'indicateur permanent
        self._update_connection_indicator(connected)

        if connected:
            # Device connecté : afficher une confirmation brève "Connecté"
            InfoBar.success(
                title="Connecté",
                content="Le Mighty Plug Pro est maintenant connecté",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                duration=2000,  # 2 secondes
                parent=self,
            )
        else:
            # Device déconnecté : afficher une bannière d'avertissement persistante
            InfoBar.warning(
                title="Déconnecté",
                content="Le Mighty Plug Pro est déconnecté. Certaines fonctionnalités sont limitées.",
                orient=Qt.Horizontal,
                isClosable=False,  # Persistante jusqu'à reconnexion
                position=InfoBarPosition.TOP_RIGHT,
                duration=-1,  # Persistante
                parent=self,
            )