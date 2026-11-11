"""
Fichiers .mppropatch de MightyEditor : u32 LE (emplacement, 0-6) | 128 octets de preset | 80 octets d'extras
(dont le nom du baffle en ASCII) | 2048 flottants 32 bits (la réponse impulsionnelle du baffle) = 8404 octets.
Lecture seule pour l'instant : l'export demande les IR d'usine (à extraire de MightyEditor.exe, cf. roadmap).
"""

import struct
from dataclasses import dataclass
from pathlib import Path

from .catalog import PRESET_LEN
from .preset import Preset

EXTRAS_END = 0xD4
PATCH_SIZE = 8404


@dataclass
class PatchFile:
    slot: int                    # 0-6
    preset: Preset
    cab_name: str
    ir: tuple                    # 2048 flottants


def read_mppropatch(path) -> PatchFile:
    b = Path(path).read_bytes()
    if len(b) != PATCH_SIZE:
        raise ValueError(f"{Path(path).name} : {len(b)} octets, un .mppropatch en fait {PATCH_SIZE}")
    slot = struct.unpack_from("<I", b, 0)[0]
    if slot > 6:
        raise ValueError(f"emplacement {slot} invalide")
    preset = Preset(b[4:4 + PRESET_LEN])
    extras = b[4 + PRESET_LEN:EXTRAS_END]
    cab = extras[4:36].split(b"\0")[0].decode("ascii", "replace")
    n = (len(b) - EXTRAS_END) // 4
    return PatchFile(slot, preset, cab, struct.unpack(f"<{n}f", b[EXTRAS_END:EXTRAS_END + 4 * n]))
