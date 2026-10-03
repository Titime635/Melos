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


class KeyboardBackend:
    @property
    def available(self) -> bool:
        return _keyboard is not None

    def add_hotkey(self, spec: str, callback: Callable[[], None]) -> Callable[[], None]:
        """Appelle `callback` à chaque appui sur la combinaison `spec`."""
        handle = _keyboard.add_hotkey(spec, callback)
        return lambda: _keyboard.remove_hotkey(handle)

    def on_release(self, key: str, callback: Callable[[], None]) -> Callable[[], None]:
        """Appelle `callback` au relâchement de `key` (une seule touche)."""
        handle = _keyboard.on_release_key(key, lambda _event: callback())
        return lambda: _keyboard.unhook(handle)

    def read_hotkey(self) -> str:
        """BLOQUE jusqu'à ce qu'une combinaison soit pressée puis relâchée, et
        renvoie son nom (ex: "ctrl+f5"). À lancer dans un thread."""
        return _keyboard.read_hotkey(suppress=False)
