"""
Isoler (solo) / couper (mute) des instruments -> choix de la vidéo Songsterr qui sonne comme ça.

Songsterr publie, pour un morceau, plusieurs vidéos synchronisées avec les MÊMES mesures :
  - « alternative » : le morceau complet ;
  - « solo »        : seulement les pistes audio listées dans `trackHashes` ;
  - « backing »     : tout SAUF les pistes listées dans `trackHashes`.
Chaque piste audio séparée (« guitar_92jy2D42 », « drums_xNayAhcQ », « vocals_… », « other_… ») correspond à une piste
de la tablature, par l'identifiant (`hash` de la piste) ou, à défaut, par sa famille d'instrument.

On ne peut donc proposer QUE les mixages pour lesquels une vidéo existe. MixModel les calcule et gère les clics :
  - un bouton n'est cliquable que si au moins une vidéo le permet ;
  - ajouter un instrument à un solo : si aucune vidéo ne les isole ensemble, l'ancien solo est abandonné ;
  - pistes inséparables (même vidéo) : elles se sélectionnent ensemble ;
  - passer de solo à mute (ou l'inverse) abandonne le réglage incompatible.
Logique pure (aucune dépendance Qt) : testée dans tests/test_tabs.py.
"""

from dataclasses import dataclass

from .model import Track
from .sync import VideoSync

# famille d'instrument de la piste -> préfixes de pistes audio séparées qui peuvent la contenir (ordre de préférence)
FAMILY_PREFIXES = {
    "vocals": ("vocals",),
    "drums": ("drums",),
    "guitar": ("guitar",),
    "bass": ("bass", "other"),
    "other": ("other",),
}


def family(track: Track) -> str:
    if track.is_vocal:
        return "vocals"
    if track.is_drums:
        return "drums"
    if track.is_bass:
        return "bass"
    if track.is_guitar:
        return "guitar"
    return "other"


def universe(syncs: list[VideoSync]) -> set[str]:
    return {h for s in syncs for h in (s.track_hashes or [])}


def audible(sync: VideoSync, stems: set[str]) -> set[str]:
    hashes = set(sync.track_hashes or [])
    if sync.feature == "solo":
        return hashes
    if sync.feature == "backing":
        return stems - hashes
    return set(stems)                      # « alternative » (ou inconnue) : morceau complet


@dataclass(frozen=True)
class Mix:
    kind: str | None                       # None (morceau complet), "solo" ou "mute"
    video: VideoSync | None
    tracks: frozenset                      # pistes isolées (solo) ou coupées (mute)


class MixModel:
    def __init__(self, syncs: list[VideoSync], tracks: list[Track], overrides: dict[int, set[str]] | None = None):
        """`overrides` : {indice de piste: pistes audio choisies à la main} (ensemble vide = aucune) ; prioritaire."""
        self.syncs = syncs
        stems = universe(syncs)
        overrides = {i: set(v) & stems for i, v in (overrides or {}).items()}
        claimed = {t.hash for i, t in enumerate(tracks) if i not in overrides and t.hash in stems}   # rattachées par identifiant
        claimed |= {h for v in overrides.values() for h in v}
        self.track_stems: list[set[str]] = []
        for i, t in enumerate(tracks):
            if i in overrides:
                found = overrides[i]
            elif t.hash in stems:
                found = {t.hash}
            else:
                found = set()
                for prefix in FAMILY_PREFIXES[family(t)]:
                    found = {h for h in stems - claimed if h.split("_", 1)[0] == prefix}
                    if found:
                        break
            self.track_stems.append(found)
        self.mixable = frozenset(i for i, s in enumerate(self.track_stems) if s)
        self.default = Mix(None, syncs[0] if syncs else None, frozenset())
        # pour chaque vidéo : pistes audibles et pistes muettes
        self._cands = []
        for order, s in enumerate(syncs):
            a = audible(s, stems)
            heard = frozenset(i for i in self.mixable if self.track_stems[i] <= a)
            silent = frozenset(i for i in self.mixable if not (self.track_stems[i] & a))
            self._cands.append((order, s, heard, silent))

    # ---------- recherche ----------
    def _best(self, wanted: frozenset, index: int, exclude: int | None = None):
        """Vidéo dont l'ensemble (index 2 : audibles, 3 : muets) contient `wanted`, le plus petit possible,
        sans jamais « tout » (ce ne serait plus un solo / un mute)."""
        best = None
        for c in self._cands:
            group = c[index]
            if not group or not wanted <= group or group >= self.mixable or exclude in group:
                continue
            if best is None or len(group) < len(best[index]):
                best = c
        return best

    def _click(self, kind: str, state: Mix, t: int):
        index = 2 if kind == "solo" else 3
        if t not in self.mixable:
            return None
        if state.kind == kind and t in state.tracks:                 # on retire t (et ses pistes inséparables)
            # le nouveau mix doit être INCLUS dans le mix actuel : la plus grande version dont le groupe est contenu dans
            # (mix actuel sans t) ; sinon retour au morceau complet
            allowed = state.tracks - {t}
            best = None
            for c in self._cands:
                group = c[index]
                if group and group <= allowed and group < self.mixable and (best is None or len(group) > len(best[index])):
                    best = c
            return Mix(kind, best[1], best[index]) if best else self.default
        wanted = (state.tracks | {t}) if state.kind == kind else frozenset({t})
        c = self._best(wanted, index) or (self._best(frozenset({t}), index) if wanted != {t} else None)
        return Mix(kind, c[1], c[index]) if c else None

    def state_for(self, video_id: str) -> Mix:
        """Réglage des boutons qui correspond à la vidéo choisie à la main (menu « Vidéo »)."""
        for _, s, heard, silent in self._cands:
            if s.video_id != video_id:
                continue
            if s.feature == "solo" and heard and heard != self.mixable:
                return Mix("solo", s, heard)
            if s.feature == "backing" and silent and silent != self.mixable:
                return Mix("mute", s, silent)
            return Mix(None, s, frozenset())
        return self.default

    def describe(self, tracks: list[Track]) -> list[str]:
        """Table piste -> pistes audio, pour le débogage."""
        lines = [f"piste {i}: {t.name!r} hash={t.hash!r} famille={family(t)} -> {sorted(self.track_stems[i])}"
                 for i, t in enumerate(tracks)]
        for _, s, heard, silent in self._cands:
            lines.append(f"video {s.video_id} {s.feature} hashes={s.track_hashes} entendues={sorted(heard)} "
                         f"muettes={sorted(silent)}")
        return lines

    # ---------- interface ----------
    def solo_click(self, state: Mix, t: int) -> Mix | None:
        return self._click("solo", state, t)

    def mute_click(self, state: Mix, t: int) -> Mix | None:
        return self._click("mute", state, t)

    def clickable(self, kind: str, state: Mix, t: int) -> bool:
        return self._click(kind, state, t) is not None

    def preview(self, kind: str, state: Mix, t: int) -> frozenset:
        """Pistes qui seraient actives pour ce bouton après le clic (vide : le clic ne ferait que retirer / rien)."""
        new = self._click(kind, state, t)
        return new.tracks if new is not None and new.kind == kind else frozenset()