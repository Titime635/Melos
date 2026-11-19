"""
Points de synchro Songsterr (/api/video-points) -> temps de début de chaque mesure dans la vidéo.

Observé : `points` ≈ une valeur par mesure (début de mesure, en secondes dans la vidéo) ; les dernières mesures
peuvent ne pas être couvertes (on extrapole avec la dernière durée de mesure), et le premier point peut être
négatif (vidéo qui démarre « dans » la première mesure) : on le garde tel quel, c'est à l'affichage de borner.
"""

import logging
from dataclasses import dataclass
from statistics import median

log = logging.getLogger(__name__)
_logged: set = set()


@dataclass
class VideoSync:
    video_id: str
    feature: str                     # alternative / solo / backing
    bar_starts_ms: list[float]       # une valeur par mesure de la partition
    countries: list[str] | None = None   # pays où Songsterr propose la vidéo (None / « All » = partout)
    title: str = ""                  # titre YouTube (rempli par la vérification de disponibilité)
    track_hashes: list[str] | None = None   # pistes audio séparées concernées (solo / backing), cf. tabs/mixer.py
    flat_points: list[tuple[int, int, float]] | None = None   # (mesure, passage, ms) quand la partition a des reprises

    @property
    def alpha_sync(self):
        """Ce qu'on donne à alphaTab : tous les passages si la partition a des reprises, sinon une valeur par mesure."""
        return self.flat_points if self.flat_points else self.bar_starts_ms

    @property
    def offset_note(self) -> str:
        return f"{self.feature} · {self.video_id}"


def expected_bar_ms(score) -> list[float]:
    """Durée théorique (ms) de chaque mesure d'après le tempo et la signature de la partition."""
    from .score_edits import tempo_at
    track = next((t for t in score.tracks if t.measures), None)
    if track is None:
        return []
    return [float(m.length) * 4 * 60000.0 / max(1.0, tempo_at(score, m.index)) for m in track.measures]


def played_sequence(measures) -> list[int]:
    """Ordre dans lequel les mesures sont jouées (reprises \\ro / \\rc et fins alternatives dépliées)."""
    n = len(measures)
    seq: list[int] = []
    passes: dict[int, int] = {}      # début de reprise -> passage en cours
    start, i, limit = 0, 0, max(64, n * 24)
    while i < n and len(seq) < limit:
        m = measures[i]
        if m.repeat_start:
            start = i
        cur = passes.get(start, 1)
        if m.alt_ending and cur not in m.alt_ending:
            i += 1                   # cette fin n'est pas jouée à ce passage
            continue
        seq.append(i)
        if m.repeat_end:
            if cur < max(2, m.repeat_end):
                passes[start] = cur + 1
                i = start
                continue
            passes.pop(start, None)
            start = i + 1
        i += 1
    return seq


def align_played(points: list[float], seq: list[int], measure_count: int):
    """(départ de la 1re occurrence de chaque mesure en ms, [(mesure, passage, ms)]) quand un point correspond à chaque
    mesure jouée. None si les nombres ne correspondent pas."""
    if not seq or len(points) != len(seq):
        return None
    seen: dict[int, int] = {}
    flat, first = [], {}
    for bar, t in zip(seq, points):
        occ = seen.get(bar, 0)
        seen[bar] = occ + 1
        ms = float(t) * 1000.0
        flat.append((bar, occ, ms))
        first.setdefault(bar, ms)
    starts = [first.get(b) for b in range(measure_count)]
    last = None
    for b in range(measure_count):          # mesure jamais jouée : on reprend la précédente + une durée moyenne
        if starts[b] is None:
            starts[b] = (last + 2000.0) if last is not None else 0.0
        last = starts[b]
    return starts, flat


def stride_of(points: list[float], measure_count: int, expected_ms: list[float] | None) -> int:
    """Songsterr ne place pas toujours un point par mesure (6/4 : parfois un par demi-mesure) : si les points sont
    nettement plus nombreux que les mesures ET qu'un point sur k donne des mesures de la durée attendue, k est le pas."""
    n = len(points)
    if not expected_ms or measure_count < 2 or n < measure_count * 1.5:
        return 1
    exp = median(expected_ms)
    guess = round(n / measure_count)
    for k in sorted({guess, 2, 3, 4}, key=lambda k: abs(k - guess)):
        if k < 2 or len(points[::k]) < measure_count * 0.8:
            continue
        sub = points[::k]
        gaps = [(b - a) * 1000.0 for a, b in zip(sub, sub[1:]) if b > a]
        if gaps and abs(median(gaps) - exp) <= 0.25 * exp:
            return k
    return 1


def build_bar_starts(points: list[float], measure_count: int, expected_ms: list[float] | None = None) -> list[float]:
    """Temps de début (ms) de `measure_count` mesures ; extrapole à la fin, tronque si trop de points."""
    k = stride_of(points, measure_count, expected_ms)
    key = (len(points), measure_count, k, round(points[0], 3) if points else None)
    if key not in _logged:       # une seule ligne par jeu de points (la fonction est appelée pour chaque vidéo / chaque rendu)
        _logged.add(key)
        if len(points) != measure_count:
            log.info("synchro : %d points pour %d mesures%s", len(points), measure_count, f" -> un point sur {k}" if k > 1 else "")
        sub = points[::k]
        gaps = [(b - a) * 1000.0 for a, b in zip(sub, sub[1:]) if b > a]
        if gaps and expected_ms:
            # durée réelle d'une mesure dans la vidéo / durée théorique d'après le tempo de la partition : un rapport éloigné de 1
            # explique un métronome (calculé sur le tempo) qui dérive par rapport à l'audio d'origine
            real, theo = median(gaps), median(expected_ms)
            log.info("synchro : mesure vidéo %.0f ms (médiane) / théorique %.0f ms (rapport %.3f) ; 1er point %.2f s ; "
                     "4 premières durées vidéo %s ms", real, theo, real / theo, points[0],
                     [round(g) for g in gaps[:4]])
    points = points[::k]
    starts = [float(p) * 1000.0 for p in points[:measure_count]]
    if not starts:
        return []
    step = (starts[-1] - starts[0]) / (len(starts) - 1) if len(starts) > 1 else 2000.0
    if len(starts) > 2:
        step = starts[-1] - starts[-2]
    while len(starts) < measure_count:
        starts.append(starts[-1] + step)
    return starts


def choose_videos(entries: list[dict]) -> list[dict]:
    """Entrées de synchro utilisables, les « alternative » (clips complets) d'abord."""
    # morceau sans aucune vidéo synchronisée : Songsterr renvoie null (ou autre chose qu'une liste) -> pas d'audio
    entries = entries if isinstance(entries, list) else []
    ok = [e for e in entries if isinstance(e, dict) and e.get("status") == "done" and e.get("points") and e.get("videoId")]
    order = {"alternative": 0, "solo": 1, "backing": 2}
    return sorted(ok, key=lambda e: order.get(e.get("feature"), 3))


def to_syncs(entries: list[dict], measure_count: int, expected_ms: list[float] | None = None,
             seq: list[int] | None = None) -> list[VideoSync]:
    """`seq` : ordre de lecture des mesures (cf played_sequence). Songsterr place un point par mesure JOUÉE : avec des
    reprises il y en a plus que de mesures, et il faut les rattacher au bon passage (sinon tout dérive après la 1re reprise)."""
    out = []
    for e in choose_videos(entries):
        pts = e["points"]
        aligned = align_played(pts, seq, measure_count) if seq and len(seq) != measure_count else None
        if aligned is not None:
            key = ("reprises", len(pts), measure_count)
            if key not in _logged:
                _logged.add(key)
                log.info("synchro : %d points = %d mesures jouées (%d mesures, reprises dépliées)", len(pts), len(seq), measure_count)
            out.append(VideoSync(e["videoId"], e.get("feature") or "", aligned[0], e.get("countries"), "",
                                 e.get("trackHashes"), aligned[1]))
        else:
            if seq and len(pts) != measure_count and ("reprises?", len(pts), len(seq)) not in _logged:
                _logged.add(("reprises?", len(pts), len(seq)))
                log.info("synchro : %d points, %d mesures, mais %d mesures jouées d'après les reprises : pas de correspondance", len(pts), measure_count, len(seq))
            out.append(VideoSync(e["videoId"], e.get("feature") or "", build_bar_starts(pts, measure_count, expected_ms),
                                 e.get("countries"), "", e.get("trackHashes")))
    return out


def allowed_in(sync: VideoSync, country: str) -> bool:
    return not sync.countries or "All" in sync.countries or country.upper() in sync.countries


def sync_lines(starts_ms: list) -> list[str]:
    """Lignes alphaTex `\\sync (mesure occurrence ms)`, avec un temps jamais négatif.
    Éléments : un temps par mesure (float), ou (mesure, passage, ms) quand il y a des reprises."""
    lines = []
    for i, item in enumerate(starts_ms):
        bar, occ, ms = item if isinstance(item, (tuple, list)) else (i, 0, item)
        lines.append(f"\\sync ({bar} {occ} {max(0, round(ms))})")
    return lines