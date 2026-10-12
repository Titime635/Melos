"""
Onglet "Dashboard" — tuilage natif Qt (QMainWindow embarqué + QDockWidget),
comme Unity/VSCode : aucun espace mort, splitters natifs entre modules
adjacents, taille minimale dérivée automatiquement du contenu réel de
chaque panneau. Pas de regroupement en onglets (division uniquement, choix
explicite) : cf ui/dashboard/dock_area.py.

Bascule Édition/Performance : en Performance (par défaut), tout est
verrouillé — aucun drag/resize/réglage possible, pour ne rien décaler ou
modifier par erreur pendant un set live. En Édition, les bandes de titre
colorées deviennent des poignées de drag natives, chaque module peut être
replié ou supprimé (bouton "+" pour le rajouter ensuite), et le CONTENU de
chaque module est désactivé (cf dock_widget.py) — on réarrange, on ne
touche pas aux réglages.

Les panneaux sont les mêmes que dans l'onglet Classique (modules adaptatifs à leur taille). Ce sont des
instances SÉPARÉES de celles de l'onglet Classique, mais pointent vers les
mêmes AmpState/MidiSender : les deux vues restent synchronisées
automatiquement. LoopPanel et SetlistPanel ont chacun leur propre flux
audio/leurs propres touches globales — d'où stop() à appeler sur CES
instances-ci en plus de celles de l'onglet Classique (cf MainWindow.closeEvent).

Phase 1 : arrangement de départ figé (mesuré sur les tailles réelles des
panneaux), pas encore sauvegardable entre deux lancements (workspaces,
phase 3).
"""

import logging

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from qfluentwidgets import SegmentedWidget, TransparentDropDownToolButton, RoundMenu, Action, FluentIcon

from settings import load_settings, update_settings
from state.amp_state import AmpState
from midi.protocol import PORT_KEYWORD
from midi.sender import MidiSender
from ui.module_card import MODULE_COLORS
from ui.preset_panel import PresetPanel
from ui.tuner_panel import TunerPanel
from ui.drum_panel import DrumPanel
from ui.loop_panel import LoopPanel
from ui.tempo_panel import TempoPanel
from ui.setlist_panel import SetlistPanel
from ui.dashboard.dock_area import DashboardDockArea

# Couleur d'identité de chaque module (même palette que les couleurs de
# preset, pour rester cohérent visuellement dans toute l'appli)
ACCENT_COLORS = MODULE_COLORS

log = logging.getLogger("melos.dashboard")

TITLES = {
    "presets": "Presets",
    "tuner": "Tuner",
    "drums": "Batterie",
    "loop": "Loop station",
    "tempo": "Tempo",
    "setlist": "Setlist",
}


class DashboardInterface(QWidget):
    layout_edited = Signal(object, object)   # (agencement avant, agencement après) — cf state/undo.py

    def __init__(self, state: AmpState, sender: MidiSender, loop_engine=None, audio=None, parent=None):
        super().__init__(parent)
        self.setObjectName("DashboardInterface")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        mode_row = QHBoxLayout()
        self._mode_switcher = SegmentedWidget()
        self._mode_switcher.addItem("performance", "Performance", lambda: self._set_mode(False))
        self._mode_switcher.addItem("edit", "Édition", lambda: self._set_mode(True))
        mode_row.addWidget(self._mode_switcher)

        # "+" pour rajouter un module supprimé — visible seulement en édition
        self._add_btn = TransparentDropDownToolButton(FluentIcon.ADD)
        self._add_btn.setToolTip("Rajouter un module supprimé")
        self._add_menu = RoundMenu(parent=self)
        self._add_btn.setMenu(self._add_menu)
        mode_row.addWidget(self._add_btn)

        mode_row.addStretch()
        layout.addLayout(mode_row)

        self._dock_area = DashboardDockArea()
        self._dock_area.modules_hidden_changed.connect(self._refresh_add_menu)
        layout.addWidget(self._dock_area, stretch=1)

        # Instances séparées de celles de l'onglet Classique (cf docstring du module), sauf le moteur
        # de la loop station, partagé (`loop_engine`) : un seul flux audio, un seul clic.
        self._loop_panel = LoopPanel(state.transport, loop_engine, audio)
        self._drum_panel = DrumPanel(state, sender)
        self._drum_panel.set_sync(self._loop_panel)  # batterie calée sur la mesure du looper
        self._tempo_panel = TempoPanel(state.transport)
        self._tempo_panel.attach_loop_panel(self._loop_panel)
        self._setlist_panel = SetlistPanel(state, sender)
        self._preset_panel = PresetPanel(state, sender)
        panels = {
            "presets": self._preset_panel,
            "tuner": TunerPanel(state, sender),
            "drums": self._drum_panel,
            "loop": self._loop_panel,
            "tempo": self._tempo_panel,
            "setlist": self._setlist_panel,
        }

        for module_id, content in panels.items():
            self._dock_area.add_module(module_id, TITLES[module_id], ACCENT_COLORS[module_id], content)

        # La loop station utilise l'interface audio du Mighty : elle doit
        # suivre sa (dé)connexion (cf LoopPanel.on_device_availability_changed)
        state.connection_changed.connect(
            lambda connected: self._loop_panel.on_device_availability_changed(connected, PORT_KEYWORD)
        )

        self._build_default_layout()
        self._restore_layout()
        self._refresh_add_menu()

        self._mode_switcher.setCurrentItem("performance")
        self._set_mode(False)

    def _build_default_layout(self):
        """Deux colonnes : presets/tuner/batterie à gauche (empilés),
        loop station/tempo/setlist à droite (plus larges, empilés aussi) — mesuré
        sur les tailles réelles des panneaux."""
        d = self._dock_area
        d.split("presets", "loop", Qt.Horizontal)
        d.split("presets", "tuner", Qt.Vertical)
        d.split("tuner", "drums", Qt.Vertical)
        d.split("loop", "tempo", Qt.Vertical)
        d.split("tempo", "setlist", Qt.Vertical)

        d.resize_docks(["presets", "loop"], [404, 682], Qt.Horizontal)
        d.resize_docks(["presets", "tuner", "drums"], [160, 320, 220], Qt.Vertical)
        d.resize_docks(["loop", "tempo", "setlist"], [320, 270, 230], Qt.Vertical)
        self._default_layout = d.layout_snapshot()   # pour « Réinitialiser le Dashboard » (page Réglages)

    def _set_mode(self, edit: bool):
        self._dock_area.set_edit_mode(edit)
        self._add_btn.setVisible(edit)
        if not edit and hasattr(self, "_saved_layout"):
            self.save_layout()   # fin de l'édition : l'agencement choisi est enregistré

    # --- Agencement sauvegardé (app_settings.json, section "dashboard") ---

    def _restore_layout(self):
        cfg = load_settings()["dashboard"]
        if self._dock_area.restore_layout(cfg.get("state"), list(cfg.get("hidden") or [])):
            log.info("agencement du Dashboard restauré")
        self._saved_layout = self._dock_area.layout_snapshot()
        # Les tailles se règlent aussi à la souris en mode Performance, et les modules supprimés / rajoutés
        # changent l'agencement : on regarde régulièrement s'il a bougé plutôt que de brancher chaque cas.
        self._layout_timer = QTimer(self)
        self._layout_timer.setInterval(400)
        self._layout_timer.timeout.connect(self.save_layout)
        self._layout_timer.start()

    def save_layout(self):
        snapshot = self._dock_area.layout_snapshot()
        size = self._dock_area.size()
        resized, self._last_size = size != getattr(self, "_last_size", size), size
        if snapshot == self._saved_layout:
            return
        previous, self._saved_layout = self._saved_layout, snapshot
        update_settings({"dashboard": {"state": snapshot[0], "hidden": snapshot[1]}})
        if not resized:   # redimensionner la fenêtre déplace les séparateurs : ce n'est pas une édition
            self.layout_edited.emit(previous, snapshot)

    def apply_layout(self, layout):
        """Remet un agencement (annuler / rétablir) et l'enregistre, sans le signaler comme une modification."""
        self._dock_area.apply_layout(layout[0], list(layout[1]))
        self._saved_layout = self._dock_area.layout_snapshot()
        update_settings({"dashboard": {"state": self._saved_layout[0], "hidden": self._saved_layout[1]}})

    def reset_layout(self):
        """Remet l'agencement d'origine (page Réglages). Annulable avec Ctrl+Z sur le Dashboard."""
        before = self._saved_layout
        self.apply_layout(self._default_layout)
        if before != self._saved_layout:
            self.layout_edited.emit(before, self._saved_layout)

    def reload_from_settings(self):
        """Après un import / une réinitialisation complète : relit l'agencement enregistré."""
        cfg = load_settings()["dashboard"]
        if cfg.get("state"):
            self._dock_area.apply_layout(cfg["state"], list(cfg.get("hidden") or []))
        else:
            self._dock_area.apply_layout(*self._default_layout)
        self._saved_layout = self._dock_area.layout_snapshot()
        update_settings({"dashboard": {"state": self._saved_layout[0], "hidden": self._saved_layout[1]}})

    @property
    def preset_panel(self) -> PresetPanel:
        return self._preset_panel

    def _refresh_add_menu(self):
        self._add_menu.clear()
        hidden = self._dock_area.hidden_modules
        self._add_btn.setEnabled(bool(hidden))
        for module_id in hidden:
            action = Action(TITLES.get(module_id, module_id))
            action.triggered.connect(lambda checked=False, mid=module_id: self._dock_area.restore_module(mid))
            self._add_menu.addAction(action)

    # Panneaux pilotés par les raccourcis clavier (cf shortcuts/router.py)

    @property
    def loop_panel(self) -> LoopPanel:
        return self._loop_panel

    @property
    def drum_panel(self) -> DrumPanel:
        return self._drum_panel

    @property
    def setlist_panel(self) -> SetlistPanel:
        return self._setlist_panel

    def stop(self):
        self.save_layout()
        self._loop_panel.stop()