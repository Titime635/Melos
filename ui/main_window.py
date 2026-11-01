"""
Fenêtre principale.

Deux onglets : "Dashboard" (positionnement libre des modules, cf
ui/dashboard_interface.py) est la vue principale désormais. "Classique"
garde l'ancien affichage empilé tel quel, comme vue de secours/référence —
pas de conflit entre les deux : ce sont des instances de panneaux séparées
mais branchées sur les mêmes AmpState/MidiSender, donc toujours synchronisées.
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QScrollArea
from qfluentwidgets import qconfig, FluentWindow, FluentIcon, InfoBar, InfoBarPosition, NavigationItemPosition

from midi.protocol import PORT_KEYWORD
from state.amp_state import AmpState
from midi.sender import MidiSender
from ui.preset_panel import PresetPanel
from ui.tuner_panel import TunerPanel
from ui.drum_panel import DrumPanel
from audio.audio_config import AudioConfig
from audio.loop_engine import LoopEngine
from ui.focus_guard import FocusGuard
from ui.loop_panel import LoopPanel
from ui.tempo_panel import TempoPanel
from ui.setlist_panel import SetlistPanel
from ui.dashboard_interface import DashboardInterface
from ui.settings_interface import SettingsInterface
from ui.tab_interface import TabInterface
from ui.shortcuts_interface import ShortcutsInterface
from ui.theme import apply_theme
from settings import load_settings
from shortcuts.manager import ShortcutManager, MODE_OFF, MODE_WINDOW, MODE_GLOBAL, typing_in_app
from state.undo import SettingsHistory, ShortcutsHistory, UndoStack
from ui import icons
from shortcuts.router import ActionRouter


POPUP_DURATION_MS = 4000  # les pop-ups d'état s'effacent seules

MODE_TEXT = {
    MODE_OFF: "Raccourcis désactivés",
    MODE_WINDOW: "Raccourcis : fenêtre active",
    MODE_GLOBAL: "Raccourcis : global",
}
MODE_TOOLTIP = {
    MODE_OFF: "Raccourcis désactivés — clic : passer en « fenêtre active »",
    MODE_WINDOW: "Raccourcis actifs seulement quand Mighty Control est au premier plan — clic : passer en « global »",
    MODE_GLOBAL: "Raccourcis actifs partout (même dans une autre appli) — clic : les désactiver",
}


class HomeInterface(QScrollArea):
    """Vue de secours/référence — l'ancien affichage empilé, conservé tel
    quel. Les panneaux sont des instances séparées de celles du Dashboard,
    mais pointent vers les mêmes AmpState/MidiSender donc restent synchro.
    """

    def __init__(self, state: AmpState, sender: MidiSender, loop_engine=None, audio=None, parent=None):
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

        # Tempo / signature / clic, partagés avec la batterie et les deux loop stations
        self.tempo_panel = TempoPanel(state.transport)
        layout.addWidget(self.tempo_panel)

        # Panneau 100% logiciel, ne parle pas MIDI
        self.loop_panel = LoopPanel(state.transport, loop_engine, audio)
        self.drum_panel.set_sync(self.loop_panel)  # batterie calée sur la mesure du looper
        self.tempo_panel.attach_loop_panel(self.loop_panel)
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
    def __init__(self, state: AmpState, sender: MidiSender, shortcuts: ShortcutManager, monitor=None):
        super().__init__()
        # Pas d'effet Mica : une fois la vue web (onglet Partition) affichée, Qt compose la fenêtre avec le GPU et les
        # zones « transparentes » du Mica (barre latérale des onglets) deviennent noires en thème clair. Fond uni à la place.
        self.setMicaEffectEnabled(False)
        self.setWindowTitle("Mighty Control")
        self.resize(1150, 900)

        self._state = state
        self._shortcuts = shortcuts
        self._banner: InfoBar | None = None

        # Une seule loop station (moteur + flux audio) pour les deux vues : un seul métronome, et la phase de la
        # batterie lancée depuis une vue vaut pour l'autre
        self._loop_engine = LoopEngine(self)
        self._monitor = monitor
        self._audio = AudioConfig(self._loop_engine, self)   # périphériques + tampon, réglés dans la page Réglages

        # Cliquer à côté d'un champ de texte le quitte (cf ui/focus_guard.py)
        self._focus_guard = FocusGuard(self)
        QApplication.instance().installEventFilter(self._focus_guard)

        # Ajouté en premier : c'est la vue par défaut à l'ouverture
        self.dashboard_interface = DashboardInterface(state, sender, self._loop_engine, self._audio)
        self.addSubInterface(self.dashboard_interface, FluentIcon.LAYOUT, "Dashboard")

        self.home_interface = HomeInterface(state, sender, self._loop_engine, self._audio)
        self.addSubInterface(self.home_interface, FluentIcon.VIEW, "Classique")

        self.tab_interface = TabInterface()
        self.addSubInterface(self.tab_interface, FluentIcon.MUSIC, "Partition")

        # --- Annuler / rétablir : une pile par page (cf state/undo.py) ---
        self._play_stack = UndoStack(self._apply_play_entry, parent=self)   # Dashboard + Classique
        self._settings_history = SettingsHistory(state, sender, self._play_stack, self._loop_engine, parent=self)
        self.dashboard_interface.layout_edited.connect(
            lambda before, after: self._play_stack.record("layout", "layout", before, after, "agencement du dashboard"))
        self._shortcuts_stack = UndoStack(self._apply_shortcuts_entry, parent=self)
        self._shortcuts_history = ShortcutsHistory(shortcuts, self._shortcuts_stack, parent=self)
        for sequences, redo in ((("Ctrl+Z",), False), (("Ctrl+Y", "Ctrl+Shift+Z"), True)):
            for seq in sequences:
                QShortcut(QKeySequence(seq), self, activated=lambda r=redo: self.undo_redo(r))

        # --- Raccourcis clavier ---
        # Ils pilotent la vue (Dashboard / Classique) que l'utilisateur regarde ; sur la page
        # Raccourcis elle-même, on garde la dernière vue de jeu visitée.
        self._control_view = self.dashboard_interface
        self.stackedWidget.currentChanged.connect(self._on_page_changed)
        self._router = ActionRouter(state, sender, self.active_view, parent=self)
        shortcuts.action_triggered.connect(self._router.handle, Qt.QueuedConnection)

        self.shortcuts_interface = ShortcutsInterface(shortcuts)
        self.addSubInterface(
            self.shortcuts_interface, icons.keyboard_icon(), "Raccourcis", NavigationItemPosition.BOTTOM
        )
        self.settings_interface = SettingsInterface(self._audio, monitor, shortcuts)
        self.addSubInterface(self.settings_interface, FluentIcon.SETTING, "Réglages", NavigationItemPosition.BOTTOM)
        self.settings_interface.open_shortcuts_requested.connect(
            lambda: self.switchTo(self.shortcuts_interface))
        self.settings_interface.dashboard_reset_requested.connect(self.dashboard_interface.reset_layout)
        self.settings_interface.preset_names_reset.connect(self._reload_preset_names)
        self.settings_interface.settings_replaced.connect(self._apply_replaced_settings)
        qconfig.themeChanged.connect(lambda *_: self.shortcuts_interface_item_refresh())
        # Interrupteur rapide à 3 états (désactivé / fenêtre active / global)
        self.navigationInterface.addItem(
            routeKey="shortcuts_toggle",
            icon=icons.toggle_icon(shortcuts.mode),
            text=MODE_TEXT[shortcuts.mode],
            onClick=shortcuts.cycle_mode,
            selectable=False,
            tooltip=MODE_TOOLTIP[shortcuts.mode],
            position=NavigationItemPosition.BOTTOM,
        )
        self._refresh_shortcuts_toggle(shortcuts.mode)
        shortcuts.mode_changed.connect(self._refresh_shortcuts_toggle)

        # Indicateur de connexion permanent (barre de navigation, en bas)
        self.navigationInterface.addItem(
            routeKey="connection",
            icon=icons.plug_icon(state.connected),
            text="Mighty connecté",
            onClick=None,
            selectable=False,
            tooltip="État de la connexion USB avec le Mighty Plug Pro",
            position=NavigationItemPosition.BOTTOM,
        )
        self._refresh_connection_indicator(state.connected)
        state.connection_changed.connect(self._on_connection_changed)
        # Lancement sans Mighty : bandeau d'avertissement dès que la fenêtre est affichée
        if not state.connected:
            QTimer.singleShot(0, lambda: self._show_banner(False))

    # --- Réglages remplacés (import / réinitialisation, page Réglages) ---

    def _reload_preset_names(self):
        for panel in (self.dashboard_interface.preset_panel, self.home_interface.preset_panel):
            panel.reload_names()

    def _apply_replaced_settings(self):
        cfg = load_settings()
        apply_theme(cfg["ui"]["theme"])
        self._audio.reload_from_settings()
        if self._monitor is not None:
            self._monitor.apply_preferences()
        self.dashboard_interface.reload_from_settings()
        self._reload_preset_names()
        sc = cfg["shortcuts"]
        mode = sc.get("mode") or (MODE_GLOBAL if sc.get("enabled", True) else MODE_OFF)
        self._shortcuts.restore(mode, sc.get("bindings") or {})
        for stack in (self._play_stack, self._shortcuts_stack):
            stack.clear()

    # --- Annuler / rétablir ---

    def _apply_play_entry(self, kind: str, values) -> bool:
        if kind == "layout":
            self.dashboard_interface.apply_layout(values)
            return True
        return self._settings_history.apply(values)

    def _apply_shortcuts_entry(self, kind: str, values) -> bool:
        return self._shortcuts_history.apply(values)

    def undo_redo(self, redo: bool = False) -> str:
        """Annule / rétablit le dernier changement de la page affichée. Renvoie le texte affiché."""
        if typing_in_app() or self._shortcuts.capturing:
            return ""   # champ de texte : son propre Ctrl+Z ; capture de touche : Ctrl+Z est la touche choisie
        page = self.stackedWidget.currentWidget()
        if page is self.settings_interface:
            return ""   # rien à annuler ici : les réglages s'appliquent tout de suite
        if page is self.shortcuts_interface:
            stack, accept = self._shortcuts_stack, None
        else:
            on_dashboard = page is self.dashboard_interface
            stack, accept = self._play_stack, (lambda e: e.kind != "layout" or on_dashboard)
        entry = stack.redo(accept) if redo else stack.undo(accept)
        if entry is not None:
            text = f"{'Rétabli' if redo else 'Annulé'} : {entry.label}"
        elif self._settings_history.refused and stack is self._play_stack:
            text = self._settings_history.refused
        else:
            text = "Rien à rétablir" if redo else "Rien à annuler"
        InfoBar.info(title=text, content="", isClosable=False, duration=1500,
                     position=InfoBarPosition.BOTTOM, parent=self)
        return text

    # --- Raccourcis clavier ---

    def active_view(self):
        """Vue de jeu (Dashboard ou Classique) pilotée par les raccourcis."""
        return self._control_view

    def _on_page_changed(self, index: int):
        page = self.stackedWidget.widget(index)
        if hasattr(page, "loop_panel") and hasattr(page, "setlist_panel"):
            self._control_view = page

    def shortcuts_interface_item_refresh(self):
        item = self.navigationInterface.widget(self.shortcuts_interface.objectName())
        if item is not None:
            item.setIcon(icons.keyboard_icon())

    def _refresh_shortcuts_toggle(self, mode: str):
        item = self.navigationInterface.widget("shortcuts_toggle")
        if item is None:
            return
        item.setText(MODE_TEXT[mode])
        item.setIcon(icons.toggle_icon(mode))
        item.setToolTip(MODE_TOOLTIP[mode])
        item.update()

    # --- Connexion au Mighty ---

    def _refresh_connection_indicator(self, connected: bool):
        item = self.navigationInterface.widget("connection")
        if item is None:
            return
        item.setText("Mighty connecté" if connected else "Mighty déconnecté")
        item.setIcon(icons.plug_icon(connected))
        # Texte coloré (vert / rouge) pour qu'on voie l'état d'un coup d'œil
        color = QColor(icons.GREEN if connected else icons.RED)
        item.setLightTextColor(color)
        item.setDarkTextColor(color)
        item.update()

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
                duration=POPUP_DURATION_MS,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        else:
            # S'efface seul : l'indicateur de la barre latérale reste, lui, permanent
            self._banner = InfoBar.warning(
                title="Mighty déconnecté",
                content="Tu peux continuer à éditer : les réglages seront renvoyés à l'ampli à la reconnexion.",
                isClosable=False,
                duration=POPUP_DURATION_MS,
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
        QApplication.instance().removeEventFilter(self._focus_guard)
        self.home_interface.loop_panel.stop()
        self.dashboard_interface.stop()
        self.tab_interface.stop()
        super().closeEvent(event)