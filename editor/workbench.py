"""
Établi de l'éditeur : on édite les presets de la BIBLIOTHÈQUE (copie de travail enregistrée tout de suite, version
d'origine conservée), puis on décide où et quand les envoyer sur le Mighty. Qt-free, bloquant : destiné au thread de
travail du service.

  - mode « Écouter » : le preset édité est envoyé en direct dans le tampon d'édition de l'ampli (rien n'est écrit en
    flash) ; il s'arrête quand l'ampli change de preset ;
  - « Envoyer » : écriture dans un emplacement (sauvegarde de l'ancien contenu, association mémorisée) ;
  - état de chaque emplacement par rapport à la bibliothèque : à jour / bibliothèque plus récente / modifié hors de
    Melos / hors bibliothèque / non lu.
"""

import time
from dataclasses import dataclass

from .amp_io import AmpError
from .bank import SLOTS, EditorBank
from .library import PresetLibrary
from .links import SlotLinks, fingerprint
from .preset import Preset

HISTORY_MAX = 300
MERGE_WINDOW_S = 1.2                 # un curseur tiré = une seule étape d'annulation

# états d'un emplacement
UNREAD, SYNCED, AHEAD, CHANGED, UNKNOWN = "unread", "synced", "ahead", "changed", "unknown"


@dataclass
class HistoryEntry:
    target: str                      # identifiant du preset de la bibliothèque
    before: Preset
    after: Preset
    label: str
    key: object = None
    t: float = 0.0


class Workbench:
    def __init__(self, bank: EditorBank, library: PresetLibrary, links: SlotLinks):
        self.bank, self.library, self.links = bank, library, links
        self.sel: str | None = None                  # preset de la bibliothèque affiché / écouté
        self.audition = False
        self.history: list[HistoryEntry] = []
        self.redo_stack: list[HistoryEntry] = []
        self.on_entry = None                         # callback(entry_id) : un preset a changé
        self.on_audition = None                      # callback(bool)

    # --- notifications ---
    def _entry_changed(self, entry_id):
        if self.on_entry:
            self.on_entry(entry_id)

    def _set_audition(self, on: bool):
        if self.audition != on:
            self.audition = on
            if self.on_audition:
                self.on_audition(on)

    # --- sélection / écoute ---
    def select(self, entry_id: str | None):
        self.sel = entry_id
        if self.audition:
            self._audition_push()

    def _audition_push(self):
        e = self.library.get(self.sel) if self.sel else None
        if e is None:
            return
        try:
            self.bank.push_buffer(e.preset)
        except AmpError:
            self._set_audition(False)
            raise

    def set_audition(self, on: bool):
        if on:
            if self.bank.current is None:
                raise AmpError("Ampli non connecté : impossible d'écouter")
            if not self.sel or self.library.get(self.sel) is None:
                raise AmpError("Choisis d'abord un preset de la bibliothèque")
            self._set_audition(True)
            self._audition_push()
        else:
            self._set_audition(False)
            self.bank.reload_buffer()

    def play(self, slot: int):
        """Jouer un emplacement : l'écoute s'arrête (le tampon de l'ampli est rechargé)."""
        self._set_audition(False)
        self.bank.activate(slot)

    def on_amp_preset_changed(self, slot: int):
        if self.bank.on_amp_preset_changed(slot):
            self._set_audition(False)               # le tampon d'édition a été rechargé par l'ampli

    def on_disconnected(self):
        self.bank.current = None
        self._set_audition(False)

    # --- édition de la copie de travail (bibliothèque) ---
    def _record(self, target, before: Preset, after: Preset, label, key=None):
        if before.data == after.data:
            return
        now = time.monotonic()
        last = self.history[-1] if self.history else None
        if key is not None and last and last.key == key and last.target == target and now - last.t < MERGE_WINDOW_S:
            last.after, last.t = after.copy(), now
        else:
            self.history.append(HistoryEntry(target, before.copy(), after.copy(), label, key, now))
            del self.history[:-HISTORY_MAX]
        self.redo_stack.clear()

    def _store(self, entry_id: str, preset: Preset):
        self.library.update(entry_id, preset=preset)
        self._entry_changed(entry_id)
        if self.audition and self.sel == entry_id:
            self._audition_push()

    def edit(self, entry_id: str, mutator, label: str = "réglage", key=None):
        """Modifie la copie de travail du preset (enregistrée aussitôt) ; en écoute, le changement part à l'ampli."""
        e = self.library.get(entry_id)
        if e is None:
            raise AmpError("Ce preset n'existe plus dans la bibliothèque")
        before = e.preset.copy()
        new = e.preset.copy()
        mutator(new)
        self._record(entry_id, before, new, label, key)
        self._store(entry_id, new)

    def _keep_before_overwrite(self, e, label: str):
        """Avant de remplacer la copie de travail : on garde un instantané si ce contenu n'existe nulle part ailleurs."""
        if not e.holds(e.preset):
            self.library.add_version(e.id, label, "auto", e.preset)

    def revert_original(self, entry_id: str):
        e = self.library.get(entry_id)
        if e is None or e.original is None or not e.is_modified:
            return
        before = e.preset.copy()
        new = e.original.copy()
        self._keep_before_overwrite(e, "Avant retour à l'original")
        self._record(entry_id, before, new, "retour à l'original")
        self._store(entry_id, new)

    # --- versions ---
    def snapshot(self, entry_id: str, label: str):
        """Crée une version nommée de la copie de travail. Rend None si elle est identique à la dernière."""
        if self.library.get(entry_id) is None:
            raise AmpError("Ce preset n'existe plus dans la bibliothèque")
        return self.library.add_version(entry_id, label, "manual")

    def restore_version(self, entry_id: str, version_id: str):
        """La copie de travail redevient celle de la version choisie (annulable ; l'état actuel est gardé avant)."""
        e = self.library.get(entry_id)
        v = self.library.get_version(entry_id, version_id)
        if e is None or v is None:
            raise AmpError("Cette version n'existe plus")
        self._keep_before_overwrite(e, f"Avant retour à « {v.label} »")
        before, new = e.preset.copy(), v.preset.copy()
        self._record(entry_id, before, new, f"retour à la version « {v.label} »")
        self._store(entry_id, new)

    def undo(self) -> HistoryEntry | None:
        while self.history:
            h = self.history.pop()
            if self.library.get(h.target) is not None:
                self._store(h.target, h.before)
                self.redo_stack.append(h)
                return h
        return None

    def redo(self) -> HistoryEntry | None:
        while self.redo_stack:
            h = self.redo_stack.pop()
            if self.library.get(h.target) is not None:
                self._store(h.target, h.after)
                self.history.append(h)
                h.key = None
                return h
        return None

    # --- état des emplacements par rapport à la bibliothèque ---
    def slot_state(self, slot: int) -> tuple[str, str | None]:
        """(état, identifiant du preset de la bibliothèque concerné)."""
        saved = self.bank.slots[slot].saved
        if saved is None:
            return UNREAD, None
        h = fingerprint(saved)
        link = self.links.get(slot)
        if link and self.library.get(link.entry) is None:
            link = None                                           # preset supprimé de la bibliothèque
        if link and link.hash == h:
            e = self.library.get(link.entry)
            return (SYNCED if e.preset.wire_bytes() == saved.wire_bytes() else AHEAD), e.id
        for e in self.library.entries():                          # contenu identique à un preset connu
            if fingerprint(e.preset) == h:
                return SYNCED, e.id
        if link:
            return CHANGED, link.entry                            # modifié hors de Melos
        return UNKNOWN, None

    def entry_slots(self, entry_id: str) -> list[tuple[int, str]]:
        """Emplacements qui contiennent (ou ont reçu) ce preset : [(emplacement, état)]."""
        out = []
        for i in range(SLOTS):
            st, eid = self.slot_state(i)
            if eid == entry_id and st != UNKNOWN:
                out.append((i, st))
        return out

    # --- envoyer / importer / copier ---
    def send(self, entry_id: str, slot: int, restore: bool = True) -> Preset:
        e = self.library.get(entry_id)
        if e is None:
            raise AmpError("Ce preset n'existe plus dans la bibliothèque")
        saved = self.bank.write_slot(slot, e.preset, restore=restore)
        self.links.set(slot, entry_id, saved)
        self.library.add_version(entry_id, f"Envoyé vers l'emplacement {slot + 1}", "auto", e.preset)
        if self.audition:                                         # le tampon vient d'être rechargé : on reprend l'écoute
            self._audition_push()
        return saved

    def write_preset(self, slot: int, preset: Preset, restore: bool = True) -> Preset:
        """Écrit un preset quelconque (ex. une sauvegarde de l'ampli) dans un emplacement ; l'association de
        l'emplacement est recalculée d'après le contenu."""
        saved = self.bank.write_slot(slot, preset, reason="avant restauration", restore=restore)
        self.links.clear(slot)
        if self.audition:
            self._audition_push()
        return saved

    def import_slot(self, slot: int, name: str, tags=()) -> str:
        """Ajoute à la bibliothèque le contenu d'un emplacement (preset « hors bibliothèque »)."""
        p = self.bank.slots[slot].saved
        if p is None:
            raise AmpError("Emplacement non lu")
        e = self.library.add(p, name, tags)
        self.links.set(slot, e.id, p)
        return e.id

    def copy_slot(self, src: int, dst: int, restore: bool = True):
        p = self.bank.slots[src].saved
        if p is None:
            raise AmpError("L'emplacement source n'a pas été lu")
        st, eid = self.slot_state(src)
        saved = self.bank.write_slot(dst, p, restore=restore)
        if eid and st in (SYNCED, AHEAD):
            self.links.set(dst, eid, saved)
        else:
            self.links.clear(dst)
        if self.audition:
            self._audition_push()