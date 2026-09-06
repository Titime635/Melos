"""
Touches globales pour naviguer dans la setlist — fonctionnent même sans le
focus sur la fenêtre (mains sur la guitare, pas sur le clavier/la souris).

Basé sur la librairie `keyboard` (hook bas niveau). Sur certains systèmes
(Linux sans accès à /dev/uinput, permissions manquantes...), l'enregistrement
d'une touche peut échouer : c'est pour ça que chaque appel est protégé et
remonte l'erreur via `hotkey_error` plutôt que de planter l'appli. Aucune
touche par défaut n'est assignée (cf demande explicite : pas figé sur
"espace") — tant que rien n'est configuré, la navigation ne marche qu'avec
les boutons de l'UI.

La librairie appelle les callbacks depuis son propre thread d'écoute, pas le
thread Qt : les Signal sont donc émis depuis ce thread-là. Toujours
connecter avec Qt.QueuedConnection côté UI (cf ui/setlist_panel.py), même
raison que pour le thread audio de la loop station.
"""

import threading

from PySide6.QtCore import QObject, Signal

try:
    import keyboard
    _KEYBOARD_AVAILABLE = True
except Exception:
    _KEYBOARD_AVAILABLE = False


class GlobalHotkeys(QObject):
    next_triggered = Signal()
    previous_triggered = Signal()
    hotkey_error = Signal(str)
    key_captured = Signal(str, str)  # (rôle "next"/"previous", nom de la touche)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._next_key: str | None = None
        self._previous_key: str | None = None

    @property
    def available(self) -> bool:
        return _KEYBOARD_AVAILABLE

    def set_next_key(self, key: str | None):
        self._next_key = self._register(self._next_key, key, self.next_triggered)

    def set_previous_key(self, key: str | None):
        self._previous_key = self._register(self._previous_key, key, self.previous_triggered)

    def _register(self, old_key, new_key, signal) -> str | None:
        if not _KEYBOARD_AVAILABLE:
            if new_key:
                self.hotkey_error.emit("la librairie 'keyboard' n'est pas disponible sur ce système")
            return None
        try:
            if old_key:
                keyboard.remove_hotkey(old_key)
        except (KeyError, ValueError):
            pass  # déjà retirée ou jamais enregistrée, sans conséquence
        if not new_key:
            return None
        try:
            keyboard.add_hotkey(new_key, lambda: signal.emit())
            return new_key
        except Exception as exc:
            self.hotkey_error.emit(f"impossible d'assigner la touche '{new_key}' : {exc}")
            return None

    def capture_next_keypress(self, role: str):
        """Écoute en tâche de fond la prochaine touche pressée et émet
        key_captured(role, nom_touche) — ne bloque pas l'UI."""
        if not _KEYBOARD_AVAILABLE:
            self.hotkey_error.emit("la librairie 'keyboard' n'est pas disponible sur ce système")
            return

        def _wait():
            try:
                name = keyboard.read_hotkey(suppress=False)
            except Exception as exc:
                self.hotkey_error.emit(f"capture de touche impossible : {exc}")
                return
            self.key_captured.emit(role, name)

        threading.Thread(target=_wait, daemon=True).start()

    def clear(self):
        if _KEYBOARD_AVAILABLE:
            try:
                keyboard.unhook_all_hotkeys()
            except Exception:
                pass
        self._next_key = None
        self._previous_key = None
