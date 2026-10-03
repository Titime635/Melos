"""
Exécute les actions de actions.py.

Reçoit un identifiant d'action (quelle que soit la source : clavier, plus
tard pédalier Arduino ou Jarvis) et le traduit en appels sur l'appli :

  - presets : envoyés directement via MidiSender + mise à jour optimiste
    d'AmpState (même chose que ui/preset_panel.py : pas d'écho matériel) ;
  - suivant / précédent : "fusionnés" — ils suivent la setlist si elle est
    active (interrupteur sur ON ET une séquence avec des étapes), sinon ils
    font défiler les presets (en boucle, comme la setlist) ;
  - loop station : délégué au LoopPanel de la vue pilotée.

La vue pilotée est fournie par `view_provider` : l'onglet Dashboard et
l'onglet Classique ont chacun leur loop station et leur setlist, donc le
raccourci vise celle de la vue que l'utilisateur regarde (cf
MainWindow.active_view). Doit vivre dans le thread Qt.
"""

from PySide6.QtCore import QObject

from .actions import PRESET_COUNT


class ActionRouter(QObject):
    def __init__(self, state, sender, view_provider, parent=None):
        super().__init__(parent)
        self._state = state
        self._sender = sender
        self._view_provider = view_provider

    def handle(self, action_id: str):
        if action_id.startswith("preset_"):
            self._goto_preset(int(action_id.split("_", 1)[1]) - 1)
        elif action_id == "nav_next":
            self._navigate(+1)
        elif action_id == "nav_previous":
            self._navigate(-1)
        elif action_id.startswith("loop_"):
            loop = getattr(self._view_provider(), "loop_panel", None)
            if loop is not None:
                loop.run_shortcut(action_id)

    def _goto_preset(self, index: int):
        if not 0 <= index < PRESET_COUNT:
            return
        self._sender.set_preset(index)
        self._state.on_preset_changed(index)  # mise à jour optimiste, cf ui/preset_panel.py

    def _navigate(self, direction: int):
        setlist = getattr(self._view_provider(), "setlist_panel", None)
        if setlist is not None and setlist.is_navigation_active():
            setlist.navigate(direction)
        else:
            self._goto_preset((self._state.current_preset + direction) % PRESET_COUNT)
