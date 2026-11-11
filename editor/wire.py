"""
Messages MIDI du Mighty Plug Pro pour l'éditeur, sous forme de tuples neutres (aucune dépendance mido) :
    ("cc", controle, valeur)      ("syx", [octets sans F0/F7])
Formats vérifiés sur l'ampli en USB (cf tools/probe_presets.py) :
    demande  F0 43 58 70 0B 02 <emplacement> F7  ->  F0 43 58 70 0B 02 <emplacement> <128 octets> F7
    demande  F0 43 58 70 0C 02 F7                ->  F0 43 58 70 0C 02 <emplacement courant> <128 octets> F7
    demande  F0 43 58 70 0D 02 F7                ->  F0 43 58 70 0D 02 <9 blocs> F7  (envoi : dir 1 + [n, blocs...])
    sauvegarde F0 43 58 70 75 01 30 <emplacement> F7 -> B0 7F 01 puis F0 43 58 70 75 03 30 <emplacement> .. F7
"""

from .catalog import CC_MASTER, IDX_MASTER, PRESET_LEN, get_catalog
from .preset import FX_IDS, Preset

HEADER = [0x43, 0x58, 0x70]
SYX_PRESET, SYX_CURPRESET, SYX_MODULELINK, SYX_SPEC_CMD = 0x0B, 0x0C, 0x0D, 0x75
DIR_SET, DIR_REQ, DIR_ACK = 1, 2, 3
SYSCMD_SAVE = 48
CC_SAVE_ACK = 0x7F


def request_preset(slot: int):
    return ("syx", HEADER + [SYX_PRESET, DIR_REQ, slot])


def request_current():
    return ("syx", HEADER + [SYX_CURPRESET, DIR_REQ])


def request_order():
    return ("syx", HEADER + [SYX_MODULELINK, DIR_REQ])


def set_order(order):
    order = list(order)
    return ("syx", HEADER + [SYX_MODULELINK, DIR_SET, len(order)] + order)


def save_slot(slot: int):
    return ("syx", HEADER + [SYX_SPEC_CMD, DIR_SET, SYSCMD_SAVE, slot])


def parse_preset_reply(data):
    """Réponse 0x0B : (emplacement, 128 octets) ou None."""
    d = list(data)
    if d[:3] == HEADER and d[3] == SYX_PRESET and d[4] == 2 and len(d) >= 6 + PRESET_LEN:
        return d[5], d[6:6 + PRESET_LEN]
    return None


def parse_current_reply(data):
    d = list(data)
    if d[:3] == HEADER and d[3] == SYX_CURPRESET and d[4] == 2 and len(d) >= 6 + PRESET_LEN:
        return d[5], d[6:6 + PRESET_LEN]
    return None


def parse_order_reply(data):
    d = list(data)
    if d[:3] == HEADER and d[3] == SYX_MODULELINK and d[4] == 2 and len(d) >= 6:
        return d[6:6 + d[5]]
    return None


def is_save_ack(data, slot: int) -> bool:
    d = list(data)
    return d[:3] == HEADER and d[3] == SYX_SPEC_CMD and d[4] == DIR_ACK and d[5:7] == [SYSCMD_SAVE, slot]


# --- Construction des envois à partir de presets ---
def block_messages(p: Preset, fid: int):
    """Sélection/activation du bloc puis tous ses paramètres (le modèle change : l'ampli remet ses défauts)."""
    e = get_catalog().effects[fid]
    out = [("cc", fid, p.data[fid])]
    out += [("cc", e.cc_for(j), p.data[e.param_index + j]) for j in range(e.param_slots)]
    return out


def full_messages(p: Preset):
    """Tout ce qu'il faut envoyer pour que le preset courant de l'ampli devienne `p`."""
    out = []
    for fid in FX_IDS:
        out += block_messages(p, fid)
    out.append(("cc", CC_MASTER, p.master))
    out.append(set_order(p.order))
    return out


def diff_messages(old: Preset, new: Preset):
    """Le strict nécessaire pour passer de `old` à `new` sur l'ampli (édition en direct)."""
    out = []
    for fid in FX_IDS:
        e = get_catalog().effects[fid]
        if old.data[fid] & 0x3F != new.data[fid] & 0x3F:
            out += block_messages(new, fid)                   # modèle changé : on renvoie tout le bloc
            continue
        if old.data[fid] != new.data[fid]:
            out.append(("cc", fid, new.data[fid]))            # activation seule
        for j in range(e.param_slots):
            a, b = old.data[e.param_index + j], new.data[e.param_index + j]
            if a != b:
                out.append(("cc", e.cc_for(j), b))
    if old.master != new.master:
        out.append(("cc", CC_MASTER, new.master))
    if old.order != new.order:
        out.append(set_order(new.order))
    return out
