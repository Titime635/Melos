"""
Emplacements des fichiers de données et de journal (tous à côté du code, comme avant).

Centralisé ici pour que la page Réglages (ouvrir le dossier, exporter, réinitialiser, journal) et
main.py parlent des mêmes fichiers.
"""

from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = APP_DIR / "app_settings.json"
PRESET_NAMES_FILE = APP_DIR / "ui" / "preset_names.json"   # historique : à côté de ui/preset_panel.py
SETLISTS_FILE = APP_DIR / "setlists.json"
LOG_FILE = APP_DIR / "melos_debug.log"      # journal des évènements (connexion, raccourcis, presets...)
CRASH_FILE = APP_DIR / "melos_crash.log"    # piles de tous les threads si l'appli gèle ou plante
