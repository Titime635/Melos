"""
Empêche une touche liée à un raccourci d'agir AUSSI sur l'appli elle-même.

Les raccourcis globaux n'interceptent pas les touches : quand la fenêtre a le
focus, la touche arrive en plus au widget qui l'a (Espace ou Entrée actionnent
le bouton focalisé... y compris le bouton "réduire" de la barre de titre, d'où
une fenêtre qui se minimise "parfois" selon où était le focus). Ce filtre, posé
sur toute l'application, avale les évènements clavier dont la touche (ou la
combinaison) est liée à une action, tant que les raccourcis sont actifs.

La correspondance se fait sur des ensembles de noms ("ctrl", "f5", "space"...)
calqués sur ceux de la librairie `keyboard`, sans tenir compte de l'ordre.
"""

from PySide6.QtCore import QEvent, QObject, Qt

_KEY_NAMES = {
    Qt.Key_Space: "space", Qt.Key_Return: "enter", Qt.Key_Enter: "enter", Qt.Key_Tab: "tab",
    Qt.Key_Backspace: "backspace", Qt.Key_Delete: "delete", Qt.Key_Escape: "esc",
    Qt.Key_Left: "left", Qt.Key_Right: "right", Qt.Key_Up: "up", Qt.Key_Down: "down",
    Qt.Key_PageUp: "page up", Qt.Key_PageDown: "page down", Qt.Key_Home: "home", Qt.Key_End: "end",
    Qt.Key_Insert: "insert",
}
_MODIFIER_KEYS = {Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr}

_ALIASES = {"control": "ctrl", "win": "windows", "cmd": "windows", "super": "windows", "return": "enter",
            "escape": "esc", "del": "delete", "pgup": "page up", "pgdn": "page down", "ins": "insert"}


def canonical_parts(key: str) -> frozenset:
    """"Ctrl+Left Shift+F5" -> {"ctrl", "shift", "f5"} (touches gauche/droite confondues)."""
    parts = set()
    for raw in key.lower().split("+"):
        name = raw.strip()
        for prefix in ("left ", "right "):
            if name.startswith(prefix):
                name = name[len(prefix):]
        name = _ALIASES.get(name, name)
        if name:
            parts.add(name)
    return frozenset(parts)


def qt_event_parts(event) -> frozenset | None:
    """Noms de la combinaison d'un évènement clavier Qt, ou None si on ne sait pas la nommer."""
    key = event.key()
    if key in _MODIFIER_KEYS:
        return None
    if key in _KEY_NAMES:
        name = _KEY_NAMES[key]
    elif Qt.Key_F1 <= key <= Qt.Key_F24:
        name = f"f{key - Qt.Key_F1 + 1}"
    elif Qt.Key_A <= key <= Qt.Key_Z or Qt.Key_0 <= key <= Qt.Key_9:
        name = chr(key).lower()
    else:
        return None
    parts = {name}
    mods = event.modifiers()
    if mods & Qt.ControlModifier:
        parts.add("ctrl")
    if mods & Qt.AltModifier:
        parts.add("alt")
    if mods & Qt.ShiftModifier:
        parts.add("shift")
    if mods & Qt.MetaModifier:
        parts.add("windows")
    return frozenset(parts)


class BoundKeyFilter(QObject):
    """Filtre d'application : `manager.swallows(event)` décide si l'évènement est avalé."""

    def __init__(self, manager):
        super().__init__(manager)
        self._manager = manager

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.KeyPress, QEvent.KeyRelease) and self._manager.swallows(event):
            return True
        return False
