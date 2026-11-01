"""
Sonde Songsterr : télécharge les données d'UN morceau et les range dans un dossier pour qu'on voie leur vraie
structure (à lancer chez toi : l'environnement de Claude n'a pas accès à songsterr.com).

    .venv\\Scripts\\python.exe tools\\songsterr_probe.py "https://www.songsterr.com/a/wsa/muse-plug-in-baby-tab-s1368"

Écrit dans probe_out/<songId>/ : state.json, revision_api.json, track_<n>.json, video_points.json, report.txt
Le rapport (report.txt) est ce qu'il faut me renvoyer. Rien n'est envoyé nulle part, tout reste en local.
Usage personnel : les tabs appartiennent à Songsterr et à leurs auteurs, ne pas les redistribuer.
"""

import gzip
import http.client
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
CDNS = ("https://dqsljvtekg760.cloudfront.net", "https://d3d3l6a6rcgkaf.cloudfront.net")
STATE_RE = re.compile(r'<script[^>]*id="state"[^>]*>(.*?)</script>', re.S)


def _ssl_context():
    """Certificats de `certifi` s'il est installé (le magasin de Windows peut avoir des racines périmées) ;
    la vérification n'est JAMAIS désactivée."""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class _SkipEarlyHints(http.client.HTTPResponse):
    """Le serveur envoie « 103 Early Hints » avant la vraie réponse ; http.client ne sait ignorer que « 100 »
    et prendrait le 103 pour la réponse finale (d'où une fausse erreur HTTP 103)."""

    def _read_status(self):
        while True:
            version, status, reason = super()._read_status()
            if status == 103:
                http.client._read_headers(self.fp)   # saute les en-têtes de l'indication
                continue
            return version, status, reason


class _Connection(http.client.HTTPSConnection):
    response_class = _SkipEarlyHints


class _Handler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_Connection, req, context=self._context)


def fetch(url: str, timeout: float = 20.0) -> bytes:
    opener = urllib.request.build_opener(_Handler(context=_ssl_context()))
    req = urllib.request.Request(url, headers=HEADERS)
    with opener.open(req, timeout=timeout) as resp:
        data = resp.read()
    if data[:2] == b"\x1f\x8b":      # les JSON de pistes du CDN sont servis compressés (gzip)
        data = gzip.decompress(data)
    return data


def parse_state(html: str) -> dict:
    m = STATE_RE.search(html)
    if not m:
        raise ValueError("pas de <script id=\"state\"> dans la page (structure changée ?)")
    return json.loads(m.group(1))


def shape(value, depth: int = 0, max_depth: int = 3):
    """Résumé de structure d'un JSON : types, longueurs, un exemple de chaque clé (sans tout recopier)."""
    if depth >= max_depth:
        return type(value).__name__
    if isinstance(value, dict):
        return {k: shape(v, depth + 1, max_depth) for k, v in list(value.items())[:40]}
    if isinstance(value, list):
        return [f"list[{len(value)}]", shape(value[0], depth + 1, max_depth)] if value else "list[0]"
    if isinstance(value, str):
        return f"str({value[:40]!r})"
    return repr(value)


def main(url: str):
    out_root = Path("probe_out").resolve()
    out_root.mkdir(parents=True, exist_ok=True)      # créé d'emblée : même en cas d'échec on y trouve la trace
    report: list[str] = []
    say = lambda *a: (report.append(" ".join(str(x) for x in a)), print(*a))
    say("Dossier de sortie :", out_root)

    say("URL :", url)
    try:
        raw = fetch(url)
    except urllib.error.HTTPError as exc:
        say(f"ÉCHEC : la page répond HTTP {exc.code} {exc.reason} (blocage anti-robot probable si 403)")
        (out_root / "report.txt").write_text("\n".join(report), encoding="utf-8")
        return
    except Exception as exc:
        say(f"ÉCHEC : impossible de joindre la page : {type(exc).__name__}: {exc}")
        if "CERTIFICATE" in str(exc).upper():
            say("-> Certificat refusé : 1) vérifie la date/heure de Windows ; 2) pip install certifi (puis relance) ;"
                " 3) mets Windows à jour (racines de certificats).")
        (out_root / "report.txt").write_text("\n".join(report), encoding="utf-8")
        return
    html = raw.decode("utf-8", "replace")
    (out_root / "page.html").write_bytes(raw)        # page brute, pour comprendre si la structure a changé
    say(f"page reçue : {len(raw)} octets")
    try:
        state = parse_state(html)
    except Exception as exc:
        say(f"ÉCHEC : {exc}. La page brute est dans {out_root / 'page.html'}")
        (out_root / "report.txt").write_text("\n".join(report), encoding="utf-8")
        return
    cur = (state.get("meta") or {}).get("current") or {}
    song_id, rev_id, image = cur.get("songId"), cur.get("revisionId"), cur.get("image")
    out = out_root / str(song_id or "inconnu")
    out.mkdir(parents=True, exist_ok=True)
    (out / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

    say("clés de state :", list(state.keys()))
    say("clés de meta :", list((state.get("meta") or {}).keys()))
    say("meta.current :", {k: (v if not isinstance(v, (list, dict)) else type(v).__name__) for k, v in cur.items()})
    tracks = cur.get("tracks") or []
    say(f"{len(tracks)} pistes :")
    for i, t in enumerate(tracks):
        say(f"  [{i}]", {k: t.get(k) for k in ("title", "name", "instrument", "instrumentId", "tuning", "partId",
                                               "isEmpty", "isDrums", "views") if k in t})
    say("clés de piste :", sorted({k for t in tracks for k in t}))
    vids = cur.get("videos") or []
    say(f"meta.current.videos : {len(vids)} entrées ; exemple :", json.dumps(vids[:2], ensure_ascii=False)[:500])

    # --- API de révision (source GP éventuelle) ---
    try:
        rev = json.loads(fetch(f"https://www.songsterr.com/api/revision/{rev_id}"))
        (out / "revision_api.json").write_text(json.dumps(rev, ensure_ascii=False, indent=1), encoding="utf-8")
        say("api/revision : clés =", list(rev.keys()), "| source =", rev.get("source"))
    except Exception as exc:
        say("api/revision : échec ->", exc)

    # --- JSON de chaque piste (CDN) ---
    for i, t in enumerate(tracks):
        got = None
        for part in (t.get("partId"), i):
            if part is None:
                continue
            for cdn in CDNS:
                u = f"{cdn}/{song_id}/{rev_id}/{image}/{part}.json"
                try:
                    got = json.loads(fetch(u))
                    say(f"piste {i} : OK via {u}")
                    break
                except urllib.error.HTTPError as exc:
                    say(f"piste {i} : HTTP {exc.code} sur {u}")
                except Exception as exc:
                    say(f"piste {i} : échec {exc} sur {u}")
            if got is not None:
                break
        if got is None:
            continue
        (out / f"track_{i}.json").write_text(json.dumps(got, ensure_ascii=False), encoding="utf-8")
        measures = got.get("measures") or []
        say(f"  mesures : {len(measures)} | clés racine : {list(got.keys())}")
        if measures:
            say("  mesure 0 (structure) :", json.dumps(shape(measures[0]), ensure_ascii=False)[:900])
            first_notes = next((m for m in measures if any(v.get("beats") for v in m.get("voices", []))), None)
            if first_notes:
                say("  1re mesure avec notes :", json.dumps(first_notes, ensure_ascii=False)[:700])
        if "automations" in got:
            say("  automations :", json.dumps(got["automations"], ensure_ascii=False)[:400])

    # --- Points de synchro vidéo (hypothèse : endpoint vu sur le site) ---
    for u in (f"https://www.songsterr.com/api/video-points/{song_id}/{rev_id}/list",
              f"https://www.songsterr.com/api/meta/{song_id}"):
        try:
            data = json.loads(fetch(u))
            name = "video_points.json" if "video-points" in u else "meta_api.json"
            (out / name).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            say(f"{u} : OK", json.dumps(shape(data), ensure_ascii=False)[:600])
            if "video-points" in u and isinstance(data, list):
                say(f"  {len(data)} entrées de synchro vidéo :")
                for v in data[:12]:
                    pts = v.get("points") or []
                    say("   ", {"videoId": v.get("videoId"), "feature": v.get("feature"), "status": v.get("status"),
                                "countries": v.get("countries"), "trackHashes": v.get("trackHashes"),
                                "nb_points": len(pts), "premiers_points": pts[:6], "derniers": pts[-3:]})
        except Exception as exc:
            say(f"{u} : échec -> {exc}")

    (out / "report.txt").write_text("\n".join(report), encoding="utf-8")
    print(f"\nRapport : {out / 'report.txt'}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])