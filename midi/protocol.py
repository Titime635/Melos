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

# --- Volume de la batterie ---
# Le CC 79 couvre 0-127 mais la batterie devient insupportable dès ~20 % (≈ 25) : le curseur de l'UI
# (0-100 %) est donc ramené sur la plage réellement utilisable, avec une courbe qui laisse plus de
# finesse dans les bas volumes. À ajuster ici si le plafond est trop haut/bas.
DRUM_LEVEL_CC_CAP = 32     # valeur CC envoyée quand le curseur est à 100 %
DRUM_LEVEL_GAMMA = 1.5     # > 1 : plus de finesse dans les bas volumes


def drum_level_from_percent(percent: int) -> int:
    """Position du curseur (0-100) -> valeur CC envoyée à l'ampli."""
    p = max(0, min(100, percent)) / 100
    return round(DRUM_LEVEL_CC_CAP * p ** DRUM_LEVEL_GAMMA)


def drum_percent_from_level(level: int) -> int:
    """Valeur CC de l'ampli -> position du curseur (0-100), plafonnée à 100."""
    r = max(0, min(level, DRUM_LEVEL_CC_CAP)) / DRUM_LEVEL_CC_CAP
    return round(100 * r ** (1 / DRUM_LEVEL_GAMMA))


# --- Presets ---
CHANNELS_COUNT = 7  # presets 0 à 6

# --- Tuner ---
CC_TUNER_STATE = 11
CC_TUNER_NOTE = 12
CC_TUNER_NUMBER = 71   # numéro de corde
CC_TUNER_CENT = 72     # écart en cents - zéro exact à confirmer avec une corde bien accordée

TUNER_REF_PITCH_440HZ = 10  # valeur vue dans mightier_amp (440 Hz)
TUNER_REF_HZ_MIN, TUNER_REF_HZ_MAX = 430, 450   # HYPOTHÈSE : octet de référence = Hz - 430 (10 = 440 Hz), à valider sur l'ampli


TUNER_NOTE_BASE = 9   # CC 12 = classe de hauteur 0-11 comptée à partir du LA (0 = A, 7 = E...), mesuré sur l'ampli


def tuner_pitch_class(cc12: int, shift: int = 0) -> int:
    """Classe de hauteur (0 = Do ... 11 = Si) à partir du CC 12 de l'ampli (+ correction éventuelle en demi-tons)."""
    return (int(cc12) + TUNER_NOTE_BASE + int(shift)) % 12


def tuner_ref_byte(hz: int) -> int:
    return max(TUNER_REF_HZ_MIN, min(TUNER_REF_HZ_MAX, int(hz))) - TUNER_REF_HZ_MIN

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
SYX_DRUM = 0x19  # réglages de la batterie (dont le tempo), cf mightier_amp : sendDrumsTempo

DRUM_TEMPO_MIN = 40
DRUM_TEMPO_MAX = 240

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


def build_drum_sysex(enabled: bool, style: int, level: int, bass: int, middle: int, treble: int, bpm: int) -> list[int]:
    """SysEx "réglages batterie" : le tempo ne passe pas par un CC, il voyage avec TOUS les réglages
    de la batterie (on renvoie donc les valeurs courantes). Tempo sur 2 octets 7 bits (poids fort,
    poids faible), comme dans mightier_amp. Sans les octets 0xF0/0xF7 (mido les ajoute)."""
    bpm = max(DRUM_TEMPO_MIN, min(DRUM_TEMPO_MAX, int(round(bpm))))
    data = [1 if enabled else 0, style, level, bass, middle, treble, bpm >> 7, bpm & 0x7F]
    return SYSEX_VENDOR + [SYSEX_PRIVATE, SYX_DRUM, SYXDIR_SET] + [d & 0x7F for d in data]