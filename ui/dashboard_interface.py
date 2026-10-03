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

Les panneaux ici sont pour l'instant un mélange : le tuner utilise sa
version compacte dédiée au dashboard (cf ui/dashboard/compact/), les autres
utilisent encore leurs versions complètes en attendant leur tour d'être
retravaillées (cf discussion — un module à la fois). Toutes sont des
instances SÉPARÉES de celles de l'onglet Classique, mais pointent vers les
mêmes AmpState/MidiSender : les deux vues restent synchronisées
automatiquement. LoopPanel et SetlistPanel ont chacun leur propre flux
audio/leurs propres touches globales — d'où stop() à appeler sur CES
instances-ci en plus de celles de l'onglet Classique (cf MainWindow.closeEvent).

Phase 1 : arrangement de départ figé (mesuré sur les tailles réelles des
panneaux), pas encore sauvegardable entre deux lancements (workspaces,
phase 3).
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from qfluentwidgets import SegmentedWidget, TransparentDropDownToolButton, RoundMenu, Action, FluentIcon

from state.amp_state import AmpState
from midi.protocol import PORT_KEYWORD
from midi.sender import MidiSender
from ui.preset_panel import PresetPanel
from ui.dashboard.compact.tuner_compact import CompactTunerPanel
from ui.drum_panel import DrumPanel
from ui.loop_panel import LoopPanel
from ui.setlist_panel import SetlistPanel
from ui.dashboard.dock_area import DashboardDockArea

# Couleur d'identité de chaque module (même palette que les couleurs de
# preset, pour rester cohérent visuellement dans toute l'appli)
ACCENT_COLORS = {
    "presets": "#61D149",
    "tuner": "#46D1E6",
    "drums": "#E98D32",
    "loop": "#DF74D6",
    "setlist": "#2C75EE",
}

TITLES = {
    "presets": "Presets",
    "tuner": "Tuner",
    "drums": "Batterie",
    "loop": "Loop station",
    "setlist": "Setlist",
}


class DashboardInterface(QWidget):
    def __init__(self, state: AmpState, sender: MidiSender, parent=None):
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

        # Instances séparées de celles de l'onglet Classique (cf docstring du module)
        self._loop_panel = LoopPanel()
        self._setlist_panel = SetlistPanel(state, sender)
        panels = {
            "presets": PresetPanel(state, sender),
            "tuner": CompactTunerPanel(state, sender),  # premier module retravaillé pour le dashboard
            "drums": DrumPanel(state, sender),
            "loop": self._loop_panel,
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
        self._refresh_add_menu()

        self._mode_switcher.setCurrentItem("performance")
        self._set_mode(False)

    def _build_default_layout(self):
        """Deux colonnes : presets/tuner/batterie à gauche (empilés),
        loop station/setlist à droite (plus larges, empilés aussi) — mesuré
        sur les tailles réelles des panneaux. Le tuner compact est bien plus
        petit que les autres (113x58 mesuré) : les proportions verticales de
        la colonne de gauche en tiennent compte."""
        d = self._dock_area
        d.split("presets", "loop", Qt.Horizontal)
        d.split("presets", "tuner", Qt.Vertical)
        d.split("tuner", "drums", Qt.Vertical)
        d.split("loop", "setlist", Qt.Vertical)

        d.resize_docks(["presets", "loop"], [404, 682], Qt.Horizontal)
        d.resize_docks(["presets", "tuner", "drums"], [258, 58, 288], Qt.Vertical)
        d.resize_docks(["loop", "setlist"], [387, 378], Qt.Vertical)

    def _set_mode(self, edit: bool):
        self._dock_area.set_edit_mode(edit)
        self._add_btn.setVisible(edit)

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
    def setlist_panel(self) -> SetlistPanel:
        return self._setlist_panel

    def stop(self):
        self._loop_panel.stop()