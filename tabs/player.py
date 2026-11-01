"""
Lecteur audio d'une vidéo YouTube : mpv (libmpv, via python-mpv) en audio seul, dans un PROCESSUS À PART
(tabs/player_worker.py) : si libmpv plante, l'appli survit et relance le lecteur.

mpv embarque ffmpeg (H.264, AAC, VP9, Opus... tout se lit) et récupère le flux via yt-dlp, sans passer par le
lecteur web de YouTube : pas de pub, pas de page, rien n'est sauvegardé sur le disque.
Prérequis : pip install -r requirements.txt, et mpv-2.dll à la racine du projet (tools/fetch_libmpv.py).
Usage personnel : les conditions d'utilisation de YouTube déconseillent d'extraire les flux hors de leur lecteur.
"""

import json
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

from paths import APP_DIR
from .debug import dbg

log = logging.getLogger("melos.tabs")


class PlayerError(Exception):
    """Erreur lisible par l'utilisateur."""


class AudioPlayer:
    """Proxy du lecteur mpv (processus enfant). Tous les appels rendent la main tout de suite ; `load()` fait trouver
    l'URL directe du flux par yt-dlp en tâche de fond, puis la transmet au processus enfant (dans pump())."""

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._errors: list[str] = []
        self._lock = threading.Lock()
        self._state: dict | None = None
        self._state_at = 0.0
        self.video_id = ""
        self._gen = 0
        self._ready = None                                # (gen, vidéo, url, ua, start, paused) prêt à envoyer
        self._streams: dict[str, tuple[float, str, str]] = {}   # vidéo -> (expiration, url directe, user-agent)
        self._last_load = None                            # dernier chargement envoyé (pour relancer après un plantage)
        self._speed, self._volume = 1.0, 100.0
        self._crashes: list[float] = []
        self._fatal = ''                                  # message : mpv ne démarre pas du tout (DLL absente...)

    # ---------- processus enfant ----------
    def _spawn(self):
        worker = Path(__file__).resolve().parent / "player_worker.py"
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._proc = subprocess.Popen([sys.executable, "-u", str(worker), str(APP_DIR)], cwd=str(APP_DIR),
                                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
                                          encoding="utf-8", creationflags=flags)
        except Exception as exc:
            self._proc = None
            raise PlayerError(f"lecteur audio impossible à lancer : {exc}") from exc
        dbg("lecteur mpv lancé, pid", self._proc.pid)
        threading.Thread(target=self._read, args=(self._proc,), daemon=True, name="mpv-reader").start()

    def _read(self, proc):
        for line in proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if proc is not self._proc:
                return
            if msg.get("t") == "st":
                self._state, self._state_at = msg, time.monotonic()
            elif msg.get("t") == "err":
                dbg("mpv", msg.get("m"))
                with self._lock:
                    self._errors.append(str(msg.get("m")))
                if msg.get("fatal"):
                    self._fatal = str(msg.get("m"))

    def _ensure(self):
        if self._fatal:
            raise PlayerError(self._fatal + " (pip install -r requirements.txt puis python tools/fetch_libmpv.py)")
        if self._proc is None or self._proc.poll() is not None:
            self._spawn()

    def _send(self, **msg):
        try:
            self._ensure()
            self._proc.stdin.write(json.dumps(msg) + "\n")
            self._proc.stdin.flush()
        except PlayerError:
            raise
        except Exception as exc:                          # tube cassé : pump() relancera le lecteur
            dbg("envoi à mpv impossible", repr(exc)[:100])

    def _check_alive(self):
        """Si le processus mpv est mort (plantage de libmpv), on le relance et on reprend où on en était."""
        if self._proc is None or self._proc.poll() is None:
            return
        code = self._proc.poll()
        if self._fatal:                                   # inutile de relancer : il ne démarrera pas
            return
        now = time.monotonic()
        self._crashes = [t for t in self._crashes if now - t < 60] + [now]
        dbg("LE PROCESSUS MPV A PLANTÉ, code", code, "-> relance (voir melos_mpv_crash.log)")
        self._proc, resume = None, self._last_load
        pos = None
        if self._state and self._state.get("pos") is not None and self._state.get("vid") == self.video_id:
            pos = float(self._state["pos"])
        self._state = None
        with self._lock:
            self._errors.append("Le lecteur audio a planté (libmpv) : relancé, appuie sur lecture")
        if len(self._crashes) > 4:
            with self._lock:
                self._errors.append("Le lecteur audio plante en boucle : abandon (voir melos_mpv_crash.log)")
            return
        try:
            self._spawn()
            self._send(c="speed", v=self._speed)
            self._send(c="volume", v=self._volume)
            if resume and self.video_id == resume["vid"]:
                self._send(**{**resume, "start": pos if pos is not None else resume.get("start", 0.0), "paused": True})
        except PlayerError:
            pass

    def take_error(self) -> str | None:
        """Dernier message d'erreur depuis le dernier appel (None s'il n'y en a pas)."""
        with self._lock:
            if not self._errors:
                return None
            msg, self._errors = self._errors[-1], []
            return msg

    # ---------- chargement ----------
    # yt-dlp (en tâche de fond) trouve l'URL directe du flux audio ; le processus mpv ne reçoit qu'une URL ordinaire.
    def load(self, video_id: str, start: float = 0.0, paused: bool = True):
        """Demande le chargement de l'audio de la vidéo ; `start` : position de reprise (s), `paused` : démarrer en pause."""
        self._ensure()
        with self._lock:
            self._gen += 1
            gen = self._gen
            self.video_id = video_id
            self._ready = None
        self._send(c="pause", v=True)                     # l'ancien son se tait pendant qu'on prépare le nouveau
        dbg("player.load demandé", video_id, f"start={start:.2f}", f"paused={paused}", f"gen={gen}")
        threading.Thread(target=self._resolve, args=(gen, video_id, start, paused), daemon=True, name="resolve").start()

    # Façons de demander le flux à YouTube, essayées dans l'ordre : YouTube change souvent ce qu'il accepte (adresses qui
    # répondent 403 selon le « client » choisi par yt-dlp). On ne garde que celle dont l'adresse répond vraiment.
    STRATEGIES = [
        ("défaut", {}),
        ("node", {"js_runtimes": {"node": {}}}),
        ("android_vr", {"extractor_args": {"youtube": {"player_client": ["android_vr"]}}}),
        ("tv", {"extractor_args": {"youtube": {"player_client": ["tv"]}}}),
        ("web_safari", {"extractor_args": {"youtube": {"player_client": ["web_safari"]}}}),
        ("mweb", {"extractor_args": {"youtube": {"player_client": ["mweb"]}}}),
        ("ios", {"extractor_args": {"youtube": {"player_client": ["ios"]}}}),
    ]

    @staticmethod
    def _probe(url: str, ua: str) -> str:
        """\"ok\" si l'adresse sert bien de l'audio avec ce user-agent (lecture de 2 octets), sinon la raison."""
        import urllib.error
        import urllib.request
        from .client import _ssl_context
        req = urllib.request.Request(url, headers={"User-Agent": ua or "Mozilla/5.0", "Range": "bytes=0-1"})
        try:
            with urllib.request.urlopen(req, timeout=10, context=_ssl_context()) as resp:
                return "ok" if resp.status in (200, 206) else f"HTTP {resp.status}"
        except urllib.error.HTTPError as exc:
            return f"HTTP {exc.code}"
        except Exception as exc:
            return type(exc).__name__

    def _resolve(self, gen, video_id, start, paused):
        try:
            cached = self._streams.get(video_id)
            if cached and cached[0] > time.monotonic():
                _, url, ua = cached
            else:
                url, ua = self._extract(video_id)
                self._streams[video_id] = (time.monotonic() + 1800, url, ua)
        except Exception as exc:
            dbg("yt-dlp erreur", video_id, repr(exc)[:200])
            with self._lock:
                self._errors.append(f"yt-dlp : {str(exc)[:200]}")
            return
        with self._lock:
            if gen == self._gen:                          # une demande plus récente a pu passer entre-temps
                self._ready = (gen, video_id, url, ua, start, paused)

    def _extract(self, video_id: str):
        import yt_dlp
        dbg("yt-dlp version", getattr(getattr(yt_dlp, "version", None), "__version__", "?"))
        order = list(self.STRATEGIES)
        good = getattr(self, "_good_strategy", None)
        if good:                                          # celle qui a marché la dernière fois d'abord
            order.sort(key=lambda s: s[0] != good)
        last = "aucune"
        for name, extra in order:
            opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True,
                    "format": "bestaudio[acodec=opus]/bestaudio/best", **extra}      # opus (webm) : le plus sûr pour les sauts
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
                url, ua = info["url"], (info.get("http_headers") or {}).get("User-Agent", "")
            except Exception as exc:
                last = f"{name} : {str(exc)[:100]}"
                dbg("yt-dlp", name, "échec", repr(exc)[:150])
                continue
            verdict = self._probe(url, ua)
            dbg("yt-dlp", name, (info.get("format") or "")[:50], "->", verdict)
            if verdict == "ok":
                self._good_strategy = name
                return url, ua
            last = f"{name} : {verdict}"
        raise PlayerError(f"YouTube refuse le flux audio ({last}). Mets yt-dlp à jour : pip install -U yt-dlp")

    def pump(self):
        """À appeler régulièrement (50 ms) depuis le thread de l'interface : surveille le processus mpv et lui
        transmet le flux qui vient d'être résolu."""
        self._check_alive()
        with self._lock:
            ready, self._ready = self._ready, None
        if ready is None:
            return
        gen, video_id, url, ua, start, paused = ready
        if gen != self._gen:
            return
        msg = {"c": "load", "vid": video_id, "url": url, "ua": ua, "start": start, "paused": paused}
        self._last_load = msg
        dbg("player.loadfile", video_id, f"start={start:.2f}", f"paused={paused}")
        try:
            self._send(**msg)
        except PlayerError as exc:
            with self._lock:
                self._errors.append(str(exc))

    # ---------- état et commandes ----------
    def state(self):
        """(secondes, en lecture, vitesse, durée) ou None tant que le flux n'est pas prêt."""
        st = self._state
        if st is None or not self.video_id or st.get("vid") != self.video_id or time.monotonic() - self._state_at > 1.5:
            return None
        pos, dur = st.get("pos"), st.get("dur")
        if pos is None or not dur:
            return None
        return float(pos), (not st.get("pause")) and not st.get("idle"), float(st.get("speed") or 1.0), float(dur)

    def set_paused(self, paused: bool):
        self._send(c="pause", v=bool(paused))

    def toggle(self):
        if self.video_id:
            self._send(c="toggle")

    def seek(self, sec: float):
        """Saut : le processus mpv les espace d'au moins 0,4 s et ne garde que le dernier."""
        if not self.video_id:
            return
        dbg("player.seek", f"{sec:.2f}")
        self._send(c="seek", v=max(0.0, sec))

    def set_speed(self, speed: float):
        self._speed = max(0.25, min(2.0, speed))
        self._send(c="speed", v=self._speed)

    def set_volume(self, volume_0_1: float):
        self._volume = max(0.0, min(1.0, volume_0_1)) * 100
        self._send(c="volume", v=self._volume)

    def stop(self):
        with self._lock:
            self._gen += 1
            self._ready = None
            self.video_id = ""
        self._last_load = None
        dbg("player.stop")
        self._send(c="stop")

    def shutdown(self):
        dbg("player.shutdown")
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.stdin.write(json.dumps({"c": "quit"}) + "\n")
            proc.stdin.flush()
            proc.wait(timeout=2)
        except Exception:
            proc.kill()