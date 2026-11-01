"""
Installe (ou complète) tous les fichiers volumineux qui ne sont pas dans git : libmpv, alphaTab + police, banque de sons.

    .venv\\Scripts\\python.exe tools\\setup_deps.py          # ne télécharge que ce qui manque
    .venv\\Scripts\\python.exe tools\\setup_deps.py --force  # retélécharge tout

À lancer une fois après un clone / un pull sur un nouvel ordinateur (main.py signale ce qui manque au démarrage).
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "tabs" / "vendor" / "alphatab"

# (nom, fichier qui prouve la présence, script, obligatoire ?)
DEPS = [
    ("libmpv (lecture de l'audio original)", ROOT / "mpv-2.dll", "fetch_libmpv.py", sys.platform == "win32"),
    ("alphaTab + police Bravura (partitions)", VENDOR / "alphaTab.min.js", "fetch_alphatab.py", True),
    ("banque de sons GeneralUser GS (synthèse)", VENDOR / "soundfont" / "GeneralUser-GS.sf2", "fetch_soundfonts.py", False),
]


def missing_deps() -> list[str]:
    """Libellés des dépendances absentes (la banque de sons seule est facultative : Sonivox, plus légère, sert de secours)."""
    out = [name for name, marker, _, required in DEPS if required and not marker.exists()]
    if (VENDOR / "alphaTab.min.js").exists() and not any((VENDOR / "soundfont").glob("*.sf2")):
        out.append("banque de sons (synthèse)")
    return out


def main(argv: list[str]) -> int:
    force = "--force" in argv
    failed = []
    for name, marker, script, required in DEPS:
        if script == "fetch_libmpv.py" and sys.platform != "win32":
            print(f"[ignoré]   {name} (Windows uniquement)")
            continue
        if marker.exists() and not force:
            print(f"[déjà là]  {name}")
            continue
        if script == "fetch_libmpv.py" and sys.platform != "win32":
            print(f"[ignoré]   {name} (Windows uniquement)")
            continue
        print(f"[télécharge] {name}")
        code = subprocess.run([sys.executable, str(ROOT / "tools" / script)]).returncode
        if code != 0 or not marker.exists():
            failed.append(name)
            print(f"[ÉCHEC]    {name} (voir le message ci-dessus ; lance « {script} » seul pour réessayer)")
    if failed:
        print("\nManquent encore :", ", ".join(failed))
        return 1
    print("\nTout est installé.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
