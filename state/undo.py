"""
Annuler / rétablir (Ctrl+Z, Ctrl+Y, Ctrl+Maj+Z), séparément pour chaque page.

- `UndoStack` : pile générique d'entrées (genre, clé, avant, après). Deux modifications de même clé qui se
  suivent de près (curseur qu'on fait glisser) sont fusionnées en une seule entrée. Appliquer une entrée
  (undo/redo) ne l'enregistre pas.
- `SettingsHistory` : surveille les réglages des modules (tempo, mesure, batterie...) et les enregistre dans
  une pile ; sait les réappliquer (état + ordre MIDI pour la batterie).

L'agencement du Dashboard est enregistré par DashboardInterface (genre "layout") ; les raccourcis par
ShortcutsHistory (genre "bindings"). Cf ui/main_window.py pour le choix de la pile selon la page.
"""

import time
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

from midi import protocol
from state.transport_state import FIELDS as TRANSPORT_FIELDS

COALESCE_S = 0.8
LIMIT = 200


@dataclass
class Entry:
    kind: str
    key: object
    before: object
    after: object
    label: str = ""
    t: float = field(default_factory=time.monotonic)


class UndoStack(QObject):
    changed = Signal()

    def __init__(self, apply, coalesce_s: float = COALESCE_S, parent=None):
        """`apply(kind, values)` remet `values` (le « avant » d'un undo, l'« après » d'un redo)."""
        super().__init__(parent)
        self._apply = apply
        self._coalesce = coalesce_s
        self._undo: list[Entry] = []
        self._redo: list[Entry] = []
        self.applying = False

    def record(self, kind: str, key, before, after, label: str = ""):
        if self.applying or before == after:
            return
        now = time.monotonic()
        top = self._undo[-1] if self._undo else None
        if top and not self._redo and top.kind == kind and top.key == key and now - top.t < self._coalesce:
            top.after, top.t = after, now
            if top.before == top.after:
                self._undo.pop()   # revenu au point de départ : plus rien à annuler
        else:
            self._undo.append(Entry(kind, key, before, after, label, now))
            del self._undo[:-LIMIT]
        self._redo.clear()
        self.changed.emit()

    def can_undo(self, accept=None) -> bool:
        return any(accept is None or accept(e) for e in self._undo)

    def can_redo(self, accept=None) -> bool:
        return any(accept is None or accept(e) for e in self._redo)

    def undo(self, accept=None) -> Entry | None:
        return self._step(self._undo, self._redo, "before", accept)

    def redo(self, accept=None) -> Entry | None:
        return self._step(self._redo, self._undo, "after", accept)

    def _step(self, source: list, target: list, attr: str, accept) -> Entry | None:
        for i in range(len(source) - 1, -1, -1):
            entry = source[i]
            if accept is not None and not accept(entry):
                continue
            self.applying = True
            try:
                ok = self._apply(entry.kind, getattr(entry, attr))
            finally:
                self.applying = False
            if ok is False:
                return None   # refusé (ex. tempo verrouillé) : l'entrée reste en place
            del source[i]
            entry.t = 0.0     # ne se fusionne plus avec une modification ultérieure
            target.append(entry)
            self.changed.emit()
            return entry
        return None

    def clear(self):
        self._undo.clear()
        self._redo.clear()
        self.changed.emit()


# ---------------------------------------------------------------------------------------------------------
# Réglages des modules (tempo + batterie)

TRANSPORT_UNDOABLE = tuple(f for f in TRANSPORT_FIELDS if f != "bars")   # "bars" : réglé tout seul par la boucle
DRUM_FIELDS = ("drum_style", "drum_level", "drum_bass", "drum_middle", "drum_treble")   # pas drum_enabled : départ/arrêt = jeu
GRID_FIELDS = ("bpm", "beats", "unit")   # figés tant qu'une boucle existe
LABELS = {
    "bpm": "tempo", "beats": "mesure", "unit": "mesure", "quantize": "calage sur la mesure",
    "click": "métronome", "sync_drums": "calage de la batterie", "drum_latency_ms": "avance de la batterie",
    "latency_comp_ms": "compensation de latence", "drum_style": "style de batterie", "drum_level": "volume de la batterie",
    "drum_bass": "EQ batterie", "drum_middle": "EQ batterie", "drum_treble": "EQ batterie",
}


class SettingsHistory(QObject):
    """Enregistre les changements de réglages dans `stack` et sait les réappliquer."""

    KIND = "settings"

    def __init__(self, state, sender, stack: UndoStack, engine=None, parent=None):
        super().__init__(parent)
        self._state, self._sender, self._stack, self._engine = state, sender, stack, engine
        self.refused = ""   # raison du dernier refus d'application
        self._last = self._snapshot()
        state.transport.changed.connect(self._on_changed)
        state.drum_updated.connect(self._on_changed)

    def _snapshot(self) -> dict:
        s = self._state
        values = {name: getattr(s.transport, name) for name in TRANSPORT_UNDOABLE}
        values.update({name: getattr(s, name) for name in DRUM_FIELDS})
        return values

    def _on_changed(self, *_):
        now = self._snapshot()
        diff = {k: v for k, v in now.items() if v != self._last[k]}
        if diff:
            before = {k: self._last[k] for k in diff}
            names = sorted(set(LABELS[k] for k in diff))
            self._stack.record(self.KIND, frozenset(diff), before, dict(diff), " / ".join(names))
        self._last = now

    def apply(self, values: dict) -> bool:
        self.refused = ""
        grid = {k: v for k, v in values.items() if k in GRID_FIELDS and getattr(self._state.transport, k) != v}
        if grid and self._engine is not None and self._engine.grid_locked:
            self.refused = "Efface la boucle pour changer le tempo ou la mesure."
            return False
        s = self._state
        transport = {k: v for k, v in values.items() if k in TRANSPORT_UNDOABLE}
        if transport:
            s.transport.set(**transport)
        if "drum_style" in values:
            self._sender.drum_set_style(values["drum_style"])
            s.set_drum_style(values["drum_style"])
        if "drum_level" in values:
            self._sender.drum_set_level(values["drum_level"])
            s.set_drum_level(values["drum_level"])
        if any(k in values for k in ("drum_bass", "drum_middle", "drum_treble")):
            bass = values.get("drum_bass", s.drum_bass)
            middle = values.get("drum_middle", s.drum_middle)
            treble = values.get("drum_treble", s.drum_treble)
            self._sender.drum_set_eq(bass, middle, treble)
            s.set_drum_eq(bass, middle, treble)
        self._last = self._snapshot()
        return True


class ShortcutsHistory(QObject):
    """Enregistre le mode et les touches des raccourcis (page Raccourcis)."""

    KIND = "bindings"

    def __init__(self, manager, stack: UndoStack, parent=None):
        super().__init__(parent)
        self._manager, self._stack = manager, stack
        self._last = self._snapshot()
        manager.bindings_changed.connect(self._on_changed)
        manager.mode_changed.connect(self._on_changed)

    def _snapshot(self) -> dict:
        return {"mode": self._manager.mode, "bindings": {a: list(k) for a, k in self._manager.all_bindings().items()}}

    def _on_changed(self, *_):
        now = self._snapshot()
        if now != self._last:
            label = "mode des raccourcis" if now["bindings"] == self._last["bindings"] else "raccourci"
            self._stack.record(self.KIND, object(), self._last, now, label)   # jamais fusionné
        self._last = now

    def apply(self, values: dict) -> bool:
        self._manager.restore(values["mode"], values["bindings"])
        self._last = self._snapshot()
        return True
