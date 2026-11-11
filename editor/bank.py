"""
Les 7 emplacements du Mighty côté PC : un MIROIR de l'ampli (ce qui est enregistré dans chaque emplacement, quel
emplacement est joué, ce que contient son tampon d'édition). On n'édite plus ici : l'édition se fait sur les presets de
la bibliothèque (editor/workbench.py) ; la banque sait seulement lire, jouer, écouter (envoyer dans le tampon sans
rien écrire) et écrire en flash. Qt-free : tout est bloquant et destiné à un thread de travail (cf editor/service.py).

Règle vérifiée sur l'ampli : changer de preset efface les modifications non enregistrées de son tampon.
"""

import logging
from dataclasses import dataclass

from .amp_io import AmpError, AmpIO
from .library import BackupStore
from .preset import Preset

log = logging.getLogger("melos.editor")
SLOTS = 7


@dataclass
class Slot:
    saved: Preset | None = None        # ce que l'ampli contient (dernière lecture / écriture)


class EditorBank:
    def __init__(self, io: AmpIO, backups: BackupStore):
        self.io = io
        self.backups = backups
        self.slots = [Slot() for _ in range(SLOTS)]
        self.current: int | None = None        # emplacement courant de l'ampli
        self.on_applied = None                 # callback(slot) : appelé après une action (rafraîchit l'UI)
        # Ce que l'ampli a dans son tampon d'édition (preset courant) : sert à n'envoyer que les différences.
        self._amp_buffer: Preset | None = None

    # --- Lecture de l'ampli ---
    def refresh_from_amp(self, backup_reason: str | None = "connexion"):
        """Relit les 7 emplacements (avec sauvegarde de sécurité de ce qui a changé) et le preset courant."""
        for i in range(SLOTS):
            p = self.io.read_slot(i)
            if backup_reason and not self._already_backed_up(i, p):
                self.backups.save(i, p, backup_reason)
            self.slots[i].saved = p
        try:
            self.current, self._amp_buffer = self.io.read_current()
        except AmpError:
            self.current, self._amp_buffer = None, None

    def _already_backed_up(self, slot: int, p: Preset) -> bool:
        last = self.backups.list(slot)
        return bool(last) and last[0][4].wire_bytes() == p.wire_bytes()

    def _applied(self, slot: int):
        if self.on_applied:
            self.on_applied(slot)

    # --- Jouer ---
    def activate(self, slot: int):
        """Bascule l'ampli sur `slot` (son tampon est rechargé depuis la flash)."""
        self.io.select(slot)
        self.current = slot
        self._amp_buffer = self.slots[slot].saved.copy() if self.slots[slot].saved else None
        self._applied(slot)

    def on_amp_preset_changed(self, slot: int) -> bool:
        """Le preset courant a changé sans nous (bouton de l'ampli, setlist, raccourci). On vérifie auprès de l'ampli :
        l'annonce peut être périmée (changement fait par nous entre-temps). Rend True si l'emplacement courant a changé."""
        try:
            cur, buf = self.io.read_current()
        except AmpError:
            cur, buf = slot, None
        if cur == self.current:
            return False
        self.current = cur
        self._amp_buffer = buf if buf is not None else (self.slots[cur].saved.copy() if self.slots[cur].saved else None)
        self._applied(cur)
        return True

    # --- Écouter : envoyer dans le tampon d'édition, sans rien écrire en flash ---
    def push_buffer(self, preset: Preset):
        if self.current is None:
            raise AmpError("Ampli non connecté")
        self.io.push(preset, self._amp_buffer)
        self._amp_buffer = preset.copy()
        self._applied(self.current)

    def reload_buffer(self):
        """Arrête l'écoute : l'ampli rejoue ce qui est enregistré dans l'emplacement courant."""
        if self.current is not None:
            self.activate(self.current)

    # --- Écriture en flash ---
    def write_slot(self, slot: int, preset: Preset, reason: str = "avant écrasement", restore: bool = True) -> Preset:
        """Écrit `preset` dans l'emplacement `slot` de l'ampli : sauvegarde de sécurité de l'ancien contenu, écriture,
        relecture de contrôle. Pour écrire, l'ampli doit passer sur `slot` : avec `restore` il revient ensuite sur
        l'emplacement qu'il jouait. Rend le contenu relu."""
        old = self.io.read_slot(slot)
        if not self._already_backed_up(slot, old):
            self.backups.save(slot, old, reason)
        origin = self.current
        self.slots[slot].saved = old
        self.activate(slot)
        self.io.push(preset, self._amp_buffer)
        self._amp_buffer = preset.copy()
        self.io.save(slot)
        saved = self.io.read_slot(slot)
        self.slots[slot].saved = saved
        self._amp_buffer = saved.copy()
        if saved.wire_bytes() != preset.wire_bytes():
            log.warning("emplacement %d : la relecture diffère de ce qui a été envoyé", slot + 1)
        if restore and origin is not None and origin != slot:
            self.activate(origin)
        self._applied(slot)
        return saved

    def matches(self, slot: int, preset: Preset) -> bool:
        """Cet emplacement de l'ampli contient-il déjà ce preset ?"""
        s = self.slots[slot].saved
        return s is not None and s.wire_bytes() == preset.wire_bytes()

    def load_kit(self, kit: dict, progress=None):
        """Charge un « kit » {emplacement: Preset} : n'écrit que ce qui diffère, puis rend l'ampli sur le preset joué
        au départ. Rend la liste des emplacements écrits."""
        origin = self.current
        todo = [(i, p) for i, p in sorted(kit.items()) if not self.matches(i, p)]
        written = []
        for n, (i, p) in enumerate(todo):
            if progress:
                progress(n, len(todo), i)
            self.write_slot(i, p, reason="avant chargement d'un kit", restore=False)
            written.append(i)
        if progress:
            progress(len(todo), len(todo), None)
        if origin is not None and self.current != origin:
            self.activate(origin)
        return written