"""
Service Qt de l'éditeur : fait travailler la banque (miroir de l'ampli) et l'établi (édition des presets de la
bibliothèque) dans un thread dédié — les échanges avec l'ampli sont bloquants — et prévient l'UI par signaux. Toutes
les actions passent par UNE file : jamais deux conversations simultanées avec l'ampli, et l'ordre des actions de
l'utilisateur est respecté.

Branchements (cf main.py) :
    state.connection_changed -> service.on_connection_changed
    state.preset_changed     -> service.on_amp_preset_changed   (changement fait par l'ampli, la setlist, un raccourci)
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal

from .amp_io import AmpError
from .bank import EditorBank
from .workbench import Workbench

log = logging.getLogger("melos.editor")


class EditorService(QObject):
    slot_updated = Signal(int)            # le contenu / l'état de cet emplacement a changé
    entry_updated = Signal(str)           # la copie de travail de ce preset de la bibliothèque a changé
    loaded = Signal()                     # les 7 emplacements viennent d'être (re)lus
    busy_changed = Signal(bool)           # une opération est en cours (griser les boutons)
    failed = Signal(str)                  # message d'erreur lisible
    history_applied = Signal(str)         # un annuler/rétablir a modifié ce preset
    audition_changed = Signal(bool)       # l'écoute a démarré / s'est arrêtée
    sent = Signal(int, str)               # (emplacement, preset) : envoyé et enregistré dans l'ampli
    imported = Signal(str)                # preset de la bibliothèque créé depuis un emplacement
    kit_progress = Signal(int, int, int)  # (faits, total, emplacement en cours ; -1 à la fin)

    def __init__(self, bank: EditorBank, workbench: Workbench, parent=None):
        super().__init__(parent)
        self.bank, self.wb = bank, workbench
        self.library, self.links = workbench.library, workbench.links
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="melos-editor")
        self._pending = 0
        bank.on_applied = lambda slot: self.slot_updated.emit(slot)
        workbench.on_entry = lambda eid: self.entry_updated.emit(eid)
        workbench.on_audition = lambda on: self.audition_changed.emit(on)

    # --- File d'actions ---
    def _submit(self, fn, *args, touched=None):
        self._pending += 1
        if self._pending == 1:
            self.busy_changed.emit(True)

        def job():
            try:
                fn(*args)
            except AmpError as exc:
                self.failed.emit(str(exc))
            except Exception as exc:                       # une erreur imprévue ne doit pas tuer le thread
                log.exception("erreur dans l'éditeur")
                self.failed.emit(f"Erreur inattendue : {exc}")
            finally:
                for s in ([touched] if isinstance(touched, int) else touched or []):
                    self.slot_updated.emit(s)
                self._pending -= 1
                if self._pending == 0:
                    self.busy_changed.emit(False)

        self._pool.submit(job)

    @property
    def busy(self) -> bool:
        return self._pending > 0

    @property
    def audition(self) -> bool:
        return self.wb.audition

    # --- Lecture de l'ampli ---
    def refresh(self, backup_reason="connexion"):
        def run():
            self.bank.refresh_from_amp(backup_reason)
            self.loaded.emit()
        self._submit(run)

    # --- Édition des presets de la bibliothèque ---
    def select(self, entry_id):
        self._submit(self.wb.select, entry_id)

    def edit(self, entry_id: str, mutator, label: str = "réglage", key=None):
        self._submit(self.wb.edit, entry_id, mutator, label, key)

    def revert_original(self, entry_id: str):
        self._submit(self.wb.revert_original, entry_id)

    def snapshot(self, entry_id: str, label: str):
        self._submit(self.wb.snapshot, entry_id, label)

    def restore_version(self, entry_id: str, version_id: str):
        def run():
            self.wb.restore_version(entry_id, version_id)
            self.history_applied.emit(entry_id)
        self._submit(run)

    def write_preset(self, slot: int, preset):
        self._submit(self.wb.write_preset, slot, preset, touched=slot)

    def set_audition(self, on: bool):
        self._submit(self.wb.set_audition, on)

    # --- Annuler / rétablir ---
    def can_undo(self) -> str | None:
        """Libellé de ce qu'« annuler » défera (None : rien)."""
        return self.wb.history[-1].label if self.wb.history else None

    def can_redo(self) -> str | None:
        return self.wb.redo_stack[-1].label if self.wb.redo_stack else None

    def undo(self):
        def run():
            h = self.wb.undo()
            if h is not None:
                self.history_applied.emit(h.target)
        self._submit(run)

    def redo(self):
        def run():
            h = self.wb.redo()
            if h is not None:
                self.history_applied.emit(h.target)
        self._submit(run)

    # --- Le Mighty ---
    def play(self, slot: int):
        self._submit(self.wb.play, slot, touched=slot)

    def send(self, entry_id: str, slot: int):
        def run():
            self.wb.send(entry_id, slot)
            self.sent.emit(slot, entry_id)
        self._submit(run, touched=slot)

    def import_slot(self, slot: int, name: str, tags=()):
        def run():
            self.imported.emit(self.wb.import_slot(slot, name, tags))
        self._submit(run, touched=slot)

    def copy_slot(self, src: int, dst: int):
        self._submit(self.wb.copy_slot, src, dst, touched=[src, dst])

    def load_kit(self, kit: dict):
        def run():
            self.bank.load_kit(kit, progress=lambda n, t, s: self.kit_progress.emit(n, t, -1 if s is None else s))
        self._submit(run, touched=sorted(kit))

    # --- Évènements de l'appli ---
    def on_connection_changed(self, connected: bool):
        if connected:
            self.refresh()
        else:
            self.wb.on_disconnected()

    def on_amp_preset_changed(self, slot: int):
        self._submit(self.wb.on_amp_preset_changed, slot, touched=slot)

    def shutdown(self):
        self._pool.shutdown(wait=False, cancel_futures=True)