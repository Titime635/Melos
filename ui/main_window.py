"""
Fenêtre principale.

Onglets : "Dashboard" (positionnement libre des modules, cf
ui/dashboard_interface.py) est la vue principale désormais. "Classique"
garde l'ancien affichage empilé tel quel, comme vue de secours/référence —
pas de conflit entre les deux : ce sont des instances de panneaux séparées
mais branchées sur les mêmes AmpState/MidiSender, donc toujours synchronisées.
"""

import logging

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QScrollArea
from qfluentwidgets import qconfig, FluentWindow, FluentIcon, InfoBar, InfoBarPosition, NavigationItemPosition

from midi.protocol import PORT_KEYWORD
from state.amp_state import AmpState
from midi.sender import MidiSender
from ui.preset_panel import PresetPanel, SlotNames
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
from ui.editor_interface import EditorInterface
from ui.shortcuts_interface import ShortcutsInterface
from ui.theme import INSTRUMENT_COLORS, MODULE_COLORS, apply_theme, page_icon as _page_icon, window_background
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

    def __init__(self, state: AmpState, sender: MidiSender, loop_engine=None, audio=None, parent=None, names=None):
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

        self.preset_panel = PresetPanel(state, sender, names=names)
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
        self.setlist_panel = SetlistPanel(state, sender, names=names)
        layout.addWidget(self.setlist_panel)

        layout.addStretch()
        self.setWidget(content)

        # La loop station utilise l'interface audio du Mighty : elle doit
        # suivre sa (dé)connexion (cf LoopPanel.on_device_availability_changed)
        state.connection_changed.connect(
            lambda connected: self.loop_panel.on_device_availability_changed(connected, PORT_KEYWORD)
        )


class MainWindow(FluentWindow):
    def __init__(self, state: AmpState, sender: MidiSender, shortcuts: ShortcutManager, monitor=None, editor=None):
        super().__init__()
        self.setCustomBackgroundColor(*window_background())      # même fond de page que l'onglet Partition
        # Pas d'effet Mica : une fois la vue web (onglet Partition) affichée, Qt compose la fenêtre avec le GPU et les
        # zones « transparentes » du Mica (barre latérale des onglets) deviennent noires en thème clair. Fond uni à la place.
        self.setMicaEffectEnabled(False)
        self.setWindowTitle("Mighty Control")
        self.stackedWidget.setAnimationEnabled(False)       # pas de glissement de page vers le haut au changement d'onglet : ça donne une impression de lenteur
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

        # Noms d'emplacements : UNE source pour le Dashboard, Classique, setlist et éditeur (cf ui/preset_panel.py)
        self.names = SlotNames(editor[0], editor[1], self) if editor else SlotNames(parent=self)

        # Ajouté en premier : c'est la vue par défaut à l'ouverture
        self.dashboard_interface = DashboardInterface(state, sender, self._loop_engine, self._audio, names=self.names)
        self.addSubInterface(self.dashboard_interface, _page_icon(FluentIcon.LAYOUT, MODULE_COLORS["setlist"]), "Dashboard")

        self.home_interface = HomeInterface(state, sender, self._loop_engine, self._audio, names=self.names)
        self.addSubInterface(self.home_interface, _page_icon(FluentIcon.VIEW, MODULE_COLORS["tuner"]), "Classique")

        self.tab_interface = TabInterface()
        self.tab_interface.set_amp(state, sender, self.names)   # changements de preset posés sur la partition
        self.addSubInterface(self.tab_interface, _page_icon(FluentIcon.MUSIC, INSTRUMENT_COLORS["guitar"]), "Partition")

        # Éditeur de presets du Mighty + bibliothèque (cf editor/ et ui/editor_interface.py)
        self._editor_service = editor[0] if editor else None
        self.editor_interface = None
        if editor:
            self.editor_interface = EditorInterface(editor[0], editor[1], state, names=self.names)
            self.addSubInterface(self.editor_interface, _page_icon(FluentIcon.EDIT, MODULE_COLORS["loop"]), "Éditeur")

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

        # Ctrl+S : sur la page Éditeur, renvoie vers l'ampli le preset édité (là où il est déjà chargé)
        save = QShortcut(QKeySequence(QKeySequence.Save), self)
        save.setContext(Qt.WindowShortcut)
        save.activated.connect(self.save_current)

        # F11 : plein écran fenêtré (sans bordure, sans barre de titre) ; F11 de nouveau revient à l'état d'avant
        self._was_maximized = False
        sc = QShortcut(QKeySequence(Qt.Key_F11), self)
        sc.setContext(Qt.WindowShortcut)
        sc.activated.connect(self.toggle_fullscreen)

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
        self.names.reload()   # les panneaux Presets, la setlist et l'éditeur suivent via `names.changed`

    def _apply_replaced_settings(self):
        cfg = load_settings()
        apply_theme(cfg["ui"]["theme"])
        self.setCustomBackgroundColor(*window_background())
        self._audio.reload_from_settings()
        if self._monitor is not None:
            self._monitor.apply_preferences()
        self.dashboard_interface.reload_from_settings()
        self._reload_preset_names()
        self.tab_interface.library.reload()
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

    def save_current(self):
        if not self._shortcuts.capturing and self.stackedWidget.currentWidget() is self.editor_interface:
            self.editor_interface.save_current()

    def undo_redo(self, redo: bool = False) -> str:
        """Annule / rétablit le dernier changement de la page affichée. Renvoie le texte affiché."""
        if typing_in_app() or self._shortcuts.capturing:
            return ""   # champ de texte : son propre Ctrl+Z ; capture de touche : Ctrl+Z est la touche choisie
        page = self.stackedWidget.currentWidget()
        if page is self.settings_interface:
            return ""   # rien à annuler ici : les réglages s'appliquent tout de suite
        if page is self.editor_interface:
            text = self.editor_interface.undo_redo(redo)     # historique propre à l'éditeur (copies de travail)
            InfoBar.info(title=text, content="", isClosable=False, duration=1500,
                         position=InfoBarPosition.BOTTOM, parent=self)
            return text
        if page is self.tab_interface:
            text = self.tab_interface.undo_redo(redo)        # historique propre à la page Partition
            InfoBar.info(title=text, content="", isClosable=False, duration=1500,
                         position=InfoBarPosition.BOTTOM, parent=self)
            return text
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

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showMaximized() if self._was_maximized else self.showNormal()
        else:
            self._was_maximized = self.isMaximized()
            self.showFullScreen()
        self._sync_titlebar()
        for ms in (60, 300):                                 # Windows termine le changement d'état après coup
            QTimer.singleShot(ms, self._sync_titlebar)

    def _sync_titlebar(self):
        """Barre de titre (et ses boutons réduire / agrandir / fermer) cachée en plein écran, remise en place au retour."""
        bar = getattr(self, "titleBar", None)
        if bar is None:
            return
        full = self.isFullScreen()
        bar.setVisible(not full)
        if not full:
            bar.move(46, 0)
            bar.resize(self.width() - 46, bar.height())
            for name in ("minBtn", "maxBtn", "closeBtn"):
                btn = getattr(bar, name, None)
                if btn is not None:
                    btn.show()
            bar.raise_()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:         # aussi quand on sort du plein écran autrement que par F11
            QTimer.singleShot(0, self._sync_titlebar)

    # --- Fenêtre maximisée qui déborde sur la barre des tâches ---
    # Si le contenu a un instant dépassé la taille de l'écran (ex. liste de vidéos aux titres longs), Windows garde la
    # fenêtre à la taille de l'écran ENTIER : la barre de lecture passe sous la barre des tâches. On détecte le
    # débordement et on re-maximise, ce qui recalcule la taille sur la zone utile.
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.isMaximized() and not getattr(self, "_fixing_overflow", False):
            QTimer.singleShot(0, self._fix_maximized_overflow)

    def _fix_maximized_overflow(self):
        screen = self.screen()
        if screen is None or not self.isMaximized() or getattr(self, "_fixing_overflow", False):
            return
        avail = screen.availableGeometry()
        g = self.geometry()
        # « maximisée » d'après sa taille (l'état Qt peut être faux) : couvre presque tout l'écran mais dépasse la zone utile
        if g.height() <= avail.height() + 1 and g.width() <= avail.width() + 16:
            return
        logging.getLogger("melos.window").warning("débordement détecté (%dx%d pour une zone utile de %dx%d) : correction",
                                                  g.width(), g.height(), avail.width(), avail.height())
        self._fixing_overflow = True
        self.showNormal()
        self.showMaximized()
        QTimer.singleShot(400, lambda: setattr(self, "_fixing_overflow", False))

    def closeEvent(self, event):
        # Coupe proprement les flux audio des DEUX vues (instances séparées,
        # chacune la sienne) et désenregistre les touches globales
        self._shortcuts.shutdown()
        QApplication.instance().removeEventFilter(self._focus_guard)
        self.home_interface.loop_panel.stop()
        self.dashboard_interface.stop()
        self.tab_interface.stop()
        if self._editor_service is not None:
            self._editor_service.shutdown()
        super().closeEvent(event)