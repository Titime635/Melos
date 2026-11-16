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


@dataclass
class VideoSync:
    video_id: str
    feature: str                     # alternative / solo / backing
    bar_starts_ms: list[float]       # une valeur par mesure de la partition
    countries: list[str] | None = None   # pays où Songsterr propose la vidéo (None / « All » = partout)
    title: str = ""                  # titre YouTube (rempli par la vérification de disponibilité)
    track_hashes: list[str] | None = None   # pistes audio séparées concernées (solo / backing), cf. tabs/mixer.py

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
    if len(points) != measure_count:
        log.info("synchro : %d points pour %d mesures%s", len(points), measure_count, f" -> un point sur {k}" if k > 1 else "")
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


def to_syncs(entries: list[dict], measure_count: int, expected_ms: list[float] | None = None) -> list[VideoSync]:
    return [VideoSync(e["videoId"], e.get("feature") or "", build_bar_starts(e["points"], measure_count, expected_ms),
                      e.get("countries"), "", e.get("trackHashes")) for e in choose_videos(entries)]


def allowed_in(sync: VideoSync, country: str) -> bool:
    return not sync.countries or "All" in sync.countries or country.upper() in sync.countries


def sync_lines(starts_ms: list[float]) -> list[str]:
    """Lignes alphaTex `\\sync (mesure occurrence ms)`, avec un temps jamais négatif."""
    return [f"\\sync ({i} 0 {max(0, round(ms))})" for i, ms in enumerate(starts_ms)]