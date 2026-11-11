"""
Un preset du Mighty Plug Pro, en mémoire : les 128 octets de l'ampli avec des accesseurs qui respectent le
catalogue (valeurs bornées, modèles connus). Aucune dépendance MIDI ni Qt.
"""

from .catalog import (CC_MASTER, DISABLED_BIT, IDX_LINK1, IDX_MASTER, IDX_NAME, LINK_COUNT, MASTER_MAX, MODEL_MASK,
                      NAME_LEN, PRESET_LEN, get_catalog)

FX_IDS = tuple(range(1, 10))           # CMP, EFX, AMP, EQ, NG, MOD, DLY, RVB, CAB
DEFAULT_ORDER = (5, 1, 2, 3, 9, 4, 6, 7, 8)    # NG, CMP, EFX, AMP, CAB, EQ, MOD, DLY, RVB
IDX_BPM_H, IDX_BPM_L = 86, 87
# Octets que l'ampli accepte par CC / SysEx d'ordre ; le reste (85-88 tempo/drapeaux du delay, 100-127 nom et fin)
# est conservé dans le preset mais ne peut pas être poussé à l'ampli : voir Preset.wire_bytes()
_TAIL = bytes([1, 0, 0, 1, 2, 0x4D, 0, 0, 0, 0, 0, 7])
# Squelette des octets constants d'un preset (relevés identiques sur les 7 emplacements de l'ampli) : octets 11-13
# (en-tête du WAH), « nombres de paramètres » de chaque bloc (2,2,7,7,2,4,4,3,6,2) et fin de preset.
_SKELETON_CONST = {11: 2, 12: 0x32, 13: 0, 14: 2, 26: 7, 35: 7, 48: 2, 53: 4, 60: 4, 69: 3, 74: 6, 81: 2, 19: 2,
                   82: 50, 83: 50, 33: 50, 34: 50, 42: 50, 43: 50, 44: 50, 45: 50, 46: 50, 47: 50}   # + remplissage à 50


class Preset:
    __slots__ = ("data",)

    def __init__(self, data=None):
        if data is None:
            data = self._blank()
        data = bytearray(data)
        if len(data) < IDX_NAME:
            raise ValueError(f"preset trop court ({len(data)} octets)")
        if len(data) < PRESET_LEN:                      # 116 octets (ancien format) : on complète la fin
            data += bytearray(PRESET_LEN - len(data))
            data[116:] = _TAIL
        if any(b > 0x7F for b in data[:PRESET_LEN]):
            raise ValueError("octet > 127 : ce n'est pas un preset du Mighty")
        self.data = data[:PRESET_LEN]

    # --- Construction ---
    @staticmethod
    def _blank() -> bytearray:
        cat = get_catalog()
        d = bytearray(PRESET_LEN)
        d[0] = d[10] = 0x41                            # WAH et SR : inutilisés sur le Plug Pro
        for i, v in _SKELETON_CONST.items():
            d[i] = v
        for fid in FX_IDS:
            e = cat.effects[fid]
            d[fid] = 1 | (0 if fid in (3, 9) else DISABLED_BIT)      # seuls l'ampli et le baffle sont actifs
        d[IDX_MASTER] = 50
        d[IDX_LINK1] = 0
        d[IDX_LINK1 + 1:IDX_LINK1 + 10] = bytes(DEFAULT_ORDER)
        d[IDX_LINK1 + 10] = 10
        d[IDX_NAME:IDX_NAME + 4] = b"NULL"
        d[116:] = _TAIL
        p = Preset.__new__(Preset)
        p.data = d
        for fid in FX_IDS:
            p.set_model(fid, 1, keep_enabled=True)
        return p.data

    @classmethod
    def default(cls) -> "Preset":
        return cls()

    @classmethod
    def from_hex(cls, text: str) -> "Preset":
        return cls(bytes.fromhex(text))

    def copy(self) -> "Preset":
        return Preset(self.data)

    def to_bytes(self) -> bytes:
        return bytes(self.data)

    def to_hex(self) -> str:
        return self.data.hex()

    def __eq__(self, other):
        return isinstance(other, Preset) and self.data == other.data

    def __hash__(self):
        return hash(bytes(self.data))

    # --- Blocs d'effet ---
    def model(self, fid: int) -> int:
        return self.data[fid] & MODEL_MASK

    def enabled(self, fid: int) -> bool:
        return not self.data[fid] & DISABLED_BIT

    def set_enabled(self, fid: int, on: bool):
        self.data[fid] = (self.data[fid] & MODEL_MASK) | (0 if on else DISABLED_BIT)

    def set_model(self, fid: int, index: int, *, reset_params: bool = True, apply_link: bool = True,
                  keep_enabled: bool = True):
        """Change le modèle d'un bloc. Comme dans MightyEditor : les paramètres repartent des valeurs
        par défaut du modèle, et un ampli entraîne son baffle habituel."""
        cat = get_catalog()
        e = cat.effects[fid]
        m = e.model(index)
        if m is None:
            raise ValueError(f"{e.key} : modèle {index} inconnu")
        on = self.enabled(fid) if keep_enabled else True
        self.data[fid] = index | (0 if on else DISABLED_BIT)
        if reset_params:
            for p in m.params:
                self.data[e.param_index + p.offset] = p.default
        if apply_link and fid == 3 and m.link and m.link["cab"] in cat.cab_by_name:
            self.set_model(9, cat.cab_by_name[m.link["cab"]], apply_link=False)
            cab = cat.effects[9]
            for off, key in enumerate(("level", "low_cut", "high_cut")):
                self.data[cab.param_index + off] = m.link[key]

    def param(self, fid: int, offset: int) -> int:
        return self.data[get_catalog().effects[fid].param_index + offset]

    def set_param(self, fid: int, offset: int, value: int) -> int:
        """Écrit un paramètre (borné d'après le catalogue) et rend la valeur réellement retenue."""
        e = get_catalog().effects[fid]
        if not 0 <= offset < e.param_slots:
            raise ValueError(f"{e.key} : paramètre {offset} inexistant")
        m = e.model(self.model(fid))
        pdef = next((p for p in m.params if p.offset == offset), None) if m else None
        v = pdef.clamp(value) if pdef else max(0, min(127, int(value)))
        self.data[e.param_index + offset] = v
        return v

    def reset_params(self, fid: int):
        """Remet les réglages du modèle courant d'un bloc à leurs valeurs par défaut (modèle et on/off inchangés)."""
        e = get_catalog().effects[fid]
        m = e.model(self.model(fid))
        for p in (m.params if m else ()):
            self.data[e.param_index + p.offset] = p.default

    def params(self, fid: int) -> list[int]:
        e = get_catalog().effects[fid]
        return list(self.data[e.param_index:e.param_index + e.param_slots])

    # --- Volume, tempo, ordre ---
    @property
    def master(self) -> int:
        return self.data[IDX_MASTER]

    @master.setter
    def master(self, v: int):
        self.data[IDX_MASTER] = max(0, min(MASTER_MAX, int(v)))

    @property
    def bpm(self) -> int:
        return (self.data[IDX_BPM_H] << 7) | self.data[IDX_BPM_L]

    @property
    def order(self) -> list[int]:
        """Ordre des blocs dans la chaîne (identifiants 1..9, du premier au dernier)."""
        return [v for v in self.data[IDX_LINK1:IDX_LINK1 + LINK_COUNT] if 1 <= v <= 9]

    def set_order(self, order):
        order = [int(v) for v in order]
        if sorted(order) != list(FX_IDS):
            raise ValueError("l'ordre doit contenir chaque bloc 1..9 exactement une fois")
        self.data[IDX_LINK1] = 0
        self.data[IDX_LINK1 + 1:IDX_LINK1 + 10] = bytes(order)
        self.data[IDX_LINK1 + 10] = 10

    def move_block(self, fid: int, new_pos: int):
        o = self.order
        o.remove(fid)
        o.insert(max(0, min(8, new_pos)), fid)
        self.set_order(o)

    # --- Comparaison avec ce que l'ampli sait recevoir ---
    def wire_bytes(self) -> bytes:
        """Les octets que l'envoi par CC / SysEx d'ordre sait reproduire sur l'ampli (le reste est masqué)."""
        out = bytearray(self.data)
        for i in (*range(85, 89), *range(IDX_NAME, PRESET_LEN)):
            out[i] = 0
        return bytes(out)

    # --- Affichage ---
    def describe(self) -> list[str]:
        cat = get_catalog()
        lines = []
        for fid in FX_IDS:
            e = cat.effects[fid]
            m = e.model(self.model(fid))
            vals = ", ".join(f"{p.name}={self.param(fid, p.offset)}" for p in m.params) if m else "?"
            lines.append(f"{e.key:3} {'ON ' if self.enabled(fid) else 'off'} {m.name if m else '?':14} {vals}")
        lines.append("ordre : " + " > ".join(cat.effects[f].key for f in self.order))
        lines.append(f"volume : {self.master}")
        return lines