"""
Zone de dashboard : un QMainWindow embarqué comme simple widget enfant (pas
une fenêtre séparée) pour profiter de son système de dock natif — tuilage
sans espace mort, splitters natifs, drag natif pour réarranger. Pas
d'onglets : la tabification n'est pas activée, uniquement des divisions
côte à côte / haut-bas (choix explicite, cf discussion).

Les modules supprimés (cf dock_widget.py) ne sont pas détruits : ils sont
détachés du dock (removeDockWidget) et gardés dans `_hidden`, pour pouvoir
être proposés au rajout via modules_hidden_changed (cf le bouton "+" dans
DashboardInterface).
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QMainWindow

from .dock_widget import ModuleDock


class DashboardDockArea(QMainWindow):
    modules_hidden_changed = Signal()  # la liste des modules cachés a changé

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Widget)  # widget enfant normal, pas une fenêtre indépendante
        self.setDockNestingEnabled(True)  # permet les divisions imbriquées (colonnes puis sous-lignes)
        self._docks: dict[str, ModuleDock] = {}
        self._hidden: dict[str, ModuleDock] = {}
        self._edit_mode = False

    def add_module(self, module_id: str, title: str, accent_color: str, content,
                    area=Qt.LeftDockWidgetArea) -> ModuleDock:
        dock = ModuleDock(module_id, title, accent_color, content, parent=self)
        dock.delete_requested.connect(self._on_delete_requested)
        self.addDockWidget(area, dock)
        dock.set_edit_mode(self._edit_mode)
        self._docks[module_id] = dock
        return dock

    def split(self, after_id: str, module_id: str, orientation: Qt.Orientation):
        self.splitDockWidget(self._docks[after_id], self._docks[module_id], orientation)

    def resize_docks(self, module_ids: list[str], sizes: list[int], orientation: Qt.Orientation):
        self.resizeDocks([self._docks[m] for m in module_ids], sizes, orientation)

    def set_edit_mode(self, active: bool):
        self._edit_mode = active
        for dock in self._docks.values():
            dock.set_edit_mode(active)

    def module_geometry(self, module_id: str):
        return self._docks[module_id].geometry()

    # --- Suppression / rajout ---

    def _on_delete_requested(self, dock: ModuleDock):
        self.removeDockWidget(dock)
        del self._docks[dock.module_id]
        self._hidden[dock.module_id] = dock
        self.modules_hidden_changed.emit()

    @property
    def hidden_modules(self) -> dict[str, ModuleDock]:
        return dict(self._hidden)

    def restore_module(self, module_id: str, area=Qt.LeftDockWidgetArea):
        """Rajoute un module précédemment supprimé — atterrit dans `area`
        par défaut, à l'utilisateur de le glisser où il veut ensuite."""
        dock = self._hidden.pop(module_id)
        self.addDockWidget(area, dock)
        dock.set_edit_mode(self._edit_mode)
        dock.show()
        self._docks[module_id] = dock
        self.modules_hidden_changed.emit()