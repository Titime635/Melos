"""
Télécharge la banque de sons GeneralUser GS (32 Mo, licence libre) dans tabs/vendor/alphatab/soundfont/.

    .venv\\Scripts\\python.exe tools\\fetch_soundfonts.py

Bien meilleure que Sonivox (guitares, piano, batterie) ; la synthèse la choisit automatiquement quand elle est présente.
"""

import sys
import urllib.request
from pathlib import Path

DEST = Path(__file__).resolve().parent.parent / "tabs" / "vendor" / "alphatab" / "soundfont"
BASE = "https://github.com/mrbumpy409/GeneralUser-GS/raw/main/"
FILES = {"GeneralUser-GS.sf2": "GeneralUser-GS.sf2", "LICENSE.txt": "GeneralUser-GS-LICENSE.txt"}


def main():
    try:
        import certifi, ssl
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        import ssl
        ctx = ssl.create_default_context()
    DEST.mkdir(parents=True, exist_ok=True)
    for remote, local in FILES.items():
        print("Téléchargement", BASE + remote)
        try:
            with urllib.request.urlopen(BASE + remote, timeout=120, context=ctx) as r:
                (DEST / local).write_bytes(r.read())
        except OSError as exc:
            print("  échec :", exc)
            if local.endswith(".sf2"):
                return 1
    print("OK ->", DEST)


if __name__ == "__main__":
    sys.exit(main())
