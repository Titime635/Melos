"""
Télécharge libmpv (la bibliothèque de lecture de mpv, Windows 64 bits) depuis les builds de shinchiro sur GitHub et
dépose mpv-2.dll à la racine du projet.

    .venv\\Scripts\\python.exe tools\\fetch_libmpv.py

Si le script échoue : télécharge à la main « mpv-dev-x86_64-….7z » sur
https://github.com/shinchiro/mpv-winbuild-cmake/releases , extrais libmpv-2.dll et renomme-le mpv-2.dll à la racine.
"""
import json
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEVENZR = "https://www.7-zip.org/a/7zr.exe"   # 7-Zip en ligne de commande, autonome (py7zr ne sait pas lire le filtre BCJ2 de ces archives)
API = "https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest"


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "melos-fetch-libmpv"})
    with urllib.request.urlopen(req, timeout=120, context=_ctx()) as r:
        return r.read()


def main():
    release = json.loads(get(API))
    assets = [a for a in release.get("assets", []) if re.match(r"mpv-dev-.*\.7z$", a["name"])]
    # build standard x86_64 d'abord (pas « v3 », qui exige un processeur récent), sans « i686 » ni « aarch64 »
    assets.sort(key=lambda a: (("v3" in a["name"]) or ("i686" in a["name"]) or ("aarch64" in a["name"]), a["name"]))
    if not assets:
        sys.exit("Aucune archive mpv-dev trouvée dans la dernière version (voir le téléchargement manuel ci-dessus).")
    asset = assets[0]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        print(f"Téléchargement de {asset['name']} ({asset['size'] // 1_000_000} Mo)…")
        (tmp / "mpv.7z").write_bytes(get(asset["browser_download_url"]))
        print("Téléchargement de 7zr.exe (7-Zip, pour décompresser)…")
        (tmp / "7zr.exe").write_bytes(get(SEVENZR))
        out = tmp / "out"
        res = subprocess.run([str(tmp / "7zr.exe"), "e", str(tmp / "mpv.7z"), f"-o{out}", "*mpv-2.dll", "-r", "-y"],
                             capture_output=True, text=True)
        dlls = list(out.glob("*mpv-2.dll")) if out.exists() else []
        if not dlls:
            sys.exit("Extraction impossible :\n" + res.stdout[-600:] + res.stderr[-300:])
        shutil.copy(dlls[0], ROOT / "mpv-2.dll")
    print(f"OK : {ROOT / 'mpv-2.dll'}")


if __name__ == "__main__":
    main()