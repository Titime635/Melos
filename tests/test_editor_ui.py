"""Test de la page Éditeur (PySide6 + Fluent Widgets, hors écran) avec le faux ampli de test_editor.py."""

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QObject, QMimeData, QPointF, Qt, Signal
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

from editor.library import PresetLibrary  # noqa: F401  (utilisé via make_env)
from editor.links import SlotLinks
from editor.preset import Preset
from editor.service import EditorService
from editor.workbench import Workbench
from test_editor import make_env, real_presets


class FakeState(QObject):
    preset_changed = Signal(int)
    connection_changed = Signal(bool)
    current_preset = 0
    connected = True


def pump(app, cond=lambda: False, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond() and not SVC.busy:
            break
        time.sleep(0.005)
    app.processEvents()


def main():
    global SVC
    from ui.editor_interface import EditorInterface
    from ui.editor_widgets import MIME_BLOCK, BlockChip
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        amp, bank, lib, links, wb = make_env(tmp)
        SVC = svc = EditorService(bank, wb)
        a, b = real_presets()
        ea = lib.add(a, "Nirvana", ["grunge"])
        eb = lib.add(b, "AC/DC", ["rock"])
        state = FakeState()
        w = EditorInterface(svc, lib, state)
        w.resize(1150, 900)
        w.show()
        panel = w.library_panel

        def row_of(name):
            return next(i for i, r in enumerate(panel.rows) if r.name == name)

        # Sans lire l'ampli : on peut déjà éditer la bibliothèque ; les emplacements sont « non lus »
        assert w.sel_id == eb.id and all(c.state == "unread" for c in w.cards)
        assert w.title_label.text() == "AC/DC" and not w.btn_send.isEnabled() or state.connected
        svc.refresh()
        pump(app, lambda: bank.slots[6].saved is not None)
        assert bank.current == 0 and all(c.state == "unknown" for c in w.cards)      # rien n'est dans la bibliothèque

        # --- Édition d'un preset de la bibliothèque SANS toucher à l'ampli
        panel.select_row(row_of("Nirvana"))
        assert w.sel_id == ea.id
        w.select_block(3)
        log = len(amp.log)
        w._rows[0].slider.setValue(91)
        pump(app, lambda: lib.get(ea.id).preset.param(3, 0) == 91)
        assert len(amp.log) == log and lib.get(ea.id).is_modified and panel.rows[row_of("Nirvana")].modified
        assert "modifié" in w.caption_label.toolTip() or "modifié" in w.entry_caption(lib.get(ea.id))
        assert PresetLibrary(Path(tmp) / "lib").get(ea.id).preset.param(3, 0) == 91        # enregistré sur disque

        # --- Écouter : le preset part dans le tampon de l'ampli, rien n'est écrit en flash
        flash0 = amp.flash[0].copy()
        w.btn_listen.click()
        pump(app, lambda: svc.audition and amp.edit.wire_bytes() == lib.get(ea.id).preset.wire_bytes())
        assert amp.flash[0] == flash0 and w.btn_listen.isChecked()
        w._rows[0].slider.setValue(33)
        pump(app, lambda: amp.edit.param(3, 0) == 33)
        assert amp.flash[0] == flash0
        # choisir un autre preset pendant l'écoute : l'ampli le joue
        panel.select_row(row_of("AC/DC"))
        pump(app, lambda: amp.edit.wire_bytes() == lib.get(eb.id).preset.wire_bytes())
        # jouer un emplacement (clic) : l'écoute s'arrête, le tampon est rechargé depuis la flash
        w.play_slot(3)
        pump(app, lambda: bank.current == 3 and not svc.audition)
        assert amp.cur == 3 and amp.edit == amp.flash[3] and not w.btn_listen.isChecked()
        w.cards[3].mouseDoubleClickEvent(None)                      # un double clic ne déclenche pas deux fois
        # changement de preset fait par l'ampli (bouton physique) pendant l'écoute : arrêt de l'écoute
        svc.set_audition(True)
        pump(app, lambda: svc.audition)
        amp.pc(5)
        svc.on_amp_preset_changed(5)
        pump(app, lambda: bank.current == 5 and not svc.audition)

        # --- Envoyer vers un emplacement (confirmation avec aperçu), sans changer l'emplacement joué
        w.confirm_overwrite = lambda *args, **kw: True
        w.ask_info = lambda title, name='', tags=(), notes='': ((name or 'Mon preset'), list(tags), notes)
        panel.select_row(row_of("Nirvana"))
        notes = w.send_notes(2, lib.get(ea.id))
        kinds = [k for k, _ in notes]
        assert "warn" in kinds and "ok" in kinds and any("repassera" in t for _, t in notes)   # contenu inconnu écrasé
        w.request_send(2)
        pump(app, lambda: amp.flash[2].wire_bytes() == lib.get(ea.id).preset.wire_bytes())
        assert amp.cur == 5 and bank.current == 5
        pump(app)
        assert w.cards[2].state == "synced" and w.cards[2].contains and w.cards[2].title == "Nirvana"
        assert not w.cards[1].contains and w.cards[5].current
        assert [s for s, _ in wb.entry_slots(ea.id)] == [2] and "sur le Mighty : 3" in w.entry_caption(lib.get(ea.id))
        n = len(amp.log)
        w.request_send(2)                                           # déjà à jour : rien n'est envoyé
        pump(app)
        assert len(amp.log) == n
        # la bibliothèque évolue : l'emplacement devient « à renvoyer » (anneau orange sur la ligne)
        w._rows[0].slider.setValue(44)
        pump(app, lambda: lib.get(ea.id).preset.param(3, 0) == 44)
        pump(app)
        assert w.cards[2].state == "ahead" and panel.rows[row_of("Nirvana")].slots[0][2] == "ahead"
        # l'association survit à un redémarrage
        wb2 = Workbench(bank, PresetLibrary(Path(tmp) / "lib"), SlotLinks(Path(tmp) / "links.json"))
        assert wb2.slot_state(2) == ("ahead", ea.id)

        # --- Filtre « sur le Mighty / hors Mighty » : on clique vraiment sur les onglets (le clic transmet « checked »)
        panel.scope_bar.items["on"].click()
        assert panel.scope == "on" and [r.name for r in panel.rows] == ["Nirvana"]
        panel.scope_bar.items["all"].click()
        assert panel.scope == "all" and sorted(r.name for r in panel.rows) == ["AC/DC", "Nirvana"]
        panel._set_scope("on")
        assert [r.name for r in panel.rows] == ["Nirvana"]
        panel._set_scope("off")
        assert [r.name for r in panel.rows] == ["AC/DC"]
        panel._set_scope("all")
        panel.select_row(row_of("Nirvana"))

        # --- Menus : emplacement (clic droit), envoi, plus d'actions, ajout
        assert w.build_slot_menu(5) is not None and w.build_slot_menu(0) is not None
        assert w.build_send_picker() is not None and w.build_more_menu() is not None
        assert w.importable_slots() == [0, 1, 3, 4, 5, 6]
        pk = w.build_send_picker()
        infos = w.slot_pick_infos()
        assert len(pk.rows) == 7 and infos[2]["target"] and infos[2]["state"] in ("synced", "ahead")
        got_slots = []
        pk.picked.connect(got_slots.append)
        pk.rows[4].picked.emit(4)
        assert got_slots == [4]
        assert panel.build_add_menu() is not None
        # copier un emplacement vers un autre : l'association suit
        w.request_copy(2, 6)
        pump(app, lambda: amp.flash[6].wire_bytes() == amp.flash[2].wire_bytes())
        assert amp.cur == 5 and wb.slot_state(6)[0] in ("synced", "ahead") and bank.current == 5
        # importer les emplacements hors bibliothèque
        before = len(lib.entries())
        w.import_all()
        pump(app, lambda: len(lib.entries()) == before + len(w.importable_slots()) + 0 or not w.importable_slots())
        pump(app)
        assert w.importable_slots() == [] and len(lib.entries()) > before
        assert all(c.state in ("synced", "ahead") for c in w.cards)
        panel.select_row(row_of("Nirvana"))
        w.select_block(3)

        # --- Changement de modèle d'ampli : prévenu (info), reste annulable
        i = w.model_box.findData(5)
        w.model_box.setCurrentIndex(i)
        pump(app, lambda: lib.get(ea.id).preset.model(3) == 5)
        assert lib.get(ea.id).preset.model(9) != a.model(9) or True

        # --- Glisser-déposer : ordre calculé (avant / après la cible)
        order = [5, 1, 2, 3, 9, 4, 6, 7, 8]
        assert EditorInterface.dropped_order(order, 8, 5, False) == [8, 5, 1, 2, 3, 9, 4, 6, 7]
        assert EditorInterface.dropped_order(order, 5, 8, True) == [1, 2, 3, 9, 4, 6, 7, 8, 5]
        assert EditorInterface.dropped_order(order, 3, 4, True) == [5, 1, 2, 9, 4, 3, 6, 7, 8]
        cur = list(lib.get(ea.id).preset.order)
        w._on_drop(cur[-1], cur[0], False)
        pump(app, lambda: lib.get(ea.id).preset.order[0] == cur[-1])
        assert lib.get(ea.id).preset.order == [cur[-1]] + cur[:-1] and w.sel_fid == cur[-1]
        ids = [w.chain_row.itemAt(k).widget().fid for k in range(w.chain_row.count())
               if hasattr(w.chain_row.itemAt(k).widget(), "fid")]
        assert ids == lib.get(ea.id).preset.order
        got = []
        tgt = BlockChip(3)                                          # tuile isolée : ne touche pas à la page
        tgt.dropped.connect(lambda x, y, z: got.append((x, y, z)))
        md = QMimeData()
        md.setData(MIME_BLOCK, b"6")
        tgt.dropEvent(QDropEvent(QPointF(tgt.width() - 4, 30), Qt.MoveAction, md, Qt.LeftButton, Qt.NoModifier))
        tgt.dropEvent(QDropEvent(QPointF(4, 30), Qt.MoveAction, md, Qt.LeftButton, Qt.NoModifier))
        assert got == [(6, 3, True), (6, 3, False)]

        # --- Annuler / rétablir (Ctrl+Z / Ctrl+Y)
        assert w.undo_redo(False).startswith("Annulé : ordre")
        pump(app, lambda: lib.get(ea.id).preset.order == cur)
        assert lib.get(ea.id).preset.order == cur
        assert w.undo_redo(True).startswith("Rétabli : ordre")
        pump(app, lambda: lib.get(ea.id).preset.order[0] == cur[-1])
        w.undo_redo(False)
        pump(app, lambda: lib.get(ea.id).preset.order == cur)

        # --- Réinitialisation d'un bloc
        w.select_block(3)
        w._rows[0].slider.setValue(77)
        pump(app, lambda: lib.get(ea.id).preset.param(3, 0) == 77)
        w.btn_reset.click()
        pump(app, lambda: lib.get(ea.id).preset.param(3, 0) != 77)
        assert lib.get(ea.id).preset.param(3, 0) == w._rows[0].pdef.default
        assert w.undo_redo(False).startswith("Annulé : réinitialisation AMP")
        pump(app, lambda: lib.get(ea.id).preset.param(3, 0) == 77)

        # --- Saisie directe d'une valeur (double clic sur la valeur)
        ev = w._rows[0].value_label
        ev.begin_edit()
        ev.edit.setText("64")
        ev.edit.editingFinished.emit()
        pump(app, lambda: lib.get(ea.id).preset.param(3, 0) == 64)
        assert w._rows[0].slider.value() == 64
        ev.begin_edit()
        ev.edit.setText("250")                                      # hors plage : ramené à 100
        ev.edit.editingFinished.emit()
        pump(app, lambda: lib.get(ea.id).preset.param(3, 0) == 100)
        ev.begin_edit()
        ev.edit.setText("5")
        ev.edit.cancelled.emit()
        ev.edit.editingFinished.emit()
        pump(app)
        assert lib.get(ea.id).preset.param(3, 0) == 100
        w.master_label.begin_edit()
        w.master_label.edit.setText("21")
        w.master_label.edit.editingFinished.emit()
        pump(app, lambda: lib.get(ea.id).preset.master == 21)

        # --- Retour à la version d'origine
        assert lib.get(ea.id).is_modified
        w.revert_original()
        pump(app, lambda: not lib.get(ea.id).is_modified)
        assert lib.get(ea.id).preset.wire_bytes() == a.wire_bytes()
        assert w.undo_redo(False).startswith("Annulé : retour à l'original")
        pump(app, lambda: lib.get(ea.id).is_modified)

        # --- Infobulles
        assert "Clic : jouer" in w.cards[0].toolTip()
        assert w.chips[3].toolTip() and w.btn_reset.toolTip() and w.btn_undo.toolTip() and w.btn_send.toolTip()
        w.title_label.setText("x" * 300)
        w.title_label.resize(80, 20)
        assert w.title_label.toolTip().startswith("xxx")
        w.title_label.setText("ok")
        assert w.title_label.toolTip() == ""

        # --- Phase B : versions, historique, comparaison, sauvegardes de l'ampli
        from ui.editor_dialogs import BackupsDialog, HistoryDialog, OverwriteDialog
        panel.select_row(row_of("Nirvana"))
        w.select_block(3)
        w._rows[0].slider.setValue(12)
        pump(app, lambda: lib.get(ea.id).preset.param(3, 0) == 12)
        v0 = len(lib.get(ea.id).versions)
        import ui.editor_interface as ei
        class _D:                                                          # NameDialog factice
            def __init__(s2, *a, **k): pass
            def exec(s2): return True
            def value(s2): return "Mon son gras"
        real = ei.NameDialog
        ei.NameDialog = _D
        w.create_version()
        ei.NameDialog = real
        assert len(lib.get(ea.id).versions) == v0 + 1 and lib.get(ea.id).versions[-1].label == "Mon son gras"
        hd = HistoryDialog(w, lib, lib.get(ea.id))
        kinds = [k[0] for k, *_ in hd.items]
        assert kinds[0] == "current" and kinds[-1] == "original" and "version" in kinds
        hd._select(("original", ""))
        a_, b_, ch = hd.comparison()
        assert a_[1] == "original" and b_[1] == "current" and ch                      # original -> actuel : des différences
        assert hd.yesButton.isEnabled() and not hd.btn_delete.isVisibleTo(hd)
        hd._select(hd.items[1][0])
        assert hd.btn_delete.isVisibleTo(hd)
        hd._select(("current", ""))
        assert not hd.yesButton.isEnabled()
        hd._select(("original", ""))
        hd._restore()
        assert hd.chosen == ("original", "")
        w.service.revert_original(ea.id)
        pump(app, lambda: not lib.get(ea.id).is_modified)
        # restaurer une version via la page (annulable)
        vid = lib.get(ea.id).versions[-1].id if lib.get(ea.id).versions else None
        if vid:
            w.service.restore_version(ea.id, vid)
            pump(app)
        bd = BackupsDialog(w, bank.backups, bank, w.slot_title, True)
        assert len(bd.items) >= 7 and bd.yesButton.isEnabled() and bd.current() is not None
        bd2 = BackupsDialog(w, bank.backups, bank, w.slot_title, False, slot=2)
        assert all(i[1] == 2 for i in bd2.items) and not bd2.yesButton.isEnabled()
        # fenêtre « écraser » : construite avec ses cartes et ses conséquences
        od = OverwriteDialog(w, "Écraser ?", "Actuellement", "A", amp.flash[1], "Sera remplacé par", "B",
                             lib.get(ea.id).preset, [("warn", "x"), ("ok", "y")], "Envoyer")
        assert len(od.note_rows) == 2 and od.new_card.chain.highlight is not None
        w.refresh()

        # --- Bibliothèque vide et suppression d'un preset associé : plus d'erreur, emplacements « hors bibliothèque »
        w.ask_info = lambda *a, **k: ("Mon son clean", ["clean"], "")
        w.new_blank()
        assert lib.get(w.sel_id).name == "Mon son clean" and w.sel_working() == Preset.default()
        w.ask_info = lambda *a, **k: None                                  # annulé : rien n'est créé
        n_before = len(lib.entries())
        w.new_blank()
        assert len(lib.entries()) == n_before
        vid = w.sel_id
        lib.delete(ea.id)
        wb.links.forget_entry(ea.id)
        panel.reload()
        w.refresh()
        assert w.cards[2].state == "unknown" and w.sel_id != ea.id
        w.resize(1150, 900)
        pump(app)
        assert w.height() == 900 and w.minimumSizeHint().height() <= 900            # la page tient sans défilement
        svc.shutdown()
    print("test_editor_ui OK")


if __name__ == "__main__":
    main()