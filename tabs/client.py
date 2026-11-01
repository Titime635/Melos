"""
Récupération d'une tablature Songsterr + cache disque (tabs_cache/<songId>/).

Usage personnel : les tablatures appartiennent à Songsterr et à leurs auteurs ; le cache est local, jamais
redistribué. Les points d'accès ne sont pas documentés : ils peuvent changer (cf. tools/songsterr_probe.py).
"""

import gzip
import http.client
import json
import logging
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from paths import APP_DIR
from .model import Score
from .songsterr_parser import parse_score
from .sync import VideoSync, allowed_in, to_syncs

log = logging.getLogger("melos.tabs")
CACHE_DIR = APP_DIR / "tabs_cache"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
CDNS = ("https://dqsljvtekg760.cloudfront.net", "https://d3d3l6a6rcgkaf.cloudfront.net")
STATE_RE = re.compile(r'<script[^>]*id="state"[^>]*>(.*?)</script>', re.S)
URL_RE = re.compile(r"^https?://(www\.)?songsterr\.com/", re.I)


class TabError(Exception):
    """Erreur lisible par l'utilisateur."""


def _ssl_context():
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class _SkipEarlyHints(http.client.HTTPResponse):
    def _read_status(self):
        while True:
            version, status, reason = super()._read_status()
            if status == 103:                       # « Early Hints » : à ignorer, la vraie réponse suit
                http.client._read_headers(self.fp)
                continue
            return version, status, reason


class _Connection(http.client.HTTPSConnection):
    response_class = _SkipEarlyHints


class _Handler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_Connection, req, context=self._context)


def fetch(url: str, timeout: float = 20.0) -> bytes:
    opener = urllib.request.build_opener(_Handler(context=_ssl_context()))
    with opener.open(urllib.request.Request(url, headers=HEADERS), timeout=timeout) as resp:
        data = resp.read()
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


@dataclass
class SongHit:
    """Un résultat de recherche Songsterr."""
    song_id: int
    title: str
    artist: str
    tracks: list[str]
    url: str


def _slug(text: str) -> str:
    import unicodedata
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")


def song_url(song_id: int, title: str, artist: str) -> str:
    """Adresse de la page d'un morceau (Songsterr la redirige vers l'adresse canonique à partir de l'identifiant)."""
    slug = _slug(f"{artist} {title}") or "song"
    return f"https://www.songsterr.com/a/wsa/{slug}-tab-s{int(song_id)}"


def parse_search(data, limit: int = 30) -> list[SongHit]:
    """Réponse de /api/songs -> résultats. Tolérant : les champs non documentés peuvent changer de forme."""
    items = data if isinstance(data, list) else (data.get("songs") or data.get("results") or []) if isinstance(data, dict) else []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        sid = it.get("id", it.get("songId"))
        title = str(it.get("title") or "").strip()
        artist = it.get("artist")
        artist = str(artist.get("name") if isinstance(artist, dict) else artist or it.get("artistName") or "").strip()
        try:
            sid = int(sid)
        except (TypeError, ValueError):
            continue
        if not title:
            continue
        names = []
        for t in it.get("tracks") or []:
            if isinstance(t, dict):
                name = str(t.get("instrument") or t.get("name") or "").strip()
                if name and name not in names:
                    names.append(name)
        out.append(SongHit(sid, title, artist, names, song_url(sid, title, artist)))
        if len(out) >= limit:
            break
    return out


def search_songs(query: str, limit: int = 30) -> list[SongHit]:
    """Recherche par nom (point d'accès non documenté de Songsterr, celui de leur propre barre de recherche).
    Appel bloquant : à lancer hors thread UI."""
    from urllib.parse import quote
    q = query.strip()
    if len(q) < 2:
        return []
    try:
        raw = fetch(f"https://www.songsterr.com/api/songs?size={int(limit)}&pattern={quote(q)}")
        data = json.loads(raw)
    except Exception as exc:
        raise TabError(f"Recherche impossible : {type(exc).__name__}: {exc}") from exc
    hits = parse_search(data, limit)
    if not hits and data:
        log.warning("recherche : réponse inattendue %r", str(data)[:300])
    return hits


def _cached(path: Path, loader):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    data = loader()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def _track_json(meta: dict, part_id: int) -> dict:
    song, rev, image = meta["songId"], meta["revisionId"], meta["image"]
    last = None
    for cdn in CDNS:
        try:
            return json.loads(fetch(f"{cdn}/{song}/{rev}/{image}/{part_id}.json"))
        except Exception as exc:                    # CDN 2 répond 403 : normal, on essaie le suivant
            last = exc
    raise TabError(f"piste {part_id} introuvable ({last})")


def _oembed(video_id: str) -> dict | None:
    """Infos YouTube (titre) ; None si la vidéo n'existe plus (404). Intégration refusée (401), réseau en panne...
    ne l'écartent pas : la vidéo s'ouvre dans une vraie page youtube.com, pas dans un lecteur intégré."""
    import urllib.error
    try:
        raw = fetch("https://www.youtube.com/oembed?format=json&url="
                    f"https://www.youtube.com/watch?v={video_id}", timeout=8)
        return json.loads(raw)
    except urllib.error.HTTPError as exc:
        return None if exc.code == 404 else {}
    except Exception:
        return {}


def filter_available(syncs: list[VideoSync], key: Path, country: str, refresh: bool, artist: str = "", song: str = "") -> list[VideoSync]:
    """Ne garde que les vidéos proposées dans ton pays et réellement lisibles ; titres récupérés au passage.
    Résultat mis en cache (video_info2.json) : un contrôle réseau par vidéo, une seule fois."""
    from concurrent.futures import ThreadPoolExecutor
    syncs = [s for s in syncs if allowed_in(s, country)]
    path = key / "video_info2.json"
    info = {}
    if path.exists() and not refresh:
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            info = {}
    todo = [s.video_id for s in syncs if s.video_id not in info]
    if todo:
        with ThreadPoolExecutor(8) as pool:
            for vid, res in zip(todo, pool.map(_oembed, todo)):
                info[vid] = None if res is None else {"title": res.get("title", ""), "author": res.get("author_name", "")}
        key.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    out = []
    for s in syncs:
        if s.video_id in info and info[s.video_id] is None:
            continue                                  # supprimée
        data = info.get(s.video_id) or {}
        s.title = f"{data.get('author', '')} — {data.get('title', '')}".strip(" —")
        out.append(s)
    return out              # ordre de Songsterr conservé : la 1re est celle que leur site joue par défaut


def load_song(url: str, refresh: bool = False, country: str = "FR") -> tuple[Score, list[VideoSync]]:
    """Télécharge (ou relit du cache) le morceau de cette URL Songsterr. Appel bloquant : à lancer hors thread UI."""
    if not URL_RE.match(url.strip()):
        raise TabError("Ce n'est pas un lien songsterr.com.")
    m = re.search(r"-s(\d+)(?:[/?#]|$)", url.strip())
    key = CACHE_DIR / (m.group(1) if m else "misc")
    if refresh and key.exists():
        for f in key.glob("*.json"):
            if f.name != "video_info2.json":
                f.unlink()
    try:
        def page_meta():
            html = fetch(url.strip()).decode("utf-8", "replace")
            found = STATE_RE.search(html)
            if not found:
                raise TabError("Page Songsterr illisible (structure changée ?).")
            return json.loads(found.group(1))["meta"]["current"]

        meta = _cached(key / "meta.json", page_meta)
        key = CACHE_DIR / str(meta["songId"])
        tracks = {}
        for tm in meta.get("tracks") or []:
            if tm.get("isEmpty"):
                continue
            pid = tm["partId"]
            try:
                tracks[pid] = _cached(key / f"track_{pid}.json", lambda pid=pid: _track_json(meta, pid))
            except Exception:
                if not tm.get("isDrums"):
                    raise
                log.exception("batterie non téléchargée : piste affichable sans partition (mixage seulement)")
        points = _cached(key / "video_points.json", lambda: json.loads(
            fetch(f"https://www.songsterr.com/api/video-points/{meta['songId']}/{meta['revisionId']}/list")))
    except TabError:
        raise
    except Exception as exc:
        raise TabError(f"Téléchargement impossible : {type(exc).__name__}: {exc}") from exc
    score = parse_score(meta, tracks)
    if not score.tracks:
        raise TabError("Aucune piste exploitable dans ce morceau.")
    syncs = to_syncs(points, score.measure_count)
    try:
        available = filter_available(syncs, key, country, refresh, score.artist, score.title)
    except Exception:
        log.exception("vérification des vidéos")
        available = syncs
    return score, available