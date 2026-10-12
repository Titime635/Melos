"""
Fine enveloppe autour de la librairie `keyboard` (hook clavier bas niveau).

Elle existe pour deux raisons : isoler les particularités de `keyboard`
(import qui peut échouer, permissions manquantes...) et pouvoir la remplacer
par un faux clavier dans les tests (cf tests/test_shortcuts.py). Toutes les
méthodes d'enregistrement renvoient une fonction sans argument qui annule
l'enregistrement.

Les callbacks sont appelés depuis le thread d'écoute de `keyboard`, jamais
depuis le thread Qt.
"""

from typing import Callable

try:
    import keyboard as _keyboard
except Exception:  # pas installée, ou hook impossible sur ce système
    _keyboard = None


def _base_name(name: str) -> str:
    """Nom canonique d'une touche, gauche/droite confondues ("left ctrl" -> "ctrl")."""
    name = _keyboard.normalize_name(name).lower() if _keyboard is not None else name.lower()
    for prefix in ("left ", "right "):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name


def event_is_key(event_name: str | None, key: str) -> bool:
    """True si l'évènement clavier (son nom) correspond à la touche `key`.

    Pourquoi ne pas laisser `keyboard.add_hotkey` faire ce travail : il identifie
    les touches par code matériel. Or le "4" du pavé numérique et la flèche gauche
    partagent le même code (75) sous Windows : une touche liée à "4" se déclenchait
    aussi sur la flèche gauche (et "6" sur la flèche droite). On compare donc les
    NOMS que Windows donne à l'évènement (la flèche s'appelle "left", jamais "4").
    """
    return bool(event_name) and _base_name(event_name) == _base_name(key)


class KeyboardBackend:
    @property
    def available(self) -> bool:
        return _keyboard is not None

    def add_hotkey(self, spec: str, callback: Callable[[], None]) -> Callable[[], None]:
        """Appelle `callback` à chaque appui sur la combinaison `spec` ("ctrl+f5", "4"...)."""
        parts = [p.strip() for p in spec.split("+") if p.strip()]
        if not parts:
            raise ValueError("combinaison vide")
        key, modifiers = parts[-1], parts[:-1]
        for name in parts:  # refuse tout de suite un nom inconnu (comme add_hotkey le faisait)
            _keyboard.key_to_scan_codes(name)

        def on_event(event):
            if event.event_type != _keyboard.KEY_DOWN or not event_is_key(event.name, key):
                return
            if all(_keyboard.is_pressed(m) for m in modifiers):
                callback()

        handle = _keyboard.hook(on_event)
        return lambda: _keyboard.unhook(handle)

    def on_release(self, key: str, callback: Callable[[], None]) -> Callable[[], None]:
        """Appelle `callback` au relâchement de `key` (une seule touche)."""

        def on_event(event):
            if event.event_type == _keyboard.KEY_UP and event_is_key(event.name, key):
                callback()

        handle = _keyboard.hook(on_event)
        return lambda: _keyboard.unhook(handle)

    def read_hotkey(self) -> str:
        """BLOQUE jusqu'à ce qu'une combinaison soit pressée puis relâchée, et
        renvoie son nom (ex: "ctrl+f5"). À lancer dans un thread."""
        return _keyboard.read_hotkey(suppress=False)