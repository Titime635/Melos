"""
Petit serveur HTTP local (127.0.0.1, port libre) qui sert la page de partition et alphaTab.

Pourquoi pas file:// : l'intégration YouTube refuse les pages sans origine http(s) (erreurs 150/153).
"""

import functools
import http.server
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"
ALPHATAB = HERE / "vendor" / "alphatab"


def alphatab_installed() -> bool:
    return (ALPHATAB / "alphaTab.min.js").exists() and (ALPHATAB / "font").exists()


SOUNDFONT_LABELS = {"GeneralUser-GS.sf2": "GeneralUser GS (recommandée)", "sonivox.sf2": "Sonivox (légère)"}


def soundfonts() -> list[tuple[str, str]]:
    """[(nom de fichier, libellé)] des banques de sons .sf2 présentes, la meilleure d'abord (GeneralUser GS, puis les
    autres par ordre alphabétique, Sonivox en dernier)."""
    folder = ALPHATAB / "soundfont"
    names = sorted(p.name for p in folder.glob("*.sf2")) if folder.is_dir() else []
    names.sort(key=lambda n: (n != "GeneralUser-GS.sf2", n == "sonivox.sf2"))
    return [(n, SOUNDFONT_LABELS.get(n, n[:-4].replace("_", " ").replace("-", " "))) for n in names]


def soundfont_installed() -> bool:
    return bool(soundfonts())


def soundfont_url(choice: str = "auto") -> str:
    """URL de la banque choisie (« auto » ou nom absent : la meilleure installée)."""
    available = [n for n, _ in soundfonts()]
    name = choice if choice in available else (available[0] if available else "sonivox.sf2")
    return f"/alphatab/soundfont/{name}"


class _Handler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        path = path.split("?", 1)[0].split("#", 1)[0]
        if path.startswith("/alphatab/"):
            root, rel = ALPHATAB, path[len("/alphatab/"):]
        else:
            root, rel = WEB, path.lstrip("/") or "tab_view.html"
        target = (root / rel).resolve()
        return str(target) if root.resolve() in target.parents or target == root.resolve() else str(root / "__404__")

    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class TabServer:
    def __init__(self):
        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="tab-server", daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._httpd.shutdown()
        self._httpd.server_close()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/tab_view.html"