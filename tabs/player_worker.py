"""
Processus enfant qui héberge libmpv (lancé par tabs/player.py, jamais importé).

Pourquoi un processus à part : libmpv plante parfois (0xC0000005) sur les sauts / changements de flux réseau. Dans le
processus de l'appli, ce plantage la tuait ; ici, seul ce petit processus meurt et l'appli le relance.

Protocole : une ligne JSON par message. stdin (appli -> mpv) : {"c": "load"|"pause"|"toggle"|"seek"|"speed"|"volume"|"stop"|"quit", ...}
stdout (mpv -> appli) : {"t": "st", ...} (état, toutes les 50 ms) ou {"t": "err", "m": "..."}.
"""

import faulthandler
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path


def main():
    app_dir = Path(sys.argv[1])
    out = sys.stdout
    sys.stdout = sys.stderr                              # rien d'autre que nos messages sur stdout
    os.environ["PATH"] = os.pathsep.join([str(app_dir), str(Path(sys.executable).resolve().parent), os.environ.get("PATH", "")])
    if hasattr(os, "add_dll_directory") and (app_dir / "mpv-2.dll").exists():
        os.add_dll_directory(str(app_dir))
    crash = open(app_dir / "melos_mpv_crash.log", "a", buffering=1)
    faulthandler.enable(file=crash)

    def send(obj):
        out.write(json.dumps(obj) + "\n")
        out.flush()

    try:
        import mpv
        player = mpv.MPV(vid="no", ytdl=False, input_default_bindings=False, input_vo_keyboard=False,
                         audio_pitch_correction=True, keep_open=True, loglevel="warn", audio_buffer=0.6,
                         log_file=str(app_dir / "melos_mpv.log"))
        player.pause = True
    except Exception as exc:
        send({"t": "err", "m": f"mpv n'a pas démarré : {exc}", "fatal": True})
        return

    inbox: queue.Queue = queue.Queue()

    def reader():
        for line in sys.stdin:
            try:
                inbox.put(json.loads(line))
            except ValueError:
                pass
        inbox.put({"c": "quit"})                          # l'appli est partie

    threading.Thread(target=reader, daemon=True).start()

    vid = ""
    pending_load = None
    pending_seek = None
    loaded_at = 0.0
    last_seek = 0.0
    checked = True
    last_state = 0.0

    def prop(name):
        try:
            return getattr(player, name)
        except Exception:
            return None

    def busy():
        return time.monotonic() - loaded_at < 8.0 and prop("duration") is None

    while True:
        try:
            msg = inbox.get(timeout=0.02)
        except queue.Empty:
            msg = None
        try:
            if msg:
                c = msg.get("c")
                if c == "quit":
                    break
                elif c == "load":
                    pending_load, pending_seek = msg, None
                    player.pause = True                   # l'ancien son se tait pendant la préparation
                elif c == "pause":
                    player.pause = bool(msg["v"])
                elif c == "toggle":
                    player.pause = not player.pause
                elif c == "seek":
                    pending_seek = float(msg["v"])
                elif c == "speed":
                    player.speed = float(msg["v"])
                elif c == "volume":
                    player.volume = float(msg["v"])
                elif c == "stop":
                    pending_load = pending_seek = None
                    vid = ""
                    player.stop()
            now = time.monotonic()
            if pending_load and not busy():              # jamais de chargement par-dessus un chargement en cours
                m, pending_load = pending_load, None
                opts = {}
                if m.get("ua"):
                    opts["user-agent"] = f"%{len(m['ua'])}%{m['ua']}"
                if m.get("start", 0) > 0.5:
                    opts["start"] = f"{m['start']:.2f}"
                player.pause = bool(m.get("paused", True))
                player.loadfile(m["url"], **opts)
                vid, loaded_at, checked = m.get("vid", ""), time.monotonic(), False
            elif pending_seek is not None and not busy() and prop("duration") is not None and now - last_seek >= 0.4:
                sec, pending_seek, last_seek = pending_seek, None, now
                player.seek(max(0.0, sec), reference="absolute")
            if not checked and time.monotonic() - loaded_at > 20.0:
                checked = True
                if prop("duration") is None:
                    send({"t": "err", "m": "mpv n'a pas réussi à ouvrir ce flux (voir melos_mpv.log)"})
            if now - last_state >= 0.05:
                last_state = now
                send({"t": "st", "vid": vid, "pos": prop("time_pos"), "dur": prop("duration"),
                      "pause": prop("pause"), "idle": prop("core_idle"), "speed": prop("speed"),
                      "busy": busy(), "seeking": pending_seek is not None})
        except Exception as exc:                          # une commande ratée ne doit pas tuer le lecteur
            send({"t": "err", "m": f"mpv : {str(exc)[:150]}"})
    try:
        player.terminate()
    except Exception:
        pass


if __name__ == "__main__":
    main()
