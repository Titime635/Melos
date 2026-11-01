"""
Points de synchro Songsterr (/api/video-points) -> temps de début de chaque mesure dans la vidéo.

Observé : `points` ≈ une valeur par mesure (début de mesure, en secondes dans la vidéo) ; les dernières mesures
peuvent ne pas être couvertes (on extrapole avec la dernière durée de mesure), et le premier point peut être
négatif (vidéo qui démarre « dans » la première mesure) : on le garde tel quel, c'est à l'affichage de borner.
"""

from dataclasses import dataclass


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


def build_bar_starts(points: list[float], measure_count: int) -> list[float]:
    """Temps de début (ms) de `measure_count` mesures ; extrapole à la fin, tronque si trop de points."""
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


def to_syncs(entries: list[dict], measure_count: int) -> list[VideoSync]:
    return [VideoSync(e["videoId"], e.get("feature") or "", build_bar_starts(e["points"], measure_count),
                      e.get("countries"), "", e.get("trackHashes")) for e in choose_videos(entries)]


def allowed_in(sync: VideoSync, country: str) -> bool:
    return not sync.countries or "All" in sync.countries or country.upper() in sync.countries


def sync_lines(starts_ms: list[float]) -> list[str]:
    """Lignes alphaTex `\\sync (mesure occurrence ms)`, avec un temps jamais négatif."""
    return [f"\\sync ({i} 0 {max(0, round(ms))})" for i, ms in enumerate(starts_ms)]