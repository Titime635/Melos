"""
Constantes du protocole MIDI du NUX Mighty Plug Pro.

Toutes les valeurs de ce fichier ont été vérifiées empiriquement
(voir /docs/protocol_notes.md pour le détail des tests).
"""

# --- Ports MIDI ---
# Sous Windows, mido nomme les ports "<nom> <index>" où l'index est la position
# dans la liste des ports (ex: "NUX NMP-03 0" en entrée, "NUX NMP-03 1" en
# sortie parce que "Microsoft GS Wavetable Synth" occupe la sortie 0) et Windows
# peut préfixer le nom ("2- NUX NMP-03") après un changement de prise USB. Ces
# noms ne sont donc PAS stables : on retrouve le port par mot-clé.
PORT_KEYWORD = "NUX NMP-03"


def find_port(names: list[str]) -> str | None:
    """Premier port dont le nom contient PORT_KEYWORD (insensible à la casse)."""
    keyword = PORT_KEYWORD.lower()
    for name in names:
        if keyword in name.lower():
            return name
    return None

# --- Presets ---
CHANNELS_COUNT = 7  # presets 0 à 6

# --- Tuner ---
CC_TUNER_STATE = 11
CC_TUNER_NOTE = 12
CC_TUNER_NUMBER = 71   # numéro de corde
CC_TUNER_CENT = 72     # écart en cents - zéro exact à confirmer avec une corde bien accordée

TUNER_REF_PITCH_440HZ = 10  # valeur vue dans mightier_amp, pas d'autre choix exposé en UI

# --- Batterie d'accompagnement ---
CC_DRUMENABLE = 77
CC_DRUMTYPE = 78
CC_DRUMLEVEL = 79
CC_DRUM_BASS = 104
CC_DRUM_MIDDLE = 105
CC_DRUM_TREBLE = 106

# --- SysEx (nécessaires pour le tuner, PAS pour la batterie) ---
SYSEX_START = 0xF0
SYSEX_END = 0xF7
SYSEX_VENDOR = [0x43, 0x58]  # header vendor NUX, confirmé fonctionnel
SYSEX_PRIVATE = 0x70
SYX_TUNER_SETTINGS = 0x6F
SYXDIR_GET = 0
SYXDIR_SET = 1
SYXDIR_REQ = 2

# Noms de notes pour l'affichage
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_name(midi_note: int) -> str:
    if 0 <= midi_note < 128:
        return f"{NOTE_NAMES[midi_note % 12]}{midi_note // 12 - 1}"
    return str(midi_note)


def build_tuner_sysex(tuner_on: bool, mode: int = 0, ref_pitch: int = 10, muted: bool = False) -> list[int]:
    """
    Construit le payload SysEx d'activation/config du tuner (sans les octets
    0xF0/0xF7 — mido les ajoute automatiquement quand on passe `data=`).

    mode: 0=chromatique, 1=guitare compensée, 2=guitare standard, 3=basse
    ref_pitch: 10 = 440Hz (valeur par défaut vue dans mightier_amp)
    """
    data = [1 if tuner_on else 0, mode, ref_pitch, 1 if muted else 0, 0, 0, 0]
    return SYSEX_VENDOR + [SYSEX_PRIVATE, SYX_TUNER_SETTINGS, SYXDIR_SET] + data