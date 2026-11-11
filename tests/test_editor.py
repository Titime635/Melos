"""Tests de l'éditeur de presets (sans ampli : un faux Mighty reproduit ce qui a été mesuré sur le vrai)."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from editor import wire
from editor.amp_io import AmpError, AmpIO
from editor.bank import EditorBank
from editor.catalog import CC_MASTER, IDX_MASTER, get_catalog
from editor.library import BackupStore, PresetLibrary
from editor.preset import FX_IDS, Preset

# Deux presets relevés sur l'ampli de l'utilisateur (emplacements 1 et 3)
REAL_1 = ("4143421c410102040101410232000246191e1e022328234600000709642c323b013232072b362c3b3b3232323232323202151400"
          "000420141406000004052314060000000003143c0a00060000323200330232322500004d00000501020709030406080a4e554c4c"
          "00000000000000000000000001000001024d000000000007")
REAL_3 = ("4142050a43014b4101084102320002195041000219374b4600000743502c4b413c323207383232323232383d3832273202"
          "1e14000004460f50060000041e3214190000000003323c1432063200643200640232322601006a00000501060203090408070a"
          "4e554c4c00000000000000000000000001000001024d000000000007")


def real_presets():
    return [Preset.from_hex(REAL_1), Preset.from_hex(REAL_3)]


# --- Faux ampli ---------------------------------------------------------------------------------------------------
class FakeAmp:
    """Mémoire flash + tampon d'édition ; changer de preset recharge le tampon depuis la flash (comme le vrai)."""

    def __init__(self):
        base = Preset.default()
        self.flash = []
        for i in range(7):
            p = base.copy()
            p.set_model(3, i + 1)
            p.master = 30 + i
            self.flash.append(p)
        self.edit = self.flash[0].copy()
        self.cur = 0
        self.out: list = []                       # SysEx à rendre à l'hôte
        self.log: list = []
        self.silent = False

    def cc(self, control, value):
        self.log.append(("cc", control, value))
        cat = get_catalog()
        if control in FX_IDS:
            self.edit.data[control] = value
        elif control == CC_MASTER:
            self.edit.data[IDX_MASTER] = value
        else:
            for e in cat:
                if e.cc_base <= control < e.cc_base + e.param_slots:
                    self.edit.data[e.param_index + control - e.cc_base] = value

    def pc(self, n):
        self.log.append(("pc", n))
        self.cur = n
        self.edit = self.flash[n].copy()

    def sysex(self, d):
        self.log.append(("syx", tuple(d)))
        if self.silent:
            return
        H = wire.HEADER
        kind, direction = d[3], d[4]
        if kind == wire.SYX_PRESET and direction == wire.DIR_REQ:
            self.out.append(H + [kind, 2, d[5]] + list(self.flash[d[5]].data))
        elif kind == wire.SYX_CURPRESET and direction == wire.DIR_REQ:
            self.out.append(H + [kind, 2, self.cur] + list(self.edit.data))
        elif kind == wire.SYX_MODULELINK and direction == wire.DIR_SET:
            n = d[5]
            self.edit.set_order(d[6:6 + n])
            self.out.append(H + [kind, 2, n] + d[6:6 + n])
        elif kind == wire.SYX_SPEC_CMD and direction == wire.DIR_SET and d[5] == wire.SYSCMD_SAVE:
            self.flash[d[6]] = self.edit.copy()
            self.out.append(H + [kind, wire.DIR_ACK, 48, d[6], 0, 0, 0, 0, 0, 0])


class FakeTransport:
    def __init__(self, amp):
        self.amp = amp
        self.connected = True

    def send_cc(self, c, v):
        self.amp.cc(c, v)
        return True

    def send_sysex(self, d):
        self.amp.sysex(list(d))
        return True

    def send_pc(self, n):
        self.amp.pc(n)
        return True

    def clear_inbox(self):
        self.amp.out.clear()

    def wait_sysex(self, parse, timeout):
        for i, d in enumerate(list(self.amp.out)):
            r = parse(d)
            if r is not None:
                del self.amp.out[i]
                return r
        return None


def make_bank(tmp):
    amp = FakeAmp()
    io = AmpIO(FakeTransport(amp), cc_pause=0, sleep=lambda s: None)
    bank = EditorBank(io, BackupStore(Path(tmp) / "backups"))
    return amp, io, bank


# --- Catalogue / preset -------------------------------------------------------------------------------------------
def test_catalog():
    c = get_catalog()
    assert [len(e.models) for e in c] == [3, 14, 29, 2, 1, 14, 6, 6, 34]
    assert (c.cab_by_name["JZ120"], c.cab_by_name["A212"], c.cab_by_name["M-D45"]) == (1, 18, 34)   # vus dans les .mppropatch
    assert [p.offset for p in c.effects[9].models[1].params] == [3, 4, 5]     # baffle : niveau/coupe-bas/coupe-haut en 78-80
    assert c.effects[3].models[1].link["cab"] == "JZ120"


def test_preset_roundtrip_and_decode():
    for hx in (REAL_1, REAL_3):
        p = Preset.from_hex(hx)
        assert p.to_hex() == hx
    p = Preset.from_hex(REAL_1)
    assert p.model(3) == 28 and not p.enabled(1) and p.enabled(3) and p.model(9) == 1
    assert p.order == [5, 1, 2, 7, 9, 3, 4, 6, 8] and p.bpm == 77 and p.master == 37
    assert "JZ120" in "\n".join(p.describe())
    assert Preset(bytes.fromhex(REAL_1)[:116]).to_bytes()[116:] == bytes.fromhex(REAL_1)[116:]      # ancien format complété


def test_default_preset_matches_real_constants():
    d, r = Preset.default().data, Preset.from_hex(REAL_1).data
    for i in (0, 10, 11, 12, 13, 14, 19, 26, 35, 48, 53, 60, 69, 74, 81, 82, 83, 88, *range(116, 128)):
        assert d[i] == r[i], i


def test_set_model_param_clamp_order():
    p = Preset.default()
    p.set_model(3, 5)                                          # ampli : repart des défauts et entraîne son baffle
    cat = get_catalog()
    assert p.model(3) == 5 and p.model(9) == cat.cab_by_name[cat.effects[3].models[5].link["cab"]]
    assert p.param(3, 0) == cat.effects[3].models[5].params[0].default
    assert p.set_param(3, 0, 250) == 100 and p.set_param(3, 0, -4) == 0
    p.set_enabled(1, True)
    assert p.enabled(1) and p.model(1) == 1
    try:
        p.set_model(3, 99)
        assert False
    except ValueError:
        pass
    p.move_block(9, 0)
    assert p.order[0] == 9 and sorted(p.order) == list(FX_IDS)
    try:
        p.set_order([1, 2, 3])
        assert False
    except ValueError:
        pass
    raw = Preset.default().data
    raw[3] = 200
    try:
        Preset(raw)
        assert False
    except ValueError:
        pass
    amp = Preset.default()
    amp.set_model(3, 4)
    assert (amp.model(3) & 0x3F) == 4


# --- Messages --------------------------------------------------------------------------------------------------------
def apply(amp, msgs):
    for k, a, *r in msgs:
        amp.cc(a, r[0]) if k == "cc" else amp.sysex(a)


def test_full_and_diff_messages_rebuild_the_preset():
    for target in real_presets():
        amp = FakeAmp()
        apply(amp, wire.full_messages(target))
        assert amp.edit.wire_bytes() == target.wire_bytes()
        assert len(wire.full_messages(target)) == 69                    # 9 blocs + volume + ordre, comme mesuré
    a, b = real_presets()
    amp = FakeAmp()
    amp.edit = a.copy()
    apply(amp, wire.diff_messages(a, b))
    assert amp.edit.wire_bytes() == b.wire_bytes()
    c = a.copy()
    c.set_param(3, 1, 77)
    m = wire.diff_messages(a, c)
    assert m == [("cc", get_catalog().effects[3].cc_for(1), 77)]          # un seul CC pour un seul bouton
    assert wire.diff_messages(a, a.copy()) == []


def test_parse_replies():
    p = real_presets()[0]
    assert wire.parse_preset_reply(wire.HEADER + [0x0B, 2, 4] + list(p.data)) == (4, list(p.data))
    assert wire.parse_current_reply(wire.HEADER + [0x0C, 2, 6] + list(p.data)) == (6, list(p.data))
    assert wire.parse_order_reply(wire.HEADER + [0x0D, 2, 9, 5, 1, 2, 7, 9, 3, 4, 6, 8]) == [5, 1, 2, 7, 9, 3, 4, 6, 8]
    assert wire.is_save_ack(wire.HEADER + [0x75, 3, 0x30, 1, 0, 0, 0, 0, 0, 0], 1)
    assert not wire.is_save_ack(wire.HEADER + [0x75, 3, 0x30, 1], 2)
    assert wire.save_slot(1) == ("syx", [0x43, 0x58, 0x70, 0x75, 1, 0x30, 1])       # = octets vus sur le vrai ampli


# --- Bibliothèque ----------------------------------------------------------------------------------------------------
def test_library(tmp_path=None):
    with tempfile.TemporaryDirectory() as tmp:
        lib = PresetLibrary(Path(tmp) / "lib")
        a, b = real_presets()
        e1 = lib.add(a, "Nirvana clean", ["grunge", "clean"], "notes")
        e2 = lib.add(b, "AC/DC", ["rock", " Grunge "])
        assert [t.lower() for t in lib.all_tags()] == ["clean", "grunge", "rock"]
        assert {e.id for e in lib.search(tags=["grunge"])} == {e1.id, e2.id}
        assert [e.id for e in lib.search("nirv", ["clean"])] == [e1.id]
        lib.update(e1.id, name="Nirvana", tags=["grunge"])
        (Path(tmp) / "lib" / "casse.json").write_text("{pas du json", encoding="utf-8")
        lib2 = PresetLibrary(Path(tmp) / "lib")                              # relecture depuis le disque
        assert lib2.get(e1.id).name == "Nirvana" and lib2.get(e1.id).preset == a and len(lib2.entries()) == 2
        lib2.rename_tag("grunge", "Grunge")
        assert lib2.get(e2.id).tags == ["rock", "Grunge"]
        d = lib2.duplicate(e1.id)
        assert d.name.endswith("(copie)") and d.preset == a
        lib2.delete(d.id)
        assert lib2.get(d.id) is None and not list((Path(tmp) / "lib").glob("*.tmp"))


def test_backups():
    with tempfile.TemporaryDirectory() as tmp:
        st = BackupStore(Path(tmp), keep=3)
        p = Preset.default()
        for i in range(5):
            p = p.copy()
            p.master = i
            st.save(2, p, "test")
        lst = st.list(2)
        assert len(lst) == 3 and lst[0][4].master == 4 and lst[0][1] == 2


# --- Liaison + 7 emplacements ----------------------------------------------------------------------------------------
def test_io_read_select_save():
    with tempfile.TemporaryDirectory() as tmp:
        amp, io, bank = make_bank(tmp)
        assert io.read_slot(3) == amp.flash[3]
        io.select(2)
        assert io.read_current()[0] == 2
        p = amp.flash[2].copy()
        p.master = 77
        io.push(p, amp.flash[2])
        assert io.verify_current(p) and amp.flash[2].master == 32          # édité mais pas enregistré
        io.save(2)
        assert amp.flash[2].master == 77
        amp.silent = True
        try:
            io.read_slot(1, timeout=0)
            assert False
        except AmpError:
            pass


def make_env(tmp):
    """Faux ampli + banque + bibliothèque + établi."""
    from editor.links import SlotLinks
    from editor.workbench import Workbench
    amp, io, bank = make_bank(tmp)
    lib = PresetLibrary(Path(tmp) / "lib")
    links = SlotLinks(Path(tmp) / "links.json")
    return amp, bank, lib, links, Workbench(bank, lib, links)


def test_bank_mirror_play_write():
    with tempfile.TemporaryDirectory() as tmp:
        amp, io, bank = make_bank(tmp)
        bank.refresh_from_amp()
        assert bank.current == 0 and all(s.saved is not None for s in bank.slots)
        assert len(bank.backups.list()) == 7
        bank.refresh_from_amp()
        assert len(bank.backups.list()) == 7                               # pas de doublons
        bank.activate(3)
        assert amp.cur == 3 and bank.current == 3 and amp.edit == amp.flash[3]
        # annonce périmée (changement fait par nous) : ignorée ; vrai changement (bouton de l'ampli) : pris en compte
        assert bank.on_amp_preset_changed(0) is False
        amp.pc(5)
        assert bank.on_amp_preset_changed(5) is True and bank.current == 5
        # écrire dans l'emplacement 1 depuis l'emplacement 5 : sauvegarde, écriture, retour sur 5
        p = amp.flash[1].copy()
        p.master = 99
        old = amp.flash[1].copy()
        saved = bank.write_slot(1, p)
        assert amp.flash[1].master == 99 and saved == amp.flash[1] and amp.cur == 5 and bank.current == 5
        assert any(x[4] == old for x in bank.backups.list(1))
        # sans « restore » : l'ampli reste sur l'emplacement écrit
        q = p.copy()
        q.master = 12
        bank.write_slot(2, q, restore=False)
        assert amp.cur == 2 and amp.flash[2].master == 12


def test_workbench_edit_audition_send():
    with tempfile.TemporaryDirectory() as tmp:
        amp, bank, lib, links, wb = make_env(tmp)
        bank.refresh_from_amp()
        a, b = real_presets()
        e = lib.add(a, "Nirvana", ["grunge"])
        assert not e.is_modified
        # éditer sans toucher à l'ampli : copie de travail enregistrée sur disque, original conservé
        log = len(amp.log)
        wb.edit(e.id, lambda p: p.set_param(3, 0, 88), "gain", ("p", 3, 0))
        assert len(amp.log) == log and lib.get(e.id).preset.param(3, 0) == 88 and lib.get(e.id).is_modified
        lib2 = PresetLibrary(Path(tmp) / "lib")
        assert lib2.get(e.id).preset.param(3, 0) == 88 and lib2.get(e.id).original == a and lib2.get(e.id).is_modified
        # écouter : envoi dans le tampon, rien en flash ; les modifications suivantes partent en direct
        wb.select(e.id)
        wb.set_audition(True)
        assert wb.audition and amp.edit.wire_bytes() == lib.get(e.id).preset.wire_bytes()
        flash0 = amp.flash[0].copy()
        wb.edit(e.id, lambda p: p.set_param(3, 1, 12), "master amp", ("p", 3, 1))
        assert amp.edit.param(3, 1) == 12 and amp.flash[0] == flash0
        # changer de preset sur l'ampli arrête l'écoute
        amp.pc(4)
        wb.on_amp_preset_changed(4)
        assert not wb.audition and bank.current == 4
        # annuler / rétablir : un curseur tiré = une étape ; ne touche pas à l'ampli hors écoute
        assert [h.label for h in wb.history] == ["gain", "master amp"]
        n = len(amp.log)
        h = wb.undo()
        assert h.label == "master amp" and lib.get(e.id).preset.param(3, 1) == a.param(3, 1) and len(amp.log) == n
        wb.undo()
        assert not lib.get(e.id).is_modified and wb.undo() is None
        wb.redo()
        assert lib.get(e.id).preset.param(3, 0) == 88
        wb.edit(e.id, lambda p: p.set_param(3, 2, 9), "autre")
        assert not wb.redo_stack
        # revenir à l'original
        wb.revert_original(e.id)
        assert not lib.get(e.id).is_modified and wb.undo().label == "retour à l'original"
        wb.undo()

        # --- états des emplacements ---
        assert wb.slot_state(0)[0] == "unknown"
        wb.edit(e.id, lambda p: p.set_param(3, 0, 70), "gain")
        saved = wb.send(e.id, 2)                                         # envoi vers l'emplacement 3
        assert amp.flash[2].wire_bytes() == lib.get(e.id).preset.wire_bytes() and bank.current == 4
        assert wb.slot_state(2) == ("synced", e.id) and wb.entry_slots(e.id) == [(2, "synced")]
        wb.edit(e.id, lambda p: p.set_param(3, 0, 71), "gain")
        assert wb.slot_state(2) == ("ahead", e.id)                       # bibliothèque plus récente que l'ampli
        # l'association survit à un redémarrage (nouvelle banque / nouvel établi sur les mêmes fichiers)
        from editor.links import SlotLinks
        from editor.workbench import Workbench
        wb2 = Workbench(bank, PresetLibrary(Path(tmp) / "lib"), SlotLinks(Path(tmp) / "links.json"))
        assert wb2.slot_state(2) == ("ahead", e.id)
        # l'ampli est modifié hors de Melos (autre logiciel) : « changé »
        amp.flash[2].set_param(3, 5, 3)
        bank.slots[2].saved = amp.flash[2].copy()
        assert wb.slot_state(2) == ("changed", e.id)
        # contenu identique à un preset connu, sans association enregistrée : reconnu
        links.clear(4)
        e2 = lib.add(amp.flash[4], "Cinq", [])
        assert wb.slot_state(4) == ("synced", e2.id) and wb.slot_state(5)[0] == "unknown"
        # importer un emplacement inconnu
        new_id = wb.import_slot(5, "Importé")
        assert lib.get(new_id).preset == amp.flash[5] and wb.slot_state(5) == ("synced", new_id)
        # copier un emplacement vers un autre : l'association suit
        wb.copy_slot(5, 6)
        assert amp.flash[6].wire_bytes() == amp.flash[5].wire_bytes() and wb.slot_state(6) == ("synced", new_id)
        # preset supprimé de la bibliothèque : l'emplacement redevient « hors bibliothèque »
        lib.delete(new_id)
        assert wb.slot_state(5)[0] == "unknown"
        # écoute impossible sans ampli
        wb.on_disconnected()
        try:
            wb.set_audition(True)
            assert False
        except AmpError:
            pass


def test_reset_params():
    from editor.catalog import get_catalog
    p = Preset.default()
    p.set_param(3, 0, 91)
    p.set_param(3, 2, 7)
    p.set_enabled(3, True)
    model = p.model(3)
    p.reset_params(3)
    dflt = [q.default for q in get_catalog().effects[3].model(model).params]
    assert p.params(3)[:len(dflt)] == dflt and p.model(3) == model and p.enabled(3)


def test_versions_diff_backups_transport():
    from editor.amp_io import MidiTransport
    from editor.diff import diff_presets
    # MidiSender.set_preset() ne rend rien : l'envoi d'un Program Change n'est pas un échec
    class S:
        is_open = True
        def set_preset(self, i): self.last = i
        def send_cc(self, c, v): return True
        def send_sysex(self, d): return True
    class L:
        def add_raw_handler(self, h): pass
    t = MidiTransport(S(), L())
    assert t.send_pc(3) is True
    t._sender.is_open = False
    assert t.send_pc(3) is False

    with tempfile.TemporaryDirectory() as tmp:
        amp, bank, lib, links, wb = make_env(tmp)
        bank.refresh_from_amp()
        a, _ = real_presets()
        e = lib.add(a, "Base", [])
        assert e.versions == [] and wb.snapshot(e.id, "rien") is None        # identique à l'original : pas de doublon
        wb.edit(e.id, lambda p: p.set_param(3, 0, 60), "gain")
        v1 = wb.snapshot(e.id, "Son gras")
        assert v1 and v1.kind == "manual" and wb.snapshot(e.id, "encore") is None
        wb.edit(e.id, lambda p: (p.set_param(3, 0, 20), p.set_enabled(7, True), p.master.__class__ and None), "x")
        # envoi : instantané automatique
        wb.send(e.id, 2)
        kinds = [v.kind for v in lib.get(e.id).versions]
        assert kinds == ["manual", "auto"] and "emplacement 3" in lib.get(e.id).versions[-1].label
        # restaurer une version : l'état actuel est gardé (déjà dans l'instantané d'envoi), annulable
        n = len(lib.get(e.id).versions)
        wb.restore_version(e.id, v1.id)
        assert lib.get(e.id).preset.param(3, 0) == 60 and len(lib.get(e.id).versions) == n
        wb.edit(e.id, lambda p: p.set_param(3, 3, 11), "autre")              # état jamais sauvegardé ailleurs
        wb.restore_version(e.id, v1.id)
        assert any(v.label.startswith("Avant retour") for v in lib.get(e.id).versions)
        assert wb.undo().label.startswith("retour à la version")
        assert lib.get(e.id).preset.param(3, 3) == 11
        # persistance des versions
        lib2 = PresetLibrary(Path(tmp) / "lib")
        assert [v.label for v in lib2.get(e.id).versions] == [v.label for v in lib.get(e.id).versions]
        lib.delete_version(e.id, v1.id)
        assert lib.get_version(e.id, v1.id) is None
        # différences lisibles
        b = a.copy()
        b.set_param(3, 0, (a.param(3, 0) + 10) % 90)
        b.set_enabled(7, not a.enabled(7))
        b.master = (a.master + 5) % 100
        b.move_block(8, 0)
        ch = diff_presets(a, b)
        kinds = {c.kind for c in ch}
        assert {"param", "enabled", "master", "order"} <= kinds and diff_presets(a, a) == []
        c = next(x for x in ch if x.kind == "param")
        assert c.fid == 3 and c.old == str(a.param(3, 0)) and c.new == str(b.param(3, 0))
        # restaurer une sauvegarde de l'ampli dans un emplacement
        old = amp.flash[4].copy()
        wb.write_preset(4, a)
        assert amp.flash[4].wire_bytes() == a.wire_bytes() and any(x[4] == old for x in bank.backups.list(4))


def test_kit_loading():
    with tempfile.TemporaryDirectory() as tmp:
        amp, io, bank = make_bank(tmp)
        bank.refresh_from_amp()
        a, b = real_presets()
        kit = {1: a, 2: b, 6: amp.flash[6].copy()}
        assert bank.matches(6, kit[6]) and not bank.matches(1, a)
        steps = []
        written = bank.load_kit(kit, progress=lambda n, t, s: steps.append((n, t, s)))
        assert written == [1, 2] and steps[-1] == (2, 2, None)
        assert amp.flash[1].wire_bytes() == a.wire_bytes() and amp.flash[2].wire_bytes() == b.wire_bytes()
        assert bank.current == 0 and bank.matches(1, a) and bank.matches(2, b)
        assert bank.load_kit(kit) == []                                         # déjà chargé : rien à écrire


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("test_editor OK (%d tests)" % len(tests))


if __name__ == "__main__":
    main()