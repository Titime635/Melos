r"""
Sonde matérielle du NUX Mighty Plug Pro : lecture des 7 presets en SysEx, comparaison avec des fichiers .mppropatch
exportés par MightyEditor, et mesure du temps de (re)chargement d'un preset par CC.

NE SAUVEGARDE JAMAIS rien dans l'ampli (aucune commande « save »). La commande `timing` modifie seulement le preset
EN COURS D'ÉDITION de l'emplacement testé ; il est annulé en changeant de preset (comportement vérifié), et le script
le fait lui-même à la fin.

AVANT DE LANCER : fermer Melos (le port MIDI ne peut être ouvert que par une appli à la fois sous Windows) et
MightyEditor.

    .venv\Scripts\python.exe tools\probe_presets.py ports
    .venv\Scripts\python.exe tools\probe_presets.py read
    .venv\Scripts\python.exe tools\probe_presets.py compare preset1.mppropatch preset5.mppropatch ...
    .venv\Scripts\python.exe tools\probe_presets.py timing --slot 2 --delays 0,5,20
    .venv\Scripts\python.exe tools\probe_presets.py cabmap --slot 2 --only CAB
    .venv\Scripts\python.exe tools\probe_presets.py snap avant   puis   snap apres   puis   snapdiff avant apres
    .venv\Scripts\python.exe tools\probe_presets.py savetest --slot 2     (ÉCRIT dans l'emplacement, puis restaure)

Tout est écrit dans le dossier probe_presets_out/ (à m'envoyer en entier : report.txt, presets_raw.json, frames.log).
"""

import argparse
import json
import struct
import sys
import time
from pathlib import Path

PORT_KEYWORD = "NUX NMP-03"
OUT_DIR = Path("probe_presets_out")

# --- Protocole (d'après Mightier Amp, à confirmer par cette sonde) ---------------------------------------------------
HEADER = [0x43, 0x58, 0x70]                 # constructeur NUX + « privé »
SYX_PRESET, SYX_CURPRESET, SYX_MODULELINK = 0x0B, 0x0C, 0x0D
DIR_SET, DIR_REQ = 1, 2

# type d'effet -> (nom, octet de tête = CC de sélection, premier octet de paramètre, nb de paramètres, premier CC de paramètre)
FX = {
    1: ("CMP", 14, 15, 4, 13),
    2: ("EFX", 19, 20, 6, 17),
    3: ("AMP", 26, 27, 8, 23),
    4: ("EQ", 35, 36, 12, 31),
    5: ("NG", 48, 49, 4, 43),
    6: ("MOD", 53, 54, 6, 47),
    7: ("DLY", 60, 61, 8, 53),
    8: ("RVB", 69, 70, 4, 61),
    9: ("CAB", 74, 75, 6, 65),
}
IDX_MASTER, CC_MASTER = 84, 73
IDX_LINK1, IDX_NAME, PRESET_LEN = 89, 100, 128       # un preset = 128 octets (lecture SysEx USB ET .mppropatch)

# Noms des modèles et des paramètres (extraits de MightyEditor.exe) : {type: {index: [nom, [paramètres par offset]]}}
TABLES = {int(k): {int(i): v for i, v in d.items()} for k, d in json.loads(r"""{"1":{"1":["Rose Comp",["Sustain","Level"]],"2":["K Comp",["Sustain","Level","Clipping"]],"3":["Studio Comp",["Thr","Ratio","Gain","Release"]]},"2":{"1":["Distortion+",["Output","Sensitivity"]],"2":["RC Boost",["Gain","Volume","Bass","Treble"]],"3":["AC Boost",["Gain","Volume","Bass","Treble"]],"4":["Dist One",["Level","Tone","Drive"]],"5":["T Screamer",["Drive","Tone","Level"]],"6":["Blues Drv",["Level","Tone","Gain"]],"7":["Morning Drv",["Volume","Drive","Tone"]],"8":["Eat Dist",["Distortion","Filter","Volume"]],"9":["Red Dirt",["Drive","Tone","Level"]],"10":["Crunch",["Volume","Tone","Gain"]],"11":["Muff Fuzz",["Volume","Tone","Sustain"]],"12":["Katana",["Boost","Volume"]],"13":["ST Singer",["Volume","Gain","Filter"]],"14":["Touch Wah",["Type","Wow","Sense","UP/DN Switch","Level"]]},"3":{"1":["Jazz Clean",["Gain","Master","Bass","Middle","Treble","Bright"]],"2":["Deluxe Rvb",["Gain","Master","Bass","Middle","Treble"]],"3":["Bass Mate",["Gain","Master","Bass","Middle","Treble","Presence"]],"4":["Tweedy",["Gain","Master","Tone"]],"5":["Twin Rvb",["Gain","Master","Bass","Middle","Treble","Bright"]],"6":["Hiwire",["Gain","Master","Bass","Middle","Treble","Presence"]],"7":["Cali Crunch",["Gain","Master","Bass","Middle","Treble","Presence"]],"8":["Class A15",["Gain","Master","Bass","Treble","Cut"]],"9":["Class A30",["Gain","Master","Bass","Treble","Cut"]],"10":["Plexi 100",["Gain","Master","Bass","Middle","Treble","Presence"]],"11":["Plexi 45",["Gain","Master","Bass","Middle","Treble","Presence"]],"12":["Brit 800",["Gain","Master","Bass","Middle","Treble","Presence"]],"13":["1987 X 50",["Gain","Master","Bass","Middle","Treble","Presence"]],"14":["Slo 100",["Gain","Master","Bass","Middle","Treble","Presence"]],"15":["Fireman HBE",["Gain","Master","Bass","Middle","Treble","Presence"]],"16":["Dual Rect",["Gain","Master","Bass","Middle","Treble","Presence"]],"17":["Die VH4",["Gain","Master","Bass","Middle","Treble","Presence"]],"18":["Vibro King",["Gain","Master","Bass","Middle","Treble","Bright"]],"19":["Budda",["Gain","Master","Bass","Middle","Treble","Cut"]],"20":["Mr. Z38",["Gain","Master","Bass","Middle","Treble","Cut"]],"21":["Super Rvb",["Gain","Master","Bass","Middle","Treble","Bright"]],"22":["Brit Blues",["Gain","Master","Bass","Middle","Treble","Presence"]],"23":["Match",["Gain","Master","Bass","Treble","Cut"]],"24":["Brit 2000",["Gain","Master","Bass","Middle","Treble","Presence"]],"25":["Uber",["Gain","Master","Bass","Middle","Treble","Presence"]],"26":["AGL",["Gain","Master","Bass","Middle","Treble","Mid Freq"]],"27":["MLD",["Gain","Master","Bass","Middle","Treble","Mid Freq"]],"28":["Optima Air",["Gain","Master","Bass","Middle","Treble"]],"29":["Stageman",["Gain","Master","Bass","Middle","Treble"]]},"4":{"1":["6-Band",["100","220","500","1.2K","2.6K","6.4K"]],"3":["10-Band",["Vol","31.25","62.5","125","250","500","1K","2K","4K","8K","16K"]]},"5":{"1":["Noise Gate",["Sens","Decay"]]},"6":{"1":["CE-1",["Intensity","Depth","Rate"]],"2":["CE-2",["Rate","Depth"]],"3":["ST Chorus",["Intensity","Width","Rate"]],"4":["Vibrato",["Rate","Depth"]],"5":["Detune",["Shift-L","Mix","Shift-R"]],"6":["Flanger",["Level","Rate","Width","F.Back"]],"7":["Phase 90",["Speed"]],"8":["Phase 100",["Intensity","Speed"]],"9":["S.C.F.",["Speed","Width","Mode","Intensity"]],"10":["U-Vibe",["Speed","Volume","Intensity","Mode"]],"11":["Tremolo",["Rate","Depth"]],"12":["Rotary",["Balance","Speed"]],"13":["SCH-1",["Rate","Depth","Tone"]],"14":["Mono Octave",["Sub","Dry","Up"]]},"7":{"1":["Analog",["Rate","Echo","Intensity"]],"2":["Digital",["E.Level","F.Back","D.Time"]],"3":["Modulation",["D-Time","D-Level","Mod","Repeat"]],"4":["Tape Echo",["Time","Level","Repeat"]],"5":["Pan Delay",["Pan D.Time","Repeat","D.Level"]],"6":["Phi Delay",["Time","Repeat","Mix"]]},"8":{"1":["Room",["Decay","Tone","Level"]],"2":["Hall",["Decay","Pre Delay","Liveliness","Level"]],"3":["Plate",["Decay","Level"]],"4":["Spring",["Decay","Level"]],"5":["Shimmer",["Mix","Decay","Shim"]],"6":["Damp",["Mix","Depth"]]},"9":{"1":["JZ120",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"2":["DR112",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"3":["TR212",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"4":["HIWIRE412",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"5":["CALI 112",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"6":["A112",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"7":["GB412",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"8":["M1960AX",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"9":["M1960AV",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"10":["M1960TV",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"11":["SLO412",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"12":["FIREMAN 412",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"13":["RECT 412",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"14":["DIE412",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"15":["MATCH212",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"16":["UBER412",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"17":["BS410",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"18":["A212",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"19":["M1960AHW",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"20":["M1936",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"21":["BUDDA112",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"22":["Z212",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"23":["SUPERVERB410",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"24":["VIBROKING310",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"25":["AGL_DB810",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"26":["AMP_SV212",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"27":["AMP_SV410",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"28":["AMP_SV810",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"29":["BASSGUY410",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"30":["EDEN410",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"31":["MKB410",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"32":["G-HBIRD",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"33":["G-J15",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"34":["M-D45",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"35":["USER 1",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"36":["USER 2",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"37":["USER 3",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"38":["USER 4",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"39":["USER 5",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"40":["USER 6",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"41":["USER 7",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"42":["USER 8",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"43":["USER 9",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"44":["USER 10",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"45":["USER 11",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"46":["USER 12",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"47":["USER 13",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"48":["USER 14",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"49":["USER 15",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"50":["USER 16",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"51":["USER 17",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"52":["USER 18",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"53":["USER 19",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]],"54":["USER 20",["Level (dB)","Low Cut (Hz)","High Cut (Hz)"]]}}""").items()}


# --- Liaison MIDI (réelle ou simulée pour les tests) ------------------------------------------------------------------
class MidoLink:
    def __init__(self, in_name: str, out_name: str):
        import mido
        self.mido = mido
        self.inp = mido.open_input(in_name)
        self.out = mido.open_output(out_name)
        self.t0 = time.perf_counter()
        self.frames: list[str] = []

    def log(self, way: str, msg):
        ms = (time.perf_counter() - self.t0) * 1000
        raw = msg.hex(" ") if hasattr(msg, "hex") else str(msg)
        self.frames.append(f"{ms:10.1f} ms {way} {raw}")

    def send(self, msg):
        self.out.send(msg)
        self.log("->", msg)

    def recv(self, timeout: float):
        end = time.perf_counter() + timeout
        while time.perf_counter() < end:
            msg = self.inp.poll()
            if msg is not None:
                self.log("<-", msg)
                return msg
            time.sleep(0.0005)
        return None

    def close(self):
        for p in (self.inp, self.out):
            try:
                p.close()
            except Exception:
                pass


def sysex(link, data):
    link.send(link.mido.Message("sysex", data=data))


def program_change(link, n):
    link.send(link.mido.Message("program_change", program=n))


def cc(link, control, value):
    link.send(link.mido.Message("control_change", control=control, value=value))


def drain(link, quiet=0.25):
    """Vide ce que l'ampli envoie encore ; rend les messages reçus."""
    got = []
    while True:
        m = link.recv(quiet)
        if m is None:
            return got
        got.append(m)


# --- Lectures SysEx ---------------------------------------------------------------------------------------------------
def read_preset(link, idx: int, timeout=3.0):
    """Demande le preset idx (mémoire sauvegardée). En USB la réponse est UN message :
    F0 43 58 70 0B 02 <idx> <octets du preset> F7 (pas d'octet « morceau n/total » comme en Bluetooth).
    Rend (octets du preset, 1, durée ms) ou (None, 0, durée) si rien."""
    t = time.perf_counter()
    sysex(link, HEADER + [SYX_PRESET, DIR_REQ, idx])
    end = t + timeout
    while time.perf_counter() < end:
        m = link.recv(0.05)
        if m is None or m.type != "sysex":
            continue
        d = list(m.data)
        if d[:4] == HEADER + [SYX_PRESET] and len(d) > 6 and d[5] == idx:
            return d[6:], 1, (time.perf_counter() - t) * 1000
    return None, 0, (time.perf_counter() - t) * 1000


def read_current(link, timeout=1.5):
    """Preset COURANT (0x0C) : F0 43 58 70 0C 02 <emplacement> <octets du preset> F7.
    Rend (emplacement 0-6, octets du preset) ou (None, None)."""
    sysex(link, HEADER + [SYX_CURPRESET, DIR_REQ])
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        m = link.recv(0.05)
        if m is not None and m.type == "sysex":
            d = list(m.data)
            if d[:4] == HEADER + [SYX_CURPRESET] and len(d) > 7:
                return d[5], d[6:]
    return None, None


def read_order(link, wait=0.6):
    sysex(link, HEADER + [SYX_MODULELINK, DIR_REQ])
    out, end = [], time.perf_counter() + wait
    while time.perf_counter() < end:
        m = link.recv(0.05)
        if m is not None and m.type == "sysex" and list(m.data)[:4] == HEADER + [SYX_MODULELINK]:
            out.append(list(m.data))
    return out


# --- Décodage ---------------------------------------------------------------------------------------------------------
def chain_order(p):
    return [v for v in p[IDX_LINK1:IDX_LINK1 + 11] if 1 <= v <= 9]


def describe(p) -> list[str]:
    lines = []
    for h, (tag, head_i, base, count, _) in FX.items():
        b = p[h] if h < len(p) else 0
        model, on = b & 0x3F, not b & 0x40
        name, pnames = TABLES.get(h, {}).get(model, [f"modèle {model}?", []])
        vals = [p[base + j] if base + j < len(p) else None for j in range(count)]
        ps = ", ".join(f"{(pnames[j] if j < len(pnames) else f'p{j}')}={v}" for j, v in enumerate(vals)
                       if j < max(len(pnames), 1) or v)
        lines.append(f"  {tag:3} {'ON ' if on else 'off'} {name:14} {ps}")
    order = chain_order(p)
    lines.append("  ordre : " + " > ".join(FX[h][0] for h in order))
    lines.append(f"  volume du preset (octet {IDX_MASTER}) : {p[IDX_MASTER] if len(p) > IDX_MASTER else '?'}")
    name = bytes(p[IDX_NAME:IDX_NAME + 16]).split(b"\0")[0] if len(p) > IDX_NAME else b""
    lines.append(f"  nom (octets 100-115) : {name.decode('ascii', 'replace')!r}")
    return lines


def diff(a, b):
    n = max(len(a), len(b))
    return [(i, a[i] if i < len(a) else None, b[i] if i < len(b) else None) for i in range(n)
            if (a[i] if i < len(a) else None) != (b[i] if i < len(b) else None)]


def index_name(i):
    if i == IDX_MASTER:
        return "volume"
    for h, (tag, head_i, base, count, _) in FX.items():
        if i == h:
            return f"{tag} type"
        if i == head_i:
            return f"{tag} compteur"
        if base <= i < base + count:
            return f"{tag} param {i - base}"
    if IDX_LINK1 <= i < IDX_LINK1 + 11:
        return f"ordre {i - IDX_LINK1}"
    if IDX_NAME <= i < IDX_NAME + 16:
        return f"nom {i - IDX_NAME}"
    return "?"


# --- .mppropatch ------------------------------------------------------------------------------------------------------
def parse_patch(path: Path):
    b = path.read_bytes()
    slot = struct.unpack_from("<I", b, 0)[0]
    preset = list(b[4:4 + PRESET_LEN])
    extras = b[4 + PRESET_LEN:0xD4]
    ir = b[0xD4:]
    floats = struct.unpack(f"<{len(ir) // 4}f", ir[:len(ir) // 4 * 4])
    cab = extras[4:36].split(b"\0")[0].decode("ascii", "replace")
    return {"slot": slot, "preset": preset, "extras": extras, "cab_name": cab, "ir_samples": len(floats),
            "ir_peak": max((abs(x) for x in floats), default=0.0), "size": len(b)}


# --- Commandes --------------------------------------------------------------------------------------------------------
def say(report, text=""):
    print(text)
    report.append(text)


def save_outputs(link, report, extra=None):
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "report.txt").write_text("\n".join(report), encoding="utf-8")
    if link is not None:
        (OUT_DIR / "frames.log").write_text("\n".join(link.frames), encoding="utf-8")
    if extra:
        for name, data in extra.items():
            (OUT_DIR / name).write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"\nFichiers écrits dans {OUT_DIR.resolve()}")


def cmd_ports(args, link=None):
    import mido
    print("Entrées :", mido.get_input_names())
    print("Sorties :", mido.get_output_names())


def cmd_read(link, args):
    report = []
    raw = {}
    say(report, "== Lecture des 7 presets en SysEx ==")
    for slot in range(7):
        payload, total, ms = read_preset(link, slot)
        if payload is None:
            say(report, f"Preset {slot + 1} : pas de réponse après {ms:.0f} ms")
            continue
        raw[str(slot)] = {"hex": bytes(payload).hex(), "length": len(payload), "pieces": total, "ms": round(ms)}
        say(report, f"Preset {slot + 1} : {len(payload)} octets, {ms:.0f} ms")
        for line in describe(payload):
            say(report, line)
    say(report, "\n== Preset courant (0x0C) ==")
    cur_slot, cur = read_current(link)
    if cur is None:
        say(report, "  pas de réponse")
    else:
        same = raw.get(str(cur_slot), {}).get("hex") == bytes(cur).hex()
        say(report, f"  emplacement courant : {cur_slot + 1} ; {len(cur)} octets ; "
                    f"{'identique' if same else 'DIFFÉRENT de'} la lecture 0x0B de cet emplacement")
    say(report, "\n== Ordre des effets (0x0D) ==")
    for d in read_order(link):
        say(report, "  " + bytes(d).hex(" "))
    save_outputs(link, report, {"presets_raw.json": raw})


def load_raw():
    p = OUT_DIR / "presets_raw.json"
    if not p.exists():
        sys.exit("Lance d'abord : probe_presets.py read")
    return {int(k): list(bytes.fromhex(v["hex"])) for k, v in json.loads(p.read_text()).items()}


def cmd_compare(link, args):
    report = []
    raw = load_raw()
    say(report, "== Comparaison .mppropatch <-> lecture SysEx ==")
    say(report, "(les presets ne doivent pas avoir été modifiés entre l'export et la lecture)")
    for f in args.files:
        pt = parse_patch(Path(f))
        say(report, f"\n{f} : emplacement {pt['slot'] + 1}, {pt['size']} octets, IR {pt['ir_samples']} échantillons "
                    f"(crête {pt['ir_peak']:.3f}), baffle « {pt['cab_name']} »")
        say(report, "  octets entre le preset et l'IR : " + pt["extras"].hex(" "))
        sysex_data = raw.get(pt["slot"])
        if sysex_data is None:
            say(report, "  pas de lecture SysEx pour cet emplacement")
            continue
        say(report, f"  SysEx : {len(sysex_data)} octets ; patch : {len(pt['preset'])} octets")
        common = min(len(sysex_data), len(pt["preset"]))     # normalement 128 des deux côtés
        diffs = diff(sysex_data[:common], pt["preset"][:common])
        if len(sysex_data) != len(pt["preset"]):
            say(report, f"  (comparaison sur les {common} premiers octets ; octets en plus côté SysEx : "
                        f"{sysex_data[common:]})")
        if not diffs:
            say(report, "  IDENTIQUES sur la partie comparée")
        for i, a, b in diffs:
            say(report, f"  octet {i:3} ({index_name(i)}) : SysEx={a}  patch={b}")
    save_outputs(link, report)


def burst_messages(p):
    """Messages pour recharger un preset par CC : modèle+activation, paramètres, volume, puis ordre en SysEx."""
    msgs = []
    for h, (tag, head_i, base, count, cc_base) in FX.items():
        msgs.append(("cc", h, p[h]))
        msgs += [("cc", cc_base + j, p[base + j]) for j in range(count) if base + j < len(p)]
    msgs.append(("cc", CC_MASTER, p[IDX_MASTER]))
    order = chain_order(p)
    msgs.append(("syx", HEADER + [SYX_MODULELINK, DIR_SET, len(order)] + order, None))
    return msgs


def play_burst(link, msgs, delay_ms):
    t = time.perf_counter()
    for kind, a, b in msgs:
        if kind == "cc":
            cc(link, a, b)
        else:
            sysex(link, a)
        if delay_ms:
            time.sleep(delay_ms / 1000)
    return (time.perf_counter() - t) * 1000


def snapshot(link, slot):
    """(lecture 0x0B de l'emplacement = mémoire sauvegardée, lecture 0x0C = preset courant)."""
    saved, _, _ = read_preset(link, slot)
    _, current = read_current(link)
    return saved, current


def cmd_timing(link, args):
    report = []
    slot = args.slot - 1
    other = (slot + 1) % 7
    delays = [float(x) for x in args.delays.split(",")]
    say(report, f"== Test sur l'emplacement {slot + 1} (jamais sauvegardé dans l'ampli) ==")

    def goto(n):
        program_change(link, n)
        time.sleep(1.0)
        drain(link)

    goto(slot)
    saved0, cur0 = snapshot(link, slot)
    if saved0 is None or cur0 is None:
        return say(report, "Lecture impossible (0x0B ou 0x0C sans réponse), arrêt.") or save_outputs(link, report)
    say(report, f"Départ : {len(saved0)} octets ; 0x0C {'identique' if cur0 == saved0 else 'différent'} de 0x0B.")
    a = saved0

    # 1. une modification par CC : laquelle des deux lectures la voit ?
    mod = list(a)
    mod[IDX_MASTER] = min(127, a[IDX_MASTER] + 5)
    mod[FX[3][2]] = min(100, a[FX[3][2]] + 10)
    cc(link, CC_MASTER, mod[IDX_MASTER])
    cc(link, FX[3][4], mod[FX[3][2]])
    time.sleep(0.5)
    drain(link)
    saved1, cur1 = snapshot(link, slot)
    say(report, "\n-- Une modification par CC (volume +5, gain ampli +10) --")
    say(report, "Lecture 0x0B (mémoire de l'emplacement) : " + ("INCHANGÉE" if saved1 == a else
                f"modifiée {[(i, index_name(i), x, y) for i, x, y in diff(a, saved1 or [])][:10]}"))
    say(report, "Lecture 0x0C (preset courant) : " + ("INCHANGÉE" if cur1 == a else
                f"modifiée {[(i, index_name(i), x, y) for i, x, y in diff(a, cur1 or [])][:10]}"))
    reads_edit = cur1 is not None and cur1 != a
    check = (lambda: snapshot(link, slot)[1]) if reads_edit else (lambda: snapshot(link, slot)[0])
    say(report, "=> pour vérifier les modifications, on relit par " + ("0x0C" if reads_edit else "0x0B"))

    # 2. changement de preset : la modification disparaît-elle ?
    goto(other)
    goto(slot)
    saved2, cur2 = snapshot(link, slot)
    say(report, "\n-- Après un aller-retour vers un autre preset --")
    say(report, "0x0B : " + ("identique au départ" if saved2 == a else f"différent {diff(a, saved2 or [])[:10]}"))
    say(report, "0x0C : " + ("identique au départ (modification perdue)" if cur2 == a else f"différent {diff(a, cur2 or [])[:10]}"))

    # 3. rechargement complet par CC, avec chronométrage
    say(report, "\n-- Rechargement complet par CC (copie de travail renvoyée) --")
    msgs = burst_messages(mod)
    say(report, f"{len(msgs)} messages à envoyer")
    results = {}
    for delay in delays:
        goto(other)
        goto(slot)
        ms = play_burst(link, msgs, delay)
        time.sleep(0.5)
        drain(link)
        e = check()
        d2 = diff(mod, e or [])
        if e is None:
            verdict = "relecture impossible"
        elif not d2:
            verdict = "conforme à la copie de travail"
        else:
            verdict = "écarts : " + str([(i, index_name(i), x, y) for i, x, y in d2][:16])
        say(report, f"pause de {delay:g} ms entre messages : envoi en {ms:.0f} ms ; relecture : {verdict}")
        results[str(delay)] = {"send_ms": round(ms), "mismatches": len(d2) if e is not None else None}

    # 4. retour à l'état d'origine
    goto(other)
    goto(slot)
    z = snapshot(link, slot)[1]
    say(report, "\nÉtat final : " + ("preset d'origine retrouvé" if z == a else "ATTENTION, différent du départ"))
    save_outputs(link, report, {"timing.json": results})


def cmd_savetest(link, args):
    """Teste (1) le délai réel d'un changement de preset, (2) la commande de sauvegarde en flash.
    ATTENTION : écrit dans l'emplacement choisi (modif de +1 sur le volume, puis restauration)."""
    report = []
    slot = args.slot - 1
    other = (slot + 1) % 7
    say(report, f"== Sauvegarde / délai de chargement, emplacement {slot + 1} ==")

    def settle(n, timeout=5.0):
        """Program Change puis relit 0x0C toutes les 5 ms ; rend (ms, données) quand l'ampli annonce n."""
        drain(link, 0.05)
        t0 = time.perf_counter()
        program_change(link, n)
        while time.perf_counter() - t0 < timeout:
            sl, d = read_current(link, 0.3) or (None, None)
            if sl == n and d:
                return (time.perf_counter() - t0) * 1000, d
            time.sleep(0.005)
        return None, None

    saved0, _, _ = read_preset(link, slot)
    if saved0 is None:
        return say(report, "Lecture impossible, arrêt.") or save_outputs(link, report)
    save_outputs(link, [], {"backup_slot%d.json" % (slot + 1): list(saved0)})
    say(report, "Sauvegarde de l'état d'origine : backup_slot%d.json" % (slot + 1))

    say(report, "\n-- Délai de chargement d'un preset (Program Change -> 0x0C annonce le bon emplacement) --")
    times = []
    for _ in range(3):
        for n in (other, slot):
            ms, d = settle(n)
            times.append(ms)
            ok = d is not None and (n != slot or d == saved0)
            say(report, f"vers {n + 1} : {'%.0f ms' % ms if ms is not None else 'pas de réponse'}"
                        f"{'' if ok else ' (données différentes de la mémoire !)'}")
            time.sleep(0.5)

    say(report, "\n-- Sauvegarde en flash --")
    settle(slot)
    mod = list(saved0)
    mod[IDX_MASTER] = min(127, saved0[IDX_MASTER] + 1)
    cc(link, CC_MASTER, mod[IDX_MASTER])
    time.sleep(0.3)
    drain(link)
    sysex(link, HEADER + [0x75, DIR_SET, 48, slot])
    t0 = time.perf_counter()
    got = drain(link, 0.5)
    say(report, f"réponses de l'ampli à la commande de sauvegarde : {[m.hex() if hasattr(m, 'hex') else str(m) for m in got]}")
    time.sleep(1.0)
    settle(other); settle(slot)
    after = read_preset(link, slot)[0]
    say(report, "0x0B après sauvegarde + aller-retour : " +
        ("conforme à la modification => LA SAUVEGARDE FONCTIONNE" if after == mod else
         "inchangé => la sauvegarde n'a pas fonctionné" if after == saved0 else f"autre chose : {diff(saved0, after or [])[:8]}"))

    # restauration
    cc(link, CC_MASTER, saved0[IDX_MASTER])
    time.sleep(0.3)
    sysex(link, HEADER + [0x75, DIR_SET, 48, slot])
    time.sleep(1.0)
    settle(other); settle(slot)
    z = read_preset(link, slot)[0]
    say(report, "\nÉtat final : " + ("preset d'origine restauré" if z == saved0 else f"ATTENTION différent : {diff(saved0, z or [])[:8]}"))
    save_outputs(link, report, {"savetest.json": {"load_ms": times}})


def cmd_cabmap(link, args):
    """Quel octet du preset bouge quand on envoie chaque CC de réglage ? (édition du tampon seulement : rien n'est
    enregistré, et on revient sur l'état d'origine en changeant de preset.)"""
    report = []
    slot = args.slot - 1
    other = (slot + 1) % 7
    program_change(link, slot)
    time.sleep(1.0)
    drain(link)
    _, base = read_current(link)
    if base is None:
        return say(report, "Lecture impossible, arrêt.") or save_outputs(link, report)
    say(report, f"== Correspondance CC -> octet du preset (emplacement {slot + 1}) ==")
    for h, (tag, head_i, first, count, cc_base) in FX.items():
        if args.only and tag not in args.only.split(","):
            continue
        for j in range(count):
            old = base[first + j]
            test = 77 if old != 77 else 33
            cc(link, cc_base + j, test)
            time.sleep(0.03)
            drain(link, 0.02)
            _, after = read_current(link)
            changed = [(i, base[i], after[i]) for i in range(len(base)) if after[i] != base[i]] if after else None
            say(report, f"{tag} CC {cc_base + j:3} (valeur {test}) -> octets modifiés : "
                        f"{[(i, index_name(i), a, b) for i, a, b in changed] if changed is not None else 'lecture impossible'}")
            cc(link, cc_base + j, old)
            time.sleep(0.02)
    program_change(link, other)
    time.sleep(1.0)
    program_change(link, slot)
    time.sleep(1.0)
    drain(link)
    z = read_current(link)[1]
    say(report, "\nÉtat final : " + ("identique au départ" if z == base else "ATTENTION, différent du départ"))
    save_outputs(link, report)


def cmd_snap(link, args):
    """Instantané du preset COURANT + des 7 emplacements, pour comparer avant/après une manip dans MightyEditor."""
    report = []
    cur = read_current(link)
    slots = {}
    for i in range(7):
        p, _, _ = read_preset(link, i)
        slots[str(i)] = list(p) if p else None
    data = {"current_slot": cur[0], "current": list(cur[1]) if cur[1] else None, "slots": slots}
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / f"snap_{args.name}.json").write_text(json.dumps(data), encoding="utf-8")
    say(report, f"Instantané « {args.name} » : preset courant = emplacement {cur[0] + 1 if cur[0] is not None else '?'}")
    save_outputs(link, report)


def cmd_snapdiff(link, args):
    report = []
    a = json.loads((OUT_DIR / f"snap_{args.a}.json").read_text(encoding="utf-8"))
    b = json.loads((OUT_DIR / f"snap_{args.b}.json").read_text(encoding="utf-8"))
    for label, x, y in [("preset courant", a["current"], b["current"])] + [
            (f"emplacement {i + 1} (mémoire)", a["slots"][str(i)], b["slots"][str(i)]) for i in range(7)]:
        if x is None or y is None:
            continue
        d = diff(x, y)
        say(report, f"{label} : " + ("identique" if not d else str([(i, index_name(i), u, v) for i, u, v in d])))
    save_outputs(None, report)


def find_ports():
    import mido
    inn = next((n for n in mido.get_input_names() if PORT_KEYWORD.lower() in n.lower()), None)
    out = next((n for n in mido.get_output_names() if PORT_KEYWORD.lower() in n.lower()), None)
    return inn, out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ports")
    sub.add_parser("read")
    c = sub.add_parser("compare")
    c.add_argument("files", nargs="+")
    t = sub.add_parser("timing")
    t.add_argument("--slot", type=int, default=1, help="emplacement testé, 1 à 7")
    t.add_argument("--delays", default="0,5,20", help="pauses (ms) entre messages à essayer")
    v = sub.add_parser("savetest")
    v.add_argument("--slot", type=int, default=2, help="emplacement testé, 1 à 7 (sera réécrit puis restauré)")
    m = sub.add_parser("cabmap")
    m.add_argument("--slot", type=int, default=2)
    m.add_argument("--only", default="", help="blocs à tester, ex. CAB ou CAB,AMP (tous par défaut)")
    sn = sub.add_parser("snap")
    sn.add_argument("name")
    sd = sub.add_parser("snapdiff")
    sd.add_argument("a")
    sd.add_argument("b")
    args = ap.parse_args(argv)
    if args.cmd == "ports":
        return cmd_ports(args)
    if args.cmd == "compare":                      # pas besoin de l'ampli
        return cmd_compare(None, args)
    if args.cmd == "snapdiff":
        return cmd_snapdiff(None, args)
    inn, out = find_ports()
    if not inn or not out:
        sys.exit("Mighty introuvable (port « %s »). Branché ? Melos et MightyEditor fermés ? (commande : ports)" % PORT_KEYWORD)
    link = MidoLink(inn, out)
    try:
        {"read": cmd_read, "timing": cmd_timing, "savetest": cmd_savetest, "cabmap": cmd_cabmap, "snap": cmd_snap}[args.cmd](link, args)
    finally:
        link.close()


if __name__ == "__main__":
    main()