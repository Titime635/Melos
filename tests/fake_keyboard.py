"""Faux backend clavier pour les tests : même interface que shortcuts/backend.py."""

import queue


class FakeKeyboard:
    available = True

    def __init__(self):
        self.hotkeys: dict[str, list] = {}   # combinaison -> callbacks d'appui
        self.releases: dict[str, list] = {}  # touche -> callbacks de relâchement
        self.reject: set[str] = set()        # combinaisons que le "système" refuse
        self._capture: queue.Queue = queue.Queue()

    # --- interface du backend ---
    def add_hotkey(self, spec, callback):
        if spec in self.reject:
            raise ValueError(f"invalid hotkey {spec}")
        self.hotkeys.setdefault(spec, []).append(callback)
        return lambda: self.hotkeys.get(spec, []).remove(callback) if callback in self.hotkeys.get(spec, []) else None

    def on_release(self, key, callback):
        self.releases.setdefault(key, []).append(callback)
        return lambda: self.releases.get(key, []).remove(callback) if callback in self.releases.get(key, []) else None

    def read_hotkey(self):
        return self._capture.get(timeout=5)

    # --- simulation de l'utilisateur ---
    def registered(self) -> list[str]:
        return sorted(spec for spec, cbs in self.hotkeys.items() if cbs)

    def press(self, spec):
        for cb in list(self.hotkeys.get(spec, [])):
            cb()

    def release(self, spec):
        for part in spec.split("+"):
            for cb in list(self.releases.get(part, [])):
                cb()

    def tap(self, spec):
        self.press(spec)
        self.release(spec)

    def user_presses_in_capture(self, key):
        self._capture.put(key)
