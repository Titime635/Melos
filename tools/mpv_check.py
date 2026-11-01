"""
Vérifie la chaîne python-mpv + libmpv + yt-dlp : joue l'AUDIO d'une vidéo YouTube pendant ~15 s.

    .venv\\Scripts\\python.exe tools\\mpv_check.py            (vidéo par défaut : CrsPVNc9h8U)
    .venv\\Scripts\\python.exe tools\\mpv_check.py <idVidéo>

Prérequis : pip install python-mpv yt-dlp, et mpv-2.dll (libmpv) à la racine du projet ou dans le PATH.
"""
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["PATH"] = str(ROOT) + os.pathsep + os.environ.get("PATH", "")   # pour trouver mpv-2.dll
if hasattr(os, "add_dll_directory"):
    os.add_dll_directory(str(ROOT))

video = sys.argv[1] if len(sys.argv) > 1 else "CrsPVNc9h8U"
print("yt-dlp  :", shutil.which("yt-dlp") or "introuvable dans le PATH (le venv doit être actif, ou ajoute Scripts au PATH)")
print("deno    :", shutil.which("deno") or "non")
print("node    :", shutil.which("node") or "non")
try:
    import mpv
except Exception as exc:
    sys.exit(f"python-mpv / libmpv inaccessible : {type(exc).__name__}: {exc}\n"
             "-> pip install python-mpv, et place mpv-2.dll (libmpv) dans le dossier du projet.")

player = mpv.MPV(vid="no", ytdl=True, ytdl_format="bestaudio/best", input_default_bindings=False,
                 input_vo_keyboard=False, log_handler=lambda lvl, comp, msg: print("  mpv:", msg.strip())
                 if lvl in ("error", "fatal", "warn") else None, loglevel="warn")
player.play(f"https://www.youtube.com/watch?v={video}")
t0 = time.time()
while time.time() - t0 < 45:
    pos = player.time_pos
    if pos is not None and pos > 1:
        break
    time.sleep(0.3)
else:
    sys.exit("RATÉ : pas de lecture après 45 s (voir les messages mpv ci-dessus)")
print(f"OK : position {player.time_pos:.1f}s / durée {player.duration}s, codec audio {player.audio_codec_name}")
time.sleep(4)
player.seek(60, reference="absolute")
time.sleep(2)
print(f"saut : position {player.time_pos:.1f}s (attendu ~62)")
player.speed = 0.75
time.sleep(3)
print(f"vitesse 0.75 : position {player.time_pos:.1f}s")
player.terminate()
print("Test terminé")
