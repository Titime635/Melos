"""
Association durable emplacement du Mighty ↔ preset de la bibliothèque.

L'ampli ne peut pas mémoriser d'identifiant : Melos note, pour chaque emplacement, quel preset de la bibliothèque y a
été envoyé et l'empreinte de ce qui a été écrit. Au démarrage, on relit l'ampli : si l'empreinte est toujours la
bonne, l'association est valide ; sinon l'emplacement a été modifié en dehors de Melos.
"""

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from .preset import Preset

log = logging.getLogger("melos.editor")


def fingerprint(preset: Preset) -> str:
    """Empreinte de ce que l'ampli sait reproduire (les octets non poussables sont ignorés)."""
    return hashlib.sha1(preset.wire_bytes()).hexdigest()[:16]


@dataclass
class Link:
    entry: str
    hash: str


class SlotLinks:
    def __init__(self, path):
        self.path = Path(path)
        self._links: dict[int, Link] = {}
        self._load()

    def _load(self):
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            self._links = {int(k): Link(str(v["entry"]), str(v["hash"])) for k, v in d.get("slots", {}).items()}
        except (OSError, ValueError, KeyError, TypeError):
            self._links = {}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps({"format": 1, "slots": {str(k): {"entry": v.entry, "hash": v.hash}
                                                          for k, v in sorted(self._links.items())}}, indent=1),
                       encoding="utf-8")
        os.replace(tmp, self.path)

    def get(self, slot: int) -> Link | None:
        return self._links.get(slot)

    def set(self, slot: int, entry_id: str, preset: Preset):
        self._links[slot] = Link(entry_id, fingerprint(preset))
        self._save()

    def clear(self, slot: int):
        if self._links.pop(slot, None) is not None:
            self._save()

    def forget_entry(self, entry_id: str):
        """L'entrée a été supprimée de la bibliothèque."""
        gone = [s for s, l in self._links.items() if l.entry == entry_id]
        for s in gone:
            del self._links[s]
        if gone:
            self._save()
