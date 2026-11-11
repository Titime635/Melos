"""Assemblage de l'éditeur : dossiers de données (à côté du fichier de réglages, hors dépôt) et construction du service."""

from pathlib import Path

LIBRARY_DIRNAME = "preset_library"
BACKUPS_DIRNAME = "preset_backups"
LINKS_FILENAME = "preset_slot_links.json"


def data_root() -> Path:
    from paths import SETTINGS_FILE
    return Path(SETTINGS_FILE).parent


def library_dir() -> Path:
    return data_root() / LIBRARY_DIRNAME


def backups_dir() -> Path:
    return data_root() / BACKUPS_DIRNAME


def links_file() -> Path:
    return data_root() / LINKS_FILENAME


def build_editor(sender, listener, parent=None):
    """Rend (service, bibliothèque). `sender` et `listener` : les instances uniques de l'appli (cf main.py)."""
    from .amp_io import AmpIO, MidiTransport
    from .bank import EditorBank
    from .library import BackupStore, PresetLibrary
    from .links import SlotLinks
    from .service import EditorService
    from .workbench import Workbench

    io = AmpIO(MidiTransport(sender, listener))
    bank = EditorBank(io, BackupStore(backups_dir()))
    library = PresetLibrary(library_dir())
    wb = Workbench(bank, library, SlotLinks(links_file()))
    return EditorService(bank, wb, parent), library