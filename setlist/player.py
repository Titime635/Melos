"""
État de lecture d'une setlist : quelle séquence est active, à quelle étape,
et l'avancée (en boucle une fois la fin atteinte, comme demandé dans le
scope V1). Émet des Signal Qt à chaque changement — c'est ui/setlist_panel.py
qui écoute et envoie effectivement le preset au device : ce module ne
connaît pas le MIDI, même logique de séparation que audio/loop_engine.py.
"""

from PySide6.QtCore import QObject, Signal

from .model import Sequence, Step


class SetlistPlayer(QObject):
    step_changed = Signal(int)       # nouvel index d'étape dans la séquence active
    sequence_changed = Signal()      # la séquence active (ou la liste) a changé

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sequences: list[Sequence] = []
        self._active_index: int | None = None
        self._step_index: int = 0

    def set_sequences(self, sequences: list[Sequence]):
        self._sequences = sequences
        if self._active_index is not None and self._active_index >= len(sequences):
            self._active_index = None
            self._step_index = 0
        self.sequence_changed.emit()

    @property
    def sequences(self) -> list[Sequence]:
        return self._sequences

    @property
    def active_index(self) -> int | None:
        return self._active_index

    @property
    def active_sequence(self) -> Sequence | None:
        if self._active_index is None:
            return None
        return self._sequences[self._active_index]

    @property
    def step_index(self) -> int:
        return self._step_index

    def set_active(self, index: int | None):
        self._active_index = index
        self._step_index = 0
        self.sequence_changed.emit()
        if self.current_step() is not None:
            self.step_changed.emit(self._step_index)

    def current_step(self) -> Step | None:
        seq = self.active_sequence
        if seq is None or not seq.steps:
            return None
        return seq.steps[self._step_index]

    def next_step(self):
        seq = self.active_sequence
        if seq is None or not seq.steps:
            return
        self._step_index = (self._step_index + 1) % len(seq.steps)  # avance en boucle
        self.step_changed.emit(self._step_index)

    def previous_step(self):
        seq = self.active_sequence
        if seq is None or not seq.steps:
            return
        self._step_index = (self._step_index - 1) % len(seq.steps)
        self.step_changed.emit(self._step_index)

    def notify_step_removed(self, deleted_index: int):
        """À appeler après avoir supprimé l'étape `deleted_index` de la
        séquence active : décale l'index courant pour continuer à pointer
        sur la même étape logique (ou la plus proche si c'était celle-ci)."""
        if deleted_index < self._step_index:
            self._step_index -= 1
        seq = self.active_sequence
        if seq and seq.steps:
            self._step_index = max(0, min(self._step_index, len(seq.steps) - 1))
        else:
            self._step_index = 0
        self.step_changed.emit(self._step_index)

    def refresh_current(self):
        """Réémet l'étape courante sans changer l'index — utile après avoir
        ajouté une étape à une séquence qui était vide (rien à naviguer
        avant ça, donc rien n'avait encore activé l'étape 0)."""
        if self.current_step() is not None:
            self.step_changed.emit(self._step_index)
