"""
Bibliothèque de presets sur le PC : un fichier JSON par preset (dossier choisi par l'appelant, hors dépôt),
étiquettes libres, écriture atomique. Sert aussi de coffre de sauvegardes (copie des 7 emplacements de l'ampli
avant écrasement).
"""

import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .preset import Preset

log = logging.getLogger("melos.editor")
FORMAT = 1


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _atomic_write(path: Path, text: str):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def normalize_tags(tags) -> list[str]:
    seen, out = set(), []
    for t in tags or []:
        t = " ".join(str(t).split())
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


MAX_VERSIONS = 60


@dataclass
class Version:
    """Instantané d'un preset (« manuel » créé par l'utilisateur, « auto » créé à l'envoi ou avant un retour)."""
    id: str
    label: str
    preset: Preset
    date: str = ""
    kind: str = "manual"


@dataclass
class LibraryEntry:
    id: str
    name: str
    preset: Preset
    tags: list = field(default_factory=list)
    notes: str = ""
    created: str = ""
    modified: str = ""
    original: Preset | None = None      # version d'origine (import / première création) : « Revenir à l'original »
    versions: list = field(default_factory=list)      # instantanés successifs (le plus récent en dernier)

    @property
    def is_modified(self) -> bool:
        """La copie de travail diffère-t-elle de la version d'origine ?"""
        return self.original is not None and self.original.wire_bytes() != self.preset.wire_bytes()

    def to_json(self) -> str:
        return json.dumps({"format": FORMAT, "id": self.id, "name": self.name, "tags": self.tags,
                           "notes": self.notes, "created": self.created, "modified": self.modified,
                           "data": self.preset.to_hex(),
                           "original": (self.original or self.preset).to_hex(),
                           "versions": [{"id": v.id, "label": v.label, "date": v.date, "kind": v.kind,
                                         "data": v.preset.to_hex()} for v in self.versions]},
                          indent=1, ensure_ascii=False)

    def holds(self, preset: Preset) -> bool:
        """Ce contenu existe-t-il déjà quelque part (version d'origine, instantané) ? Sert à ne rien perdre en écrasant."""
        w = preset.wire_bytes()
        return (self.original is not None and self.original.wire_bytes() == w) or \
            any(v.preset.wire_bytes() == w for v in self.versions)

    @classmethod
    def from_json(cls, text: str) -> "LibraryEntry":
        d = json.loads(text)
        preset = Preset.from_hex(d["data"])
        original = Preset.from_hex(d["original"]) if d.get("original") else preset.copy()   # anciens fichiers
        versions = []
        for v in d.get("versions", []):
            try:
                versions.append(Version(str(v["id"]), str(v.get("label", "")), Preset.from_hex(v["data"]),
                                        v.get("date", ""), v.get("kind", "manual")))
            except (KeyError, ValueError):
                continue
        return cls(str(d["id"]), str(d.get("name") or "Sans nom"), preset, normalize_tags(d.get("tags")),
                   str(d.get("notes", "")), d.get("created", ""), d.get("modified", ""), original, versions)


class PresetLibrary:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, LibraryEntry] = {}
        self.reload()

    def reload(self):
        self._entries.clear()
        for f in sorted(self.folder.glob("*.json")):
            try:
                e = LibraryEntry.from_json(f.read_text(encoding="utf-8"))
            except (OSError, ValueError, KeyError) as exc:      # fichier abîmé : on le signale mais on ne bloque pas
                log.warning("preset illisible %s : %s", f.name, exc)
                continue
            self._entries[e.id] = e

    def _path(self, entry_id: str) -> Path:
        return self.folder / f"{entry_id}.json"

    def _write(self, e: LibraryEntry):
        _atomic_write(self._path(e.id), e.to_json())

    # --- Lecture ---
    def entries(self) -> list[LibraryEntry]:
        return sorted(self._entries.values(), key=lambda e: (e.name.lower(), e.created))

    def get(self, entry_id: str) -> LibraryEntry | None:
        return self._entries.get(entry_id)

    def all_tags(self) -> list[str]:
        seen = {}
        for e in self._entries.values():
            for t in e.tags:
                seen.setdefault(t.lower(), t)
        return sorted(seen.values(), key=str.lower)

    def search(self, text: str = "", tags=()) -> list[LibraryEntry]:
        """Entrées dont le nom/les notes contiennent `text` et qui portent TOUTES les étiquettes demandées."""
        want = {t.lower() for t in tags}
        q = text.strip().lower()
        out = []
        for e in self.entries():
            have = {t.lower() for t in e.tags}
            if want <= have and (not q or q in e.name.lower() or q in e.notes.lower() or any(q in t for t in have)):
                out.append(e)
        return out

    # --- Écriture ---
    def add(self, preset: Preset, name: str, tags=(), notes: str = "") -> LibraryEntry:
        now = _now()
        e = LibraryEntry(uuid.uuid4().hex[:12], name.strip() or "Sans nom", preset.copy(), normalize_tags(tags),
                         notes, now, now, preset.copy())
        self._entries[e.id] = e
        self._write(e)
        return e

    def update(self, entry_id: str, *, name=None, preset=None, tags=None, notes=None) -> LibraryEntry:
        e = self._entries[entry_id]
        if name is not None:
            e.name = name.strip() or e.name
        if preset is not None:
            e.preset = preset.copy()
        if tags is not None:
            e.tags = normalize_tags(tags)
        if notes is not None:
            e.notes = notes
        e.modified = _now()
        self._write(e)
        return e

    # --- Versions ---
    def add_version(self, entry_id: str, label: str, kind: str = "manual", preset: Preset | None = None):
        """Garde un instantané (de la copie de travail par défaut). Rend None s'il serait identique au dernier."""
        e = self._entries[entry_id]
        p = (preset or e.preset).copy()
        last = e.versions[-1].preset if e.versions else e.original
        if last is not None and last.wire_bytes() == p.wire_bytes():
            return None
        v = Version(uuid.uuid4().hex[:10], label.strip() or "Version", p, _now(), kind)
        e.versions.append(v)
        while len(e.versions) > MAX_VERSIONS:                    # on jette d'abord les instantanés automatiques
            old = next((x for x in e.versions if x.kind == "auto"), e.versions[0])
            e.versions.remove(old)
        self._write(e)
        return v

    def get_version(self, entry_id: str, version_id: str):
        e = self._entries.get(entry_id)
        return next((v for v in e.versions if v.id == version_id), None) if e else None

    def delete_version(self, entry_id: str, version_id: str):
        e = self._entries[entry_id]
        e.versions = [v for v in e.versions if v.id != version_id]
        self._write(e)

    def revert_to_original(self, entry_id: str) -> LibraryEntry:
        e = self._entries[entry_id]
        return self.update(entry_id, preset=e.original or e.preset)

    def set_original(self, entry_id: str, preset=None) -> LibraryEntry:
        """Fait de la copie de travail (ou de `preset`) la nouvelle version d'origine."""
        e = self._entries[entry_id]
        e.original = (preset or e.preset).copy()
        e.modified = _now()
        self._write(e)
        return e

    def duplicate(self, entry_id: str, name: str | None = None) -> LibraryEntry:
        e = self._entries[entry_id]
        return self.add(e.preset, name or f"{e.name} (copie)", e.tags, e.notes)

    def delete(self, entry_id: str):
        self._entries.pop(entry_id, None)
        try:
            self._path(entry_id).unlink()
        except FileNotFoundError:
            pass

    def rename_tag(self, old: str, new: str):
        for e in list(self._entries.values()):
            if any(t.lower() == old.lower() for t in e.tags):
                self.update(e.id, tags=[new if t.lower() == old.lower() else t for t in e.tags])


class BackupStore:
    """Copies des emplacements de l'ampli avant écrasement : un JSON par copie, jamais effacées automatiquement
    au-delà de `keep` par emplacement."""

    def __init__(self, folder, keep: int = 30):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.keep = keep

    def save(self, slot: int, preset: Preset, reason: str) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = self.folder / f"slot{slot + 1}_{stamp}.json"
        _atomic_write(path, json.dumps({"format": FORMAT, "slot": slot + 1, "reason": reason, "date": _now(),
                                        "data": preset.to_hex()}, indent=1))
        old = sorted(self.folder.glob(f"slot{slot + 1}_*.json"))
        for f in old[:-self.keep]:
            f.unlink(missing_ok=True)
        return path

    def list(self, slot: int | None = None):
        pat = f"slot{slot + 1}_*.json" if slot is not None else "slot*_*.json"
        out = []
        for f in sorted(self.folder.glob(pat), reverse=True):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                out.append((f, d["slot"] - 1, d.get("reason", ""), d.get("date", ""), Preset.from_hex(d["data"])))
            except (OSError, ValueError, KeyError):
                continue
        return out