"""
Télécharge alphaTab (affichage des tablatures) depuis le registre npm dans tabs/vendor/alphatab/.

    .venv\\Scripts\\python.exe tools\\fetch_alphatab.py

Ne garde que le nécessaire : alphaTab.min.js, la police Bravura et la banque de sons General MIDI (sonivox.sf2) du
synthétiseur intégré (mode « Synthèse »).
"""

import io
import json
import sys
import tarfile
import urllib.request
from pathlib import Path

VERSION = "1.8.4"
DEST = Path(__file__).resolve().parent.parent / "tabs" / "vendor" / "alphatab"
KEEP = ("dist/alphaTab.min.js", "dist/alphaTab.min.mjs", "dist/font/", "dist/soundfont/sonivox.sf2", "dist/soundfont/LICENSE")


def main():
    url = f"https://registry.npmjs.org/@coderline/alphatab/-/alphatab-{VERSION}.tgz"
    print("Téléchargement", url)
    try:
        import certifi, ssl
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        import ssl
        ctx = ssl.create_default_context()
    with urllib.request.urlopen(url, timeout=60, context=ctx) as r:
        data = r.read()
    DEST.mkdir(parents=True, exist_ok=True)
    n = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for m in tar.getmembers():
            name = m.name.removeprefix("package/")
            if m.isfile() and any(name.startswith(k) for k in KEEP):
                target = DEST / name.removeprefix("dist/")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(tar.extractfile(m).read())
                n += 1
    (DEST / "VERSION").write_text(VERSION)
    print(f"{n} fichiers écrits dans {DEST}")


if __name__ == "__main__":
    sys.exit(main())