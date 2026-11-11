import types
"""Teste tools/probe_presets.py contre un faux Mighty Plug Pro (aucun matériel, aucun port MIDI)."""

import importlib.util
import os
import struct
import sys
import tempfile
from pathlib import Path

import mido

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("probe", ROOT / "tools" / "probe_presets.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

DEFAULT_ORDER = [0, 5, 1, 6, 2, 3, 9, 4, 8, 7, 10]


def make_preset(seed: int) -> list[int]:
    p = [0] * 128
    for h, (_, _, base, count, _) in probe.FX.items():
        p[h] = (seed + h) % 20 + 1 + (0x40 if (seed + h) % 3 == 0 else 0)
        for j in range(count):
            p[base + j] = (seed * 7 + h * 3 + j * 11) % 101
    p[probe.IDX_MASTER] = 50 + seed
    p[probe.IDX_LINK1:probe.IDX_LINK1 + 11] = DEFAULT_ORDER if seed % 2 == 0 else [0, 5, 1, 2, 9, 3, 4, 6, 7, 8, 10]
    p[100:104] = b"NULL"
    return p


class FakeMighty:
    """Simule l'ampli : mémoire sauvegardée (flash) et preset en cours d'édition ; lecture = mémoire sauvegardée."""

    def __init__(self, reads_edit_buffer=False):
        self.flash = [make_preset(i) for i in range(7)]
        self.edit = [list(p) for p in self.flash]
        self.cur = 0
        self.reads_edit_buffer = reads_edit_buffer
        self.out: list = []

    def handle(self, m):
        if m.type == "program_change":
            self.cur = m.program
            self.edit[self.cur] = list(self.flash[self.cur])
        elif m.type == "control_change":
            e = self.edit[self.cur]
            if m.control in probe.FX:
                e[m.control] = m.value
            elif m.control == probe.CC_MASTER:
                e[probe.IDX_MASTER] = m.value
            else:
                for h, (_, _, base, count, cc_base) in probe.FX.items():
                    if cc_base <= m.control < cc_base + count:
                        e[base + m.control - cc_base] = m.value
        elif m.type == "sysex":
            d = list(m.data)
            if d[:3] != probe.HEADER:
                return
            kind, direction = d[3], d[4]
            if kind == probe.SYX_PRESET and direction == probe.DIR_REQ:       # un seul message, comme en USB
                idx = d[5]
                p = (self.edit if self.reads_edit_buffer else self.flash)[idx]
                self.out.append(mido.Message("sysex", data=probe.HEADER + [kind, 2, idx] + p[:128]))
            elif kind == probe.SYX_CURPRESET and direction == probe.DIR_REQ:   # preset en cours d'édition
                self.out.append(mido.Message("sysex", data=probe.HEADER + [kind, 2, self.cur] + self.edit[self.cur][:128]))
            elif kind == 0x75 and direction == probe.DIR_SET and d[5] == 48:   # sauvegarde en flash
                self.flash[d[6]] = list(self.edit[d[6]])
            elif kind == probe.SYX_MODULELINK and direction == probe.DIR_SET:
                order = d[6:6 + d[5]]
                self.edit[self.cur][probe.IDX_LINK1:probe.IDX_LINK1 + 11] = [0] + order + [10]


class FakeLink:
    mido = mido

    def __init__(self, amp):
        self.amp, self.frames = amp, []

    def send(self, msg):
        self.frames.append("-> " + msg.hex(" "))
        self.amp.handle(msg)

    def recv(self, timeout):
        if self.amp.out:
            m = self.amp.out.pop(0)
            self.frames.append("<- " + m.hex(" "))
            return m
        return None

    def close(self):
        pass


def make_patch(slot, preset) -> bytes:
    return struct.pack("<I", slot) + bytes(preset[:128]) + bytes(80) + struct.pack("<2048f", *([0.1] * 2048))


def run():
    os.chdir(tempfile.mkdtemp())
    probe.time.sleep = lambda s: None                       # pas d'attente réelle
    amp = FakeMighty()
    link = FakeLink(amp)
    probe.cmd_read(link, None)
    raw = probe.load_raw()
    assert len(raw) == 7 and raw[3] == amp.flash[3] and len(raw[3]) == 128, "lecture des 7 presets"

    p1 = Path("p1.mppropatch")
    p1.write_bytes(make_patch(2, amp.flash[2]))
    modified = list(amp.flash[4])
    modified[probe.FX[3][2]] ^= 5
    p2 = Path("p2.mppropatch")
    p2.write_bytes(make_patch(4, modified))

    class A:
        files = [str(p1), str(p2)]
    probe.cmd_compare(None, A)
    report = (probe.OUT_DIR / "report.txt").read_text(encoding="utf-8")
    assert "IDENTIQUES sur la partie comparée" in report and "AMP param 0" in report, report

    class B:
        slot, delays = 2, "0,5"
    for edit_read in (False, True):
        amp2 = FakeMighty(reads_edit_buffer=edit_read)
        probe.cmd_timing(FakeLink(amp2), B)
        r = (probe.OUT_DIR / "report.txt").read_text(encoding="utf-8")
        assert "preset d'origine retrouvé" in r and "conforme à la copie de travail" in r, r
        assert "Lecture 0x0B (mémoire de l'emplacement) : " + ("modifiée" if edit_read else "INCHANGÉE") in r, r
        assert "identique au départ (modification perdue)" in r, r
        assert amp2.flash == [make_preset(i) for i in range(7)], "rien ne doit être sauvegardé"
    # décodage lisible
    probe.cmd_savetest(FakeLink(FakeMighty(True)), types.SimpleNamespace(slot=2))
    r = (probe.OUT_DIR / "report.txt").read_text(encoding="utf-8")
    assert "LA SAUVEGARDE FONCTIONNE" in r and "restauré" in r, r
    amp3 = FakeMighty(True)
    probe.cmd_cabmap(FakeLink(amp3), types.SimpleNamespace(slot=2, only="CAB"))
    r = (probe.OUT_DIR / "report.txt").read_text(encoding="utf-8")
    assert "CAB CC  65" in r and "CAB param 0" in r and "identique au départ" in r, r
    probe.cmd_snap(FakeLink(amp3), types.SimpleNamespace(name="a"))
    amp3.edit[amp3.cur][probe.FX[9][2] + 3] ^= 5
    probe.cmd_snap(FakeLink(amp3), types.SimpleNamespace(name="b"))
    probe.cmd_snapdiff(None, types.SimpleNamespace(a="a", b="b"))
    assert "CAB param 3" in (probe.OUT_DIR / "report.txt").read_text(encoding="utf-8")
    assert any("ON" in l or "off" in l for l in probe.describe(amp.flash[0]))
    print("test_probe_presets OK")


if __name__ == "__main__":
    run()