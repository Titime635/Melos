"""
Fenêtre principale.

Deux onglets : "Dashboard" (positionnement libre des modules, cf
ui/dashboard_interface.py) est la vue principale désormais. "Classique"
garde l'ancien affichage empilé tel quel, comme vue de secours/référence —
pas de conflit entre les deux : ce sont des instances de panneaux séparées
mais branchées sur les mêmes AmpState/MidiSender, donc toujours synchronisées.
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QScrollArea
from qfluentwidgets import FluentWindow, FluentIcon, InfoBar, InfoBarPosition, NavigationItemPosition

from midi.protocol import PORT_KEYWORD
from state.amp_state import AmpState
from midi.sender import MidiSender
from ui.preset_panel import PresetPanel
from ui.tuner_panel import TunerPanel
from ui.drum_panel import DrumPanel
from ui.loop_panel import LoopPanel
from ui.setlist_panel import SetlistPanel
from ui.dashboard_interface import DashboardInterface
from ui.shortcuts_interface import ShortcutsInterface
from shortcuts.manager import ShortcutManager
from shortcuts.router import ActionRouter


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

        # La loop station utilise l'interface audio du Mighty : elle doit
        # suivre sa (dé)connexion (cf LoopPanel.on_device_availability_changed)
        state.connection_changed.connect(
            lambda connected: self.loop_panel.on_device_availability_changed(connected, PORT_KEYWORD)
        )


class MainWindow(FluentWindow):
    def __init__(self, state: AmpState, sender: MidiSender, shortcuts: ShortcutManager):
        super().__init__()
        self.setWindowTitle("Mighty Control")
        self.resize(1150, 900)

        self._state = state
        self._shortcuts = shortcuts
        self._banner: InfoBar | None = None

        # Ajouté en premier : c'est la vue par défaut à l'ouverture
        self.dashboard_interface = DashboardInterface(state, sender)
        self.addSubInterface(self.dashboard_interface, FluentIcon.LAYOUT, "Dashboard")

        self.home_interface = HomeInterface(state, sender)
        self.addSubInterface(self.home_interface, FluentIcon.VIEW, "Classique")

        # --- Raccourcis clavier ---
        # Ils pilotent la vue (Dashboard / Classique) que l'utilisateur regarde ; sur la page
        # Raccourcis elle-même, on garde la dernière vue de jeu visitée.
        self._control_view = self.dashboard_interface
        self.stackedWidget.currentChanged.connect(self._on_page_changed)
        self._router = ActionRouter(state, sender, self.active_view, parent=self)
        shortcuts.action_triggered.connect(self._router.handle, Qt.QueuedConnection)

        self.shortcuts_interface = ShortcutsInterface(shortcuts)
        self.addSubInterface(
            self.shortcuts_interface, FluentIcon.COMMAND_PROMPT, "Raccourcis", NavigationItemPosition.BOTTOM
        )
        # Interrupteur rapide (utile en jeu comme pour taper dans une autre appli)
        self.navigationInterface.addItem(
            routeKey="shortcuts_toggle",
            icon=FluentIcon.POWER_BUTTON,
            text="Raccourcis actifs",
            onClick=lambda: shortcuts.set_enabled(not shortcuts.enabled),
            selectable=False,
            position=NavigationItemPosition.BOTTOM,
        )
        self._refresh_shortcuts_toggle(shortcuts.enabled)
        shortcuts.enabled_changed.connect(self._refresh_shortcuts_toggle)

        # Indicateur de connexion permanent (barre de navigation, en bas)
        self.navigationInterface.addItem(
            routeKey="connection",
            icon=FluentIcon.CONNECT,
            text="Mighty connecté",
            onClick=None,
            selectable=False,
            position=NavigationItemPosition.BOTTOM,
        )
        self._refresh_connection_indicator(state.connected)
        state.connection_changed.connect(self._on_connection_changed)
        # Lancement sans Mighty : bandeau d'avertissement dès que la fenêtre est affichée
        if not state.connected:
            QTimer.singleShot(0, lambda: self._show_banner(False))

    # --- Raccourcis clavier ---

    def active_view(self):
        """Vue de jeu (Dashboard ou Classique) pilotée par les raccourcis."""
        return self._control_view

    def _on_page_changed(self, index: int):
        page = self.stackedWidget.widget(index)
        if hasattr(page, "loop_panel") and hasattr(page, "setlist_panel"):
            self._control_view = page

    def _refresh_shortcuts_toggle(self, enabled: bool):
        item = self.navigationInterface.widget("shortcuts_toggle")
        if item is None:
            return
        item.setText("Raccourcis actifs" if enabled else "Raccourcis coupés")
        item.setIcon(FluentIcon.POWER_BUTTON if enabled else FluentIcon.CANCEL)

    # --- Connexion au Mighty ---

    def _refresh_connection_indicator(self, connected: bool):
        item = self.navigationInterface.widget("connection")
        if item is None:
            return
        item.setText("Mighty connecté" if connected else "Mighty déconnecté")
        item.setIcon(FluentIcon.CONNECT if connected else FluentIcon.CANCEL)

    def _close_banner(self):
        if self._banner is not None:
            try:
                self._banner.close()
            except RuntimeError:
                pass  # déjà détruit
            self._banner = None

    def _show_banner(self, connected: bool):
        self._close_banner()
        if connected:
            # Confirmation brève qui s'efface seule
            InfoBar.success(
                title="Mighty connecté",
                content="Tes réglages ont été renvoyés à l'ampli.",
                isClosable=False,
                duration=2500,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        else:
            # Persistant tant que l'ampli est déconnecté (duration=-1)
            self._banner = InfoBar.warning(
                title="Mighty déconnecté",
                content="Tu peux continuer à éditer : les réglages seront renvoyés à l'ampli à la reconnexion.",
                isClosable=False,
                duration=-1,
                position=InfoBarPosition.TOP,
                parent=self,
            )

    def _on_connection_changed(self, connected: bool):
        self._refresh_connection_indicator(connected)
        self._show_banner(connected)

    def closeEvent(self, event):
        # Coupe proprement les flux audio des DEUX vues (instances séparées,
        # chacune la sienne) et désenregistre les touches globales
        self._shortcuts.shutdown()
        self.home_interface.loop_panel.stop()
        self.dashboard_interface.stop()
        super().closeEvent(event)