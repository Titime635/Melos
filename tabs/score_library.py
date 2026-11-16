"""
Historique et favoris des partitions (page Partition).

Une entrée par morceau (clé = identifiant Songsterr). Ouvrir un morceau le remet en tête de l'historique ; l'historique
est borné (les favoris ne sont jamais éliminés). On retient aussi la piste et la vidéo choisies, pour retrouver le
morceau comme on l'avait laissé. Aucune dépendance à Qt : testable seul. Fichier JSON écrit de façon atomique.
"""

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from paths import SCORE_LIBRARY_FILE
from tabs.score_edits import clean_edits

log = logging.getLogger("melos.tabs")

HISTORY_LIMIT = 60          # entrées non favorites conservées
NAME_MAX = 40               # longueur d'un nom de marque-page


@dataclass
class ScoreEntry:
    song_id: int
    url: str
    title: str = ""
    artist: str = ""
    favorite: bool = False
    opened: float = 0.0     # dernier chargement (epoch)
    count: int = 0          # nombre de chargements
    track: int = -1         # dernière piste affichée (-1 = défaut)
    video: str | None = None  # dernière vidéo (None = défaut, "" = sans audio)
    bookmarks: list = field(default_factory=list)   # marque-pages : [{"bar": index de mesure (0 = première), "name": str}], triés par mesure

    presets: list = field(default_factory=list)     # changements de preset : [{"bar": mesure, "beat": temps (absent = 0), "slot" ou "entry"}], triés par (mesure, temps)
    edits: list = field(default_factory=list)       # modifications de la partition (« Ma version ») : cf tabs/score_edits.py
    seeded: bool = False                            # marque-pages par défaut (sections de Songsterr) déjà posés : on ne les repose plus
    version: str = "original"                       # version affichée : "original" (Songsterr) ou "modified" (Ma version)

    @property
    def keep(self) -> bool:
        """Jamais éliminé de l'historique : favori, marque-pages, changements de preset ou modifications de la partition
        (du travail de l'utilisateur ; les marque-pages posés d'office ne comptent pas)."""
        return self.favorite or any(not b.get("auto") for b in self.bookmarks) or bool(self.presets) or bool(self.edits)

    @property
    def label(self) -> str:
        return self.title or self.url


def _clean_bookmarks(raw) -> list[dict]:
    """Ne garde que les marque-pages valides (un seul abîmé ne doit pas faire perdre l'entrée entière)."""
    out: dict[int, dict] = {}
    for b in raw if isinstance(raw, list) else []:
        try:
            bar = int(b["bar"])
            if bar >= 0:
                out[bar] = {"bar": bar, "name": str(b.get("name") or f"Mesure {bar + 1}")[:NAME_MAX], **({"auto": True} if b.get("auto") else {})}
        except (TypeError, ValueError, KeyError, AttributeError):
            continue
    return [out[k] for k in sorted(out)]


SLOTS = 7                   # emplacements de preset du Mighty (0-6)


BEATS_MAX = 32              # temps maximum dans une mesure (12/8, 15/16...)


def _pos(p: dict) -> tuple[int, int]:
    return p["bar"], p.get("beat", 0)


def _clean_presets(raw) -> list[dict]:
    """Ne garde que les changements de preset valides (un par mesure et par temps ; « beat » absent = début de mesure).
    Cible : un preset de la bibliothèque ({"entry": id, "name": nom au moment de la pose}) ou, sans bibliothèque,
    un emplacement brut ({"slot": 0-6})."""
    out: dict[tuple[int, int], dict] = {}
    for p in raw if isinstance(raw, list) else []:
        try:
            bar, beat = int(p["bar"]), int(p.get("beat") or 0)
            if bar < 0 or not 0 <= beat < BEATS_MAX:
                continue
            at = {"bar": bar, **({"beat": beat} if beat else {})}
            if p.get("entry"):
                out[(bar, beat)] = {**at, "entry": str(p["entry"]), "name": str(p.get("name") or "")[:80]}
            elif 0 <= int(p["slot"]) < SLOTS:
                out[(bar, beat)] = {**at, "slot": int(p["slot"])}
        except (TypeError, ValueError, KeyError, AttributeError):
            continue
    return [out[k] for k in sorted(out)]


class ScoreLibrary:
    def __init__(self, path: Path | str | None = None, limit: int = HISTORY_LIMIT, clock=time.time):
        self.path = Path(path) if path else SCORE_LIBRARY_FILE
        self.limit = limit
        self._clock = clock
        self.listeners: list = []                    # appelés après chaque changement
        self._entries: dict[int, ScoreEntry] = {}
        self._load()

    # ---------- lecture ----------
    def get(self, song_id: int) -> ScoreEntry | None:
        return self._entries.get(int(song_id))

    def is_favorite(self, song_id: int) -> bool:
        e = self.get(song_id)
        return bool(e and e.favorite)

    def recent(self) -> list[ScoreEntry]:
        return sorted(self._entries.values(), key=lambda e: e.opened, reverse=True)

    def favorites(self) -> list[ScoreEntry]:
        return sorted((e for e in self._entries.values() if e.favorite), key=lambda e: (e.title.lower(), e.artist.lower()))

    def last(self) -> ScoreEntry | None:
        r = self.recent()
        return r[0] if r else None

    def search(self, text: str, entries: list[ScoreEntry]) -> list[ScoreEntry]:
        words = text.lower().split()
        return [e for e in entries if all(w in f"{e.title} {e.artist}".lower() for w in words)]

    # ---------- écriture ----------
    def touch(self, song_id: int, url: str, title: str, artist: str):
        """Le morceau vient d'être chargé : en tête de l'historique (titre / lien rafraîchis, favori conservé)."""
        sid = int(song_id)
        e = self._entries.get(sid)
        if e is None:
            e = self._entries[sid] = ScoreEntry(sid, url)
        e.url, e.title, e.artist = url or e.url, title or e.title, artist or e.artist
        e.opened, e.count = self._clock(), e.count + 1
        self._prune()
        self._save()

    def remember(self, song_id: int, track: int | None = None, video: str | None = None):
        e = self.get(song_id)
        if e is None:
            return
        changed = False
        if track is not None and e.track != track:
            e.track, changed = track, True
        if video is not None and e.video != video:
            e.video, changed = video, True
        if changed:
            self._save()

    def set_favorite(self, song_id: int, on: bool) -> bool:
        e = self.get(song_id)
        if e is None or e.favorite == bool(on):
            return False
        e.favorite = bool(on)
        self._prune()
        self._save()
        return True

    def toggle_favorite(self, song_id: int) -> bool:
        e = self.get(song_id)
        return self.set_favorite(song_id, not (e and e.favorite)) if e else False

    def remove(self, song_id: int):
        if self._entries.pop(int(song_id), None) is not None:
            self._save()

    def clear_history(self):
        """Vide l'historique ; les favoris et les morceaux qui ont des marque-pages restent."""
        self._entries = {k: e for k, e in self._entries.items() if e.keep}
        self._save()

    # ---------- marque-pages ----------
    def bookmarks(self, song_id: int) -> list[dict]:
        e = self.get(song_id)
        return [dict(b) for b in e.bookmarks] if e else []

    def bookmark_at(self, song_id: int, bar: int) -> dict | None:
        return next((b for b in self.bookmarks(song_id) if b["bar"] == bar), None)

    def add_bookmark(self, song_id: int, bar: int, name: str = "") -> dict | None:
        """Pose un marque-page sur la mesure `bar` (un seul par mesure : s'il existe déjà, on le renomme si un nom est donné)."""
        e = self.get(song_id)
        if e is None or bar < 0:
            return None
        name = " ".join(str(name).split())[:NAME_MAX] or f"Mesure {bar + 1}"
        b = next((b for b in e.bookmarks if b["bar"] == bar), None)
        if b is None:
            b = {"bar": int(bar), "name": name}
            e.bookmarks.append(b)
            e.bookmarks.sort(key=lambda x: x["bar"])
        elif name != f"Mesure {bar + 1}":
            b["name"] = name
            b.pop("auto", None)
        self._save()
        return dict(b)

    def rename_bookmark(self, song_id: int, bar: int, name: str):
        e = self.get(song_id)
        b = next((b for b in e.bookmarks if b["bar"] == bar), None) if e else None
        name = " ".join(str(name).split())[:NAME_MAX]
        if b is not None and name and b["name"] != name:
            b["name"] = name
            b.pop("auto", None)                      # retouché par l'utilisateur : il est à lui
            self._save()

    def seed_bookmarks(self, song_id: int, sections: list[tuple[int, str]]) -> int:
        """Pose un marque-page sur chaque section du morceau (Intro, Couplet, Refrain...) la première fois seulement :
        ceux que l'utilisateur supprime ensuite ne reviennent pas. Renvoie le nombre posé."""
        e = self.get(song_id)
        if e is None or e.seeded:
            return 0
        e.seeded = True
        n = 0
        for bar, name in sections:
            name = " ".join(str(name).split())[:NAME_MAX]
            if bar >= 0 and name and not any(b["bar"] == bar for b in e.bookmarks):
                e.bookmarks.append({"bar": int(bar), "name": name, "auto": True})
                n += 1
        e.bookmarks.sort(key=lambda x: x["bar"])
        self._save(notify=False)          # silencieux : fait partie du chargement, pas une action à annuler
        return n

    def move_bookmark(self, song_id: int, bar: int, to_bar: int) -> bool:
        """Déplace le marque-page de la mesure `bar` vers `to_bar` (remplace celui qui y serait déjà)."""
        e = self.get(song_id)
        b = next((b for b in e.bookmarks if b["bar"] == bar), None) if e else None
        if b is None or to_bar < 0 or to_bar == bar:
            return False
        name = f"Mesure {to_bar + 1}" if b["name"] == f"Mesure {bar + 1}" else b["name"]       # nom par défaut : suit la mesure
        e.bookmarks = [x for x in e.bookmarks if x["bar"] not in (bar, to_bar)] + [{"bar": int(to_bar), "name": name}]
        e.bookmarks.sort(key=lambda x: x["bar"])
        self._save()
        return True

    def remove_bookmark(self, song_id: int, bar: int):
        e = self.get(song_id)
        if e is not None and any(b["bar"] == bar for b in e.bookmarks):
            e.bookmarks = [b for b in e.bookmarks if b["bar"] != bar]
            self._save()

    def neighbour_bookmark(self, song_id: int, bar: int, direction: int) -> dict | None:
        """Marque-page juste après (direction > 0) ou juste avant (< 0) la mesure `bar` ; None s'il n'y en a plus."""
        bs = self.bookmarks(song_id)
        cands = [b for b in bs if (b["bar"] > bar if direction > 0 else b["bar"] < bar)]
        return (cands[0] if direction > 0 else cands[-1]) if cands else None

    # ---------- changements de preset ----------
    def preset_marks(self, song_id: int) -> list[dict]:
        e = self.get(song_id)
        return [dict(p) for p in e.presets] if e else []

    def preset_at(self, song_id: int, bar: int, beat: int = 0) -> dict | None:
        return next((p for p in self.preset_marks(song_id) if _pos(p) == (bar, beat)), None)

    def presets_in_bar(self, song_id: int, bar: int) -> list[dict]:
        return [p for p in self.preset_marks(song_id) if p["bar"] == bar]

    def active_preset(self, song_id: int, bar: int, beat: int = 0) -> dict | None:
        """Le changement en vigueur à la mesure `bar`, au temps `beat` : le dernier posé à cette position ou avant ;
        None avant le premier."""
        cands = [p for p in self.preset_marks(song_id) if _pos(p) <= (bar, beat)]
        return cands[-1] if cands else None

    def _put_preset(self, song_id: int, bar: int, target: dict, beat: int = 0) -> bool:
        e = self.get(song_id)
        if e is None or bar < 0 or not 0 <= beat < BEATS_MAX:
            return False
        new = {"bar": int(bar), **({"beat": int(beat)} if beat else {}), **target}
        old = next((p for p in e.presets if _pos(p) == (bar, beat)), None)
        if old == new:
            return True
        e.presets = [p for p in e.presets if _pos(p) != (bar, beat)] + [new]
        e.presets.sort(key=_pos)
        self._save()
        return True

    def set_preset_mark(self, song_id: int, bar: int, slot: int, beat: int = 0) -> bool:
        """Pose (ou remplace) un changement vers l'emplacement brut `slot` (0-6) à la mesure `bar`, au temps `beat` (0 = début)."""
        return 0 <= slot < SLOTS and self._put_preset(song_id, bar, {"slot": int(slot)}, beat)

    def set_preset_entry(self, song_id: int, bar: int, entry_id: str, name: str = "", beat: int = 0) -> bool:
        """Pose (ou remplace) un changement vers un preset de la bibliothèque de presets (nom conservé pour l'affichage
        si le preset disparaît de la bibliothèque)."""
        return bool(entry_id) and self._put_preset(song_id, bar, {"entry": str(entry_id), "name": str(name)[:80]}, beat)

    def move_preset_mark(self, song_id: int, bar: int, to_bar: int, beat: int = 0, to_beat: int = 0) -> bool:
        """Déplace le changement de (`bar`, `beat`) vers (`to_bar`, `to_beat`) (remplace celui qui y serait déjà)."""
        e = self.get(song_id)
        p = next((p for p in e.presets if _pos(p) == (bar, beat)), None) if e else None
        if p is None or to_bar < 0 or not 0 <= to_beat < BEATS_MAX or (to_bar, to_beat) == (bar, beat):
            return False
        target = {k: v for k, v in p.items() if k not in ("bar", "beat")}
        moved = {"bar": int(to_bar), **({"beat": int(to_beat)} if to_beat else {}), **target}
        e.presets = [q for q in e.presets if _pos(q) not in ((bar, beat), (to_bar, to_beat))] + [moved]
        e.presets.sort(key=_pos)
        self._save()
        return True

    def restore_marks(self, song_id: int, bookmarks: list, presets: list, edits: list | None = None,
                      version: str | None = None) -> bool:
        """Remet les marque-pages, changements de preset (et, si fournis, modifications de la partition et version affichée)
        d'un morceau tels qu'ils étaient (annuler / rétablir)."""
        e = self.get(song_id)
        if e is None:
            return False
        e.bookmarks, e.presets = _clean_bookmarks(bookmarks), _clean_presets(presets)
        if edits is not None:
            e.edits = clean_edits(edits)
        if version in ("original", "modified"):
            e.version = version
        self._save()
        return True

    # ---------- « Ma version » de la partition ----------
    def edits(self, song_id: int) -> list[dict]:
        e = self.get(song_id)
        return [dict(x) for x in e.edits] if e else []

    def version(self, song_id: int) -> str:
        e = self.get(song_id)
        return e.version if e else "original"

    def set_edits(self, song_id: int, edits: list) -> bool:
        """Remplace la liste des modifications (une liste vide = retour à l'original, qui reste affiché)."""
        e = self.get(song_id)
        if e is None:
            return False
        new = clean_edits(edits)
        if new == e.edits:
            return True
        e.edits = new
        self._prune()
        self._save()
        return True

    def set_version(self, song_id: int, version: str) -> bool:
        e = self.get(song_id)
        if e is None or version not in ("original", "modified"):
            return False
        if e.version != version:
            e.version = version
            self._save()
        return True

    def remove_preset_mark(self, song_id: int, bar: int, beat: int = 0):
        e = self.get(song_id)
        if e is not None and any(_pos(p) == (bar, beat) for p in e.presets):
            e.presets = [p for p in e.presets if _pos(p) != (bar, beat)]
            self._save()

    def _prune(self):
        extra = [e for e in self.recent() if not e.keep][self.limit:]
        for e in extra:
            self._entries.pop(e.song_id, None)

    # ---------- fichier / export ----------
    def to_data(self) -> dict:
        return {"version": 1, "entries": [asdict(e) for e in self.recent()]}

    def load_data(self, data) -> bool:
        """Remplace le contenu (import / lecture du fichier). Les entrées invalides sont ignorées."""
        entries: dict[int, ScoreEntry] = {}
        names = {f.name for f in fields(ScoreEntry)}
        raw = data.get("entries") if isinstance(data, dict) else None
        for item in raw if isinstance(raw, list) else []:
            try:
                e = ScoreEntry(**{k: v for k, v in item.items() if k in names})
                e.song_id, e.favorite = int(e.song_id), bool(e.favorite)
                e.opened, e.count, e.track = float(e.opened), int(e.count), int(e.track)
                e.bookmarks = _clean_bookmarks(e.bookmarks)
                e.presets = _clean_presets(e.presets)
                e.edits = clean_edits(e.edits)
                if e.version not in ("original", "modified"):
                    e.version = "original"
                if e.url:
                    entries[e.song_id] = e
            except (TypeError, ValueError, AttributeError, KeyError):
                continue
        self._entries = entries
        return bool(entries) or raw == []

    def _load(self):
        try:
            self.load_data(json.loads(self.path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            log.warning("bibliothèque de partitions illisible (%s) : repart vide", exc)

    def _save(self, notify: bool = True):
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.to_data(), ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as exc:
            log.warning("bibliothèque de partitions non enregistrée : %s", exc)
        for fn in ([] if not notify else list(self.listeners)):
            fn()

    def reload(self):
        """Relit le fichier (après un import ou une réinitialisation)."""
        self._entries = {}
        self._load()
        for fn in list(self.listeners):
            fn()