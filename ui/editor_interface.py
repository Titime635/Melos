"""
Page « Éditeur » : on édite les presets de la BIBLIOTHÈQUE (la source de travail), puis on décide où et quand les
envoyer sur le Mighty.

  - bibliothèque (à gauche) : presets nommés, étiquettes libres ; filtre « sur le Mighty / hors Mighty » ;
  - 7 emplacements du Mighty : miroir de l'ampli. Clic = l'ampli joue cet emplacement ; chaque carte dit où en est son
    contenu par rapport à la bibliothèque (à jour / à renvoyer / modifié hors de Melos / hors bibliothèque) ;
  - chaîne d'effets et réglages : agissent sur le preset sélectionné, enregistré aussitôt (version d'origine gardée) ;
  - « Écouter » : le preset édité part en direct dans l'ampli sans rien écrire ; « Envoyer vers… » l'écrit dans un
    emplacement (confirmation avec aperçu, sauvegarde automatique de l'ancien contenu).
Toute la logique est dans editor/ ; cette page ne fait qu'afficher et appeler le service.
"""

import json
import threading
from pathlib import Path

from datetime import datetime

from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (Action, BodyLabel, CaptionLabel, FlowLayout, FluentIcon, HeaderCardWidget, IconWidget,
                            InfoBar, InfoBarPosition, MenuAnimationType, MessageBox, PrimaryPushButton, PushButton, RoundMenu,
                            ScrollArea, SearchLineEdit, SegmentedWidget, SwitchButton, ToggleButton, ToolButton,
                            themeColor)

from editor.catalog import get_catalog
from editor.patchfile import read_mppropatch
from editor.preset import FX_IDS, Preset
from editor.workbench import AHEAD, CHANGED, SYNCED, UNKNOWN, UNREAD
from ui.editor_dialogs import BackupsDialog, HistoryDialog, NameDialog, OverwriteDialog, amp_name, nice_date, SlotPicker
from ui.editor_widgets import (EFFECT_COLOR, EFFECT_NAME, GREEN, GREY, ORANGE, STATE_INFO, BlockChip, ChainArrow,
                               EditableValue, ElidedLabel, GlyphWidget, LibraryRow, ParamGrid, ParamRow,
                               PresetInfoDialog, SlotCard, StateLegend, TagPill, fluent_tip, readable)
from ui.widgets import NoWheelComboBox, NoWheelSlider

try:                                                   # mêmes couleurs et mêmes noms que le panneau Presets
    from ui.preset_panel import NAMES_FILE, PRESET_COLORS
except Exception:                                      # pragma: no cover
    NAMES_FILE, PRESET_COLORS = Path("preset_names.json"), {}

SPACING = 12
CONTROL_H = 32                  # hauteur unique des boutons


def custom_slot_names() -> dict[int, str]:
    try:
        return {int(k): v for k, v in json.loads(Path(NAMES_FILE).read_text(encoding="utf-8")).items()}
    except (OSError, ValueError):
        return {}


class _Coalescer:
    """Un curseur tiré produit des dizaines de valeurs par seconde : on n'envoie au thread de travail qu'une
    modification en attente par réglage (la plus récente)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._pending: dict = {}

    def push(self, key, value) -> bool:
        """Mémorise `value` ; True si aucune modification de ce réglage n'attendait (il faut alors lancer le job)."""
        with self._lock:
            first = key not in self._pending
            self._pending[key] = value
            return first

    def pop(self, key):
        with self._lock:
            return self._pending.pop(key, None)


def section_card(title: str, icon, color=None) -> HeaderCardWidget:
    """Carte à en-tête commune à toute la page : icône colorée + titre."""
    card = HeaderCardWidget()
    card.setTitle(title)
    ic = icon if isinstance(icon, QWidget) else IconWidget(icon)
    if not isinstance(icon, QWidget):
        ic.setFixedSize(18, 18)
    card.headerLayout.insertWidget(0, ic)
    card.headerLayout.insertSpacing(1, 8)
    card.section_icon = ic
    return card


class MirroredToolButton(ToolButton):
    """Bouton-icône dont le pictogramme est retourné (la flèche « rétablir » est celle d'« annuler » en miroir)."""

    def _drawIcon(self, icon, painter, rect, state=QIcon.Off):
        painter.save()
        painter.translate(rect.left() * 2 + rect.width(), 0)
        painter.scale(-1, 1)
        super()._drawIcon(icon, painter, rect, state)
        painter.restore()


def themeColorName() -> str:
    return themeColor().name()


def tool_button(icon, tip: str, slot, cls=ToolButton) -> ToolButton:
    b = cls(icon)
    fluent_tip(b, tip)
    b.setFixedHeight(CONTROL_H)
    b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    b.clicked.connect(slot)
    return b


class LibraryPanel(HeaderCardWidget):
    """Bibliothèque : la source de travail. Sélectionner un preset = l'éditer à droite."""

    def __init__(self, page: "EditorInterface"):
        super().__init__(page)
        self.page = page
        self.lib = page.library
        self.setTitle("Bibliothèque")
        ic = IconWidget(FluentIcon.LIBRARY)
        ic.setFixedSize(18, 18)
        self.headerLayout.insertWidget(0, ic)
        self.headerLayout.insertSpacing(1, 8)
        self.setFixedWidth(330)
        self.active_tags: set[str] = set()
        self.scope = "all"                              # all | on (sur le Mighty) | off (hors Mighty)
        self.rows: list[LibraryRow] = []
        self.current_id: str | None = None

        col = QVBoxLayout()
        col.setSpacing(SPACING - 4)
        self.viewLayout.addLayout(col)

        self.search = SearchLineEdit()
        self.search.setPlaceholderText("Rechercher un preset…")
        self.search.setFixedHeight(CONTROL_H)
        self.search.textChanged.connect(lambda _=None: self.reload())
        col.addWidget(self.search)

        self.scope_bar = SegmentedWidget()
        for key, text in (("all", "Tous"), ("on", "Sur le Mighty"), ("off", "Hors Mighty")):
            self.scope_bar.addItem(routeKey=key, text=text, onClick=lambda _=False, k=key: self._set_scope(k))
        self.scope_bar.setCurrentItem("all")
        fluent_tip(self.scope_bar, "Filtrer selon que le preset est (ou non) présent dans un emplacement du Mighty")
        col.addWidget(self.scope_bar)

        self.tag_bar = QWidget()
        self.tag_flow = FlowLayout(self.tag_bar)
        self.tag_flow.setContentsMargins(0, 0, 0, 0)
        self.tag_flow.setHorizontalSpacing(5)
        self.tag_flow.setVerticalSpacing(5)
        col.addWidget(self.tag_bar)

        self.scroll = ScrollArea()                      # la liste peut être longue : c'est le seul défilement de la page
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("ScrollArea { background: transparent; border: none; }")
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        self.list_col = QVBoxLayout(inner)
        self.list_col.setContentsMargins(0, 0, 4, 0)
        self.list_col.setSpacing(6)
        self.scroll.setWidget(inner)
        self.scroll.setMinimumHeight(160)
        col.addWidget(self.scroll, 1)

        self.empty_hint = CaptionLabel("")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setWordWrap(True)
        col.addWidget(self.empty_hint)

        tools = QHBoxLayout()
        tools.setSpacing(6)
        self.btn_add = tool_button(FluentIcon.ADD, "Nouveau preset : vide, ou importé d'un emplacement du Mighty",
                                   self.show_add_menu)
        self.btn_info = tool_button(FluentIcon.EDIT, "Nom, étiquettes et notes", self.edit_info)
        self.btn_dup = tool_button(FluentIcon.COPY, "Dupliquer", self.duplicate)
        self.btn_del = tool_button(FluentIcon.DELETE, "Supprimer de la bibliothèque", self.delete)
        self.btn_import = tool_button(FluentIcon.FOLDER_ADD, "Importer des fichiers .mppropatch de MightyEditor",
                                      self.import_patches)
        for b in (self.btn_add, self.btn_info, self.btn_dup, self.btn_del, self.btn_import):
            tools.addWidget(b)
        col.addLayout(tools)
        self.reload()

    # --- Contenu ---
    def selected_entry(self):
        return self.lib.get(self.current_id) if self.current_id else None

    def count(self) -> int:
        return len(self.rows)

    def select_row(self, n: int):
        if 0 <= n < len(self.rows):
            self._select(self.rows[n].entry_id)

    def _select(self, entry_id):
        self.current_id = entry_id
        for r in self.rows:
            r.set_selected(r.entry_id == entry_id)
        self._update_buttons()
        self.page.on_library_select(entry_id)

    def _set_scope(self, key):
        self.scope = key
        self.reload(rebuild_tags=False)

    def _rebuild_tags(self):
        while self.tag_flow.count():
            w = self.tag_flow.takeAt(0)            # FlowLayout.takeAt rend directement le widget
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        tags = self.lib.all_tags()
        self.active_tags = {t for t in self.active_tags if t.lower() in {x.lower() for x in tags}}
        for t in tags:
            pill = TagPill(t, t in self.active_tags)
            pill.toggled.connect(self._on_tag)
            self.tag_flow.addWidget(pill)
        self.tag_bar.setVisible(bool(tags))

    def _on_tag(self, tag, on):
        (self.active_tags.add if on else self.active_tags.discard)(tag)
        self.reload(rebuild_tags=False)

    def reload(self, *_, select_id=None, rebuild_tags=True):
        keep = select_id or self.current_id
        if rebuild_tags:
            self._rebuild_tags()
        entries = self.lib.search(self.search.text(), sorted(self.active_tags))
        if self.scope != "all":
            entries = [e for e in entries if bool(self.page.wb.entry_slots(e.id)) == (self.scope == "on")]
        while self.list_col.count():
            it = self.list_col.takeAt(0)
            wd = it.widget()
            if wd is not None:
                wd.hide()
                wd.setParent(None)
                wd.deleteLater()
        self.rows = []
        cat = get_catalog()
        for e in entries:
            amp = cat.effects[3].model(e.preset.model(3))
            row = LibraryRow(e.id, e.name, e.tags, self._slots_of(e.id), amp.name if amp else "", e.is_modified)
            row.clicked.connect(lambda _k=0, i=e.id: self._select(i))
            row.doubleClicked.connect(self.page.listen_entry)
            self.list_col.addWidget(row)
            self.rows.append(row)
        self.list_col.addStretch(1)
        ids = [r.entry_id for r in self.rows]
        self.current_id = keep if keep in ids else (ids[0] if ids else None)
        for r in self.rows:
            r.set_selected(r.entry_id == self.current_id)
        total = len(self.lib.entries())
        self.setTitle(f"Bibliothèque ({len(entries)}/{total})" if len(entries) != total else f"Bibliothèque ({total})")
        self.empty_hint.setText("" if entries else ("Aucun preset ne correspond." if total else
                                "Bibliothèque vide : crée un preset (+), importe un emplacement du Mighty ou des .mppropatch."))
        self.empty_hint.setVisible(not entries)
        self._update_buttons()
        self.page.on_library_select(self.current_id)

    def _slots_of(self, entry_id):
        return [(i, PRESET_COLORS.get(i, "#888888"), st) for i, st in self.page.wb.entry_slots(entry_id)]

    def refresh_badges(self):
        """Met à jour les pastilles d'emplacements et le point « modifié » sans reconstruire la liste."""
        for r in self.rows:
            e = self.lib.get(r.entry_id)
            if e is not None:
                r.set_state(self._slots_of(r.entry_id), e.is_modified, e.name)
        self._update_buttons()

    def _update_buttons(self):
        has = self.selected_entry() is not None
        for b in (self.btn_info, self.btn_dup, self.btn_del):
            b.setEnabled(has)

    # --- Actions ---
    def build_add_menu(self) -> RoundMenu:
        menu = RoundMenu(parent=self)
        menu.addAction(Action(FluentIcon.ADD, "Preset vide", triggered=self.page.new_blank))
        todo = self.page.importable_slots()
        if todo:
            menu.addSeparator()
            for i in todo:
                menu.addAction(Action(FluentIcon.DOWNLOAD, f"Importer l'emplacement {i + 1} · {self.page.slot_title(i)}",
                                      triggered=lambda _=False, n=i: self.page.import_slot(n)))
            if len(todo) > 1:
                menu.addAction(Action(FluentIcon.DOWNLOAD, f"Importer les {len(todo)} emplacements hors bibliothèque",
                                      triggered=self.page.import_all))
        return menu

    def show_add_menu(self):
        self.build_add_menu().exec(self.btn_add.mapToGlobal(QPoint(0, 0)), aniType=MenuAnimationType.PULL_UP)

    def add_blank(self):
        self.page.new_blank()

    def edit_info(self):
        e = self.selected_entry()
        if e is None:
            return
        res = self.page.ask_info("Infos du preset", e.name, e.tags, e.notes)
        if res:
            name, tags, notes = res
            self.lib.update(e.id, name=name or e.name, tags=tags, notes=notes)
            self.reload(select_id=e.id)
            self.page.refresh()

    def duplicate(self):
        e = self.selected_entry()
        if e is None:
            return
        res = self.page.ask_info("Dupliquer le preset", f"{e.name} (copie)", e.tags, e.notes)
        if res:
            self.reload(select_id=self.lib.duplicate(e.id, res[0] or None).id)

    def delete(self):
        e = self.selected_entry()
        if e is None:
            return
        extra = ""
        if self.page.wb.entry_slots(e.id):
            extra = " Les emplacements de l'ampli ne sont pas touchés : leur contenu deviendra « hors bibliothèque »."
        box = MessageBox("Supprimer ce preset ?", f"« {e.name} » sera supprimé de la bibliothèque.{extra}",
                         self.page.window())
        box.yesButton.setText("Supprimer")
        box.cancelButton.setText("Annuler")
        if box.exec():
            self.lib.delete(e.id)
            self.page.wb.links.forget_entry(e.id)
            self.current_id = None
            self.reload()
            self.page.refresh()

    def import_patches(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Importer des presets MightyEditor", "",
                                                "Presets MightyEditor (*.mppropatch)")
        last, errors = None, []
        for f in files:
            try:
                pf = read_mppropatch(f)
                last = self.lib.add(pf.preset, Path(f).stem, ["import"]).id
            except (OSError, ValueError) as exc:
                errors.append(f"{Path(f).name} : {exc}")
        if last:
            self.reload(select_id=last)
        if errors:
            self.page.error("\n".join(errors))


class StatusDot(QLabel):
    """Pastille de couleur d'état (vert : identique à l'ampli, orange : modifié, gris : hors ligne / non lu)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(12, 12)
        fluent_tip(self)
        self.set_color(GREY)

    def set_color(self, color: str):
        self.setStyleSheet(f"background: {color}; border-radius: 6px;")


class EditorInterface(QWidget):
    def __init__(self, service, library, state, parent=None):
        super().__init__(parent)
        self.setObjectName("EditorInterface")           # requis par FluentWindow
        self.service, self.library, self.state = service, library, state
        self.bank, self.wb = service.bank, service.wb
        self.sel_id: str | None = None                   # preset de la bibliothèque en cours d'édition
        self.sel_fid = 3                                 # bloc affiché : l'ampli
        self._co = _Coalescer()
        self._rows: list[ParamRow] = []
        self._rows_key = None
        self._order_key = None
        self._names = custom_slot_names()
        self._cat = get_catalog()
        self._hinted = False
        self._ready = False
        self._build()

        # Les signaux du service arrivent du thread de travail : des méthodes liées les remettent dans le thread Qt.
        service.slot_updated.connect(self._on_slot_updated)
        service.entry_updated.connect(self._on_entry_updated)
        service.loaded.connect(self._on_loaded)
        service.failed.connect(self._on_failed)
        service.sent.connect(self._on_sent)
        service.imported.connect(self._on_imported)
        service.history_applied.connect(self._on_history)
        service.audition_changed.connect(self._on_audition)
        service.busy_changed.connect(self._on_busy)
        service.kit_progress.connect(self._on_kit_progress)
        state.preset_changed.connect(self._on_amp_preset)
        state.connection_changed.connect(self._on_connection)
        self._ready = True
        self.refresh()

    # ------------------------------------------------------------------ construction
    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(SPACING + 4)
        self.library_panel = LibraryPanel(self)
        root.addWidget(self.library_panel)

        right = QVBoxLayout()
        right.setSpacing(SPACING)
        root.addLayout(right, 1)

        # --- Emplacements du Mighty (miroir de l'ampli)
        slots = section_card("Mighty Plug Pro · emplacements", FluentIcon.LAYOUT)
        self.btn_backups = tool_button(FluentIcon.HISTORY, "Sauvegardes automatiques de l'ampli : restaurer ou importer",
                                       lambda: self.open_backups())
        slots.headerLayout.addStretch(1)
        slots.headerLayout.addWidget(self.btn_backups)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.cards: list[SlotCard] = []
        for i in range(7):
            c = SlotCard(i, PRESET_COLORS.get(i, "#888888"))
            c.clicked.connect(self.play_slot)
            c.context.connect(self.show_slot_menu)
            row.addWidget(c)
            self.cards.append(c)
        slot_col = QVBoxLayout()
        slot_col.setSpacing(6)
        slot_col.addLayout(row)
        self.legend = StateLegend()
        slot_col.addWidget(self.legend)
        slots.viewLayout.addLayout(slot_col)
        right.addWidget(slots)

        # --- Barre du preset édité : nom + état, annuler/rétablir, écouter, envoyer
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.status_dot = StatusDot()
        actions.addWidget(self.status_dot)
        names = QVBoxLayout()
        names.setSpacing(0)
        self.title_label = ElidedLabel("", bold=True)
        self.caption_label = ElidedLabel("", dim=True, point_size=self.font().pointSizeF() - 1.5 if self.font().pointSizeF() > 8 else None)
        names.addWidget(self.title_label)
        names.addWidget(self.caption_label)
        actions.addLayout(names, 1)
        self.btn_undo = tool_button(FluentIcon.RETURN, "Annuler (Ctrl+Z)", lambda: self.undo_redo(False))
        self.btn_redo = tool_button(FluentIcon.RETURN, "Rétablir (Ctrl+Y)", lambda: self.undo_redo(True),
                                    MirroredToolButton)
        for b in (self.btn_undo, self.btn_redo):
            b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            b.setFixedWidth(CONTROL_H + 4)
            actions.addWidget(b)
        actions.addSpacing(6)
        self.btn_listen = ToggleButton(FluentIcon.HEADPHONE, "Écouter")
        self.btn_listen.setFixedHeight(CONTROL_H)
        fluent_tip(self.btn_listen, "Envoie ce preset dans l'ampli pour l'entendre, sans rien écrire en mémoire.\n"
                                    "L'écoute s'arrête quand l'ampli change de preset.")
        self.btn_listen.clicked.connect(lambda on: self.service.set_audition(bool(on)))
        actions.addWidget(self.btn_listen)
        self.btn_send = PrimaryPushButton(FluentIcon.SEND, "Envoyer vers…")
        self.btn_send.setFixedHeight(CONTROL_H)
        fluent_tip(self.btn_send, "Écrit ce preset dans un emplacement du Mighty (confirmation avec aperçu ; "
                                  "l'ancien contenu est sauvegardé)")
        self.btn_send.clicked.connect(self.show_send_menu)
        actions.addWidget(self.btn_send)
        self.btn_more = tool_button(FluentIcon.MORE, "Plus d'actions sur ce preset", self.show_more_menu)
        self.btn_more.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_more.setFixedWidth(CONTROL_H + 4)
        actions.addWidget(self.btn_more)
        right.addLayout(actions)

        # --- Chaîne d'effets
        chain = section_card("Chaîne d'effets", FluentIcon.CONNECT)
        chain_col = QVBoxLayout()
        chain_col.setSpacing(SPACING)
        chain.viewLayout.addLayout(chain_col)
        self.chain_row = QHBoxLayout()
        self.chain_row.setSpacing(4)
        chain_col.addLayout(self.chain_row)
        self.chips: dict[int, BlockChip] = {}
        for fid in FX_IDS:
            chip = BlockChip(fid)
            chip.clicked.connect(self.select_block)
            chip.dropped.connect(self._on_drop)
            self.chips[fid] = chip
        self.arrows = [ChainArrow() for _ in range(8)]
        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.btn_left = PushButton(FluentIcon.LEFT_ARROW, "Plus tôt")
        fluent_tip(self.btn_left, "Place le bloc sélectionné avant son voisin (ou glisse-le sur un autre bloc)")
        self.btn_left.setFixedHeight(CONTROL_H)
        self.btn_left.clicked.connect(lambda: self.move_block(-1))
        self.btn_right = PushButton(FluentIcon.RIGHT_ARROW, "Plus tard")
        fluent_tip(self.btn_right, "Place le bloc sélectionné après son voisin (ou glisse-le sur un autre bloc)")
        self.btn_right.setFixedHeight(CONTROL_H)
        self.btn_right.clicked.connect(lambda: self.move_block(+1))
        tools.addWidget(self.btn_left)
        tools.addWidget(self.btn_right)
        hint = CaptionLabel("ou glisse un bloc")
        fluent_tip(hint, "Glisse un bloc de la chaîne et dépose-le avant ou après un autre (repère bleu)")
        tools.addWidget(hint)
        tools.addStretch(1)
        vol_icon = IconWidget(FluentIcon.VOLUME)
        vol_icon.setFixedSize(18, 18)
        fluent_tip(vol_icon, "Volume général du preset")
        tools.addWidget(vol_icon)
        tools.addWidget(BodyLabel("Volume"))
        self.master = NoWheelSlider(Qt.Horizontal)
        self.master.setRange(0, 100)
        self.master.setFixedWidth(220)
        self.master.valueChanged.connect(self._on_master)
        fluent_tip(self.master, "Volume général du preset")
        tools.addWidget(self.master)
        self.master_label = EditableValue(themeColorName(), width=34)
        self.master_label.committed.connect(self.master.setValue)
        tools.addWidget(self.master_label)
        chain_col.addLayout(tools)
        right.addWidget(chain)

        # --- Réglages du bloc sélectionné
        self.block_glyph = GlyphWidget(3, 26)
        self.block_card = section_card("Bloc", self.block_glyph)
        right.addWidget(self.block_card)
        block_col = QVBoxLayout()
        block_col.setSpacing(SPACING)
        self.block_card.viewLayout.addLayout(block_col)
        top = QHBoxLayout()
        top.setSpacing(10)
        self.power = SwitchButton()
        self.power.setOnText("Actif")
        self.power.setOffText("Désactivé")
        self.power.checkedChanged.connect(self._on_power)
        top.addWidget(self.power)
        top.addSpacing(8)
        top.addWidget(BodyLabel("Modèle"))
        self.model_box = NoWheelComboBox()
        self.model_box.setFixedHeight(CONTROL_H)
        self.model_box.currentIndexChanged.connect(self._on_model)
        top.addWidget(self.model_box, 1)
        self.btn_reset = PushButton(FluentIcon.SYNC, "Réinitialiser")
        self.btn_reset.setFixedHeight(CONTROL_H)
        fluent_tip(self.btn_reset, "Remet les réglages de ce bloc à leurs valeurs par défaut (modèle et on/off conservés)")
        self.btn_reset.clicked.connect(self.reset_block)
        top.addWidget(self.btn_reset)
        block_col.addLayout(top)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: rgba(128,128,128,60); background: rgba(128,128,128,60); max-height: 1px; border: none;")
        block_col.addWidget(sep)
        self.param_grid = ParamGrid()
        block_col.addWidget(self.param_grid)
        self.empty_box = QWidget()
        el = QVBoxLayout(self.empty_box)
        el.setAlignment(Qt.AlignCenter)
        self.empty_label = BodyLabel("")
        self.empty_label.setAlignment(Qt.AlignCenter)
        el.addWidget(self.empty_label)
        self.btn_blank = PushButton(FluentIcon.ADD, "Créer un preset vide")
        self.btn_blank.setFixedHeight(CONTROL_H)
        self.btn_blank.clicked.connect(self.new_blank)
        el.addWidget(self.btn_blank, 0, Qt.AlignCenter)
        block_col.addWidget(self.empty_box)
        right.addStretch(1)

    # ------------------------------------------------------------------ état
    def sel_entry(self):
        return self.library.get(self.sel_id) if self.sel_id else None

    def sel_working(self):
        e = self.sel_entry()
        return e.preset if e else None

    def slot_title(self, i: int) -> str:
        state, eid = self.wb.slot_state(i)
        e = self.library.get(eid) if eid and state != UNKNOWN else None
        return e.name if e else (self._names.get(i) or f"Preset {i + 1}")

    def importable_slots(self) -> list[int]:
        return [i for i in range(7) if self.wb.slot_state(i)[0] in (UNKNOWN, CHANGED)]

    def error(self, text: str):
        InfoBar.error(title="Éditeur", content=text, isClosable=True, duration=6000,
                      position=InfoBarPosition.TOP, parent=self.window())

    def info(self, title: str, text: str = "", ms=3500):
        InfoBar.success(title=title, content=text, isClosable=False, duration=ms,
                        position=InfoBarPosition.TOP, parent=self.window())

    # Les signaux du service arrivent du thread de travail : des méthodes liées les remettent dans le thread Qt.
    def _on_slot_updated(self, _slot: int):
        self.refresh()

    def _on_entry_updated(self, _eid: str):
        self.refresh()

    def _on_failed(self, text: str):
        self.error(text)
        self.refresh()

    def _on_busy(self, _busy: bool):
        self._update_actions()

    def _on_kit_progress(self, *_):
        self.refresh()

    def _on_amp_preset(self, _i: int):
        QTimer.singleShot(150, self.refresh)

    def _on_connection(self, _c: bool):
        self.refresh()

    def _on_audition(self, on: bool):
        self.btn_listen.blockSignals(True)
        self.btn_listen.setChecked(on)
        self.btn_listen.blockSignals(False)
        self._update_actions()
        if not on and self.state.connected:
            self.info("Écoute arrêtée", "L'ampli rejoue ce qui est enregistré dans son emplacement.", 2500)

    def _on_history(self, entry_id: str):
        """Un annuler / rétablir vient de modifier un preset : on l'affiche pour que le changement soit visible."""
        self._rows_key = None
        self.library_panel.reload(select_id=entry_id, rebuild_tags=False)
        self.refresh()

    def _on_sent(self, slot: int, entry_id: str):
        e = self.library.get(entry_id)
        self.info(f"« {e.name if e else 'Preset'} » envoyé vers l'emplacement {slot + 1}",
                  "L'ancien contenu est sauvegardé (dossier preset_backups).")
        self.refresh()

    def _on_imported(self, entry_id: str):
        self.library_panel.reload(select_id=entry_id)
        self.refresh()

    def _on_loaded(self):
        self.refresh()
        todo = self.importable_slots()
        if todo and not self._hinted:
            self._hinted = True
            InfoBar.info(title=f"{len(todo)} emplacement(s) du Mighty hors bibliothèque",
                         content="Bouton + de la bibliothèque (ou clic droit sur un emplacement) pour les importer.",
                         isClosable=True, duration=7000, position=InfoBarPosition.TOP, parent=self.window())

    # ------------------------------------------------------------------ sélection
    def on_library_select(self, entry_id):
        if entry_id == self.sel_id:
            return
        self.sel_id = entry_id
        self._rows_key = None
        self.service.select(entry_id)
        if self._ready:
            self.refresh()

    def listen_entry(self, entry_id: str):
        """Double clic sur un preset de la bibliothèque : on l'écoute sur l'ampli."""
        self.library_panel.reload(select_id=entry_id, rebuild_tags=False)
        if self.state.connected:
            self.service.set_audition(True)

    def ask_info(self, title: str, name="", tags=(), notes=""):
        """Fenêtre nom / étiquettes / notes ; rend (nom, étiquettes, notes) ou None si annulée."""
        dlg = PresetInfoDialog(self.window(), title, name, tags, notes, self.library.all_tags())
        return dlg.values() if dlg.exec() else None

    def new_blank(self):
        """Nouveau preset vide : on demande son nom tout de suite."""
        res = self.ask_info("Nouveau preset", "", [], "")
        if res is None:
            return
        name, tags, notes = res
        e = self.library.add(Preset.default(), name or "Nouveau preset", tags, notes)
        self.library_panel.reload(select_id=e.id)
        self.refresh()

    # ------------------------------------------------------------------ le Mighty
    def play_slot(self, i: int):
        """Clic sur un emplacement : l'ampli joue ce preset."""
        if self.state.connected:
            self.service.play(i)

    def default_import_name(self, i: int) -> str:
        saved = self.bank.slots[i].saved
        amp = self._cat.effects[3].model(saved.model(3)) if saved else None
        return self._names.get(i) or (f"{amp.name} (emplacement {i + 1})" if amp else f"Emplacement {i + 1}")

    def import_slot(self, i: int):
        res = self.ask_info(f"Importer l'emplacement {i + 1} dans la bibliothèque", self.default_import_name(i),
                            ["import"], "")
        if res:
            name, tags, _notes = res
            self.service.import_slot(i, name or self.default_import_name(i), tags)

    def import_all(self):
        for i in self.importable_slots():
            self.service.import_slot(i, self.default_import_name(i), ["import"])

    def preset_summary(self, p: Preset) -> str:
        parts = []
        for fid in p.order:
            if p.enabled(fid):
                m = self._cat.effects[fid].model(p.model(fid))
                parts.append(f"{EFFECT_NAME[fid]} {m.name}" if m else EFFECT_NAME[fid])
        return " · ".join(parts) + (f"   (volume {p.master})" if parts else f"volume {p.master}")

    def _confirm(self, title: str, text: str, ok: str) -> bool:
        box = MessageBox(title, text, self.window())
        box.yesButton.setText(ok)
        box.cancelButton.setText("Annuler")
        return bool(box.exec())

    def confirm_overwrite(self, slot: int, new_name: str, new: Preset, notes, ok_text: str, title: str | None = None,
                          new_caption: str = "Sera remplacé par") -> bool:
        """Fenêtre « Actuellement → Sera remplacé par » (aperçu visuel de la chaîne, blocs modifiés soulignés)."""
        old = self.bank.slots[slot].saved
        dlg = OverwriteDialog(self.window(), title or f"Écraser l'emplacement {slot + 1} ?",
                              f"Actuellement · emplacement {slot + 1}", self.slot_title(slot), old,
                              new_caption, new_name, new, notes, ok_text, PRESET_COLORS.get(slot))
        return bool(dlg.exec())

    def overwrite_notes(self, slot: int, backup_note=True) -> list:
        """Conséquences d'une écriture dans `slot`, par gravité : (« warn » | « info » | « ok », texte)."""
        state, _ = self.wb.slot_state(slot)
        notes = []
        if state in (UNKNOWN, CHANGED):
            notes.append(("warn", "Le contenu actuel n'est pas (ou plus) dans la bibliothèque : il ne sera conservé que "
                                  "dans les sauvegardes automatiques de l'ampli."))
        if backup_note:
            notes.append(("ok", "L'ancien contenu est sauvegardé automatiquement (menu « Sauvegardes »)."))
        cur = self.bank.current
        if cur is not None and cur != slot:
            notes.append(("info", f"L'ampli repassera ensuite sur l'emplacement {cur + 1}, celui qu'il jouait."))
        return notes

    def send_notes(self, slot: int, e) -> list:
        return self.overwrite_notes(slot)

    def request_send(self, slot: int):
        e = self.sel_entry()
        if e is None:
            return
        state, eid = self.wb.slot_state(slot)
        if state == SYNCED and eid == e.id:
            self.info(f"Emplacement {slot + 1} déjà à jour", "", 2500)
            return
        if self.confirm_overwrite(slot, e.name, e.preset, self.send_notes(slot, e), "Envoyer"):
            self.service.send(e.id, slot)

    def request_copy(self, src: int, dst: int):
        p = self.bank.slots[src].saved
        if p is None:
            return
        if self.confirm_overwrite(dst, self.slot_title(src), p, self.overwrite_notes(dst), "Copier",
                                  f"Copier l'emplacement {src + 1} vers l'emplacement {dst + 1} ?",
                                  f"Copie de l'emplacement {src + 1}"):
            self.service.copy_slot(src, dst)

    # --- versions et sauvegardes (phase B)
    def create_version(self):
        e = self.sel_entry()
        if e is None:
            return
        dlg = NameDialog(self.window(), "Nouvelle version", f"Version du {datetime.now().strftime('%d/%m %H:%M')}",
                         "Nom de la version")
        if dlg.exec():
            v = self.library.add_version(e.id, dlg.value() or "Version", "manual")
            self.info("Version enregistrée" if v else "Rien de nouveau",
                      f"« {v.label} »" if v else "Identique à la dernière version : rien n'a été ajouté.")
            self.refresh()

    def open_history(self):
        e = self.sel_entry()
        if e is None:
            return
        dlg = HistoryDialog(self.window(), self.library, e)
        if dlg.exec() and dlg.chosen:
            kind, vid = dlg.chosen
            if kind == "original":
                self.service.revert_original(e.id)
            else:
                self.service.restore_version(e.id, vid)
        self.refresh()

    def open_backups(self, slot: int | None = None):
        dlg = BackupsDialog(self.window(), self.bank.backups, self.bank, self.slot_title, bool(self.state.connected),
                            slot)
        if not dlg.exec() or dlg.chosen is None:
            return
        s, preset, date = dlg.chosen
        if dlg.action == "restore":
            if self.confirm_overwrite(s, f"Sauvegarde du {nice_date(date)}", preset, self.overwrite_notes(s, False) +
                                      [("ok", "L'état actuel de l'emplacement est lui aussi sauvegardé.")],
                                      "Restaurer", f"Restaurer l'emplacement {s + 1} ?", "Sera remplacé par"):
                self.service.write_preset(s, preset)
        elif dlg.action == "import":
            res = self.ask_info("Importer la sauvegarde", f"{amp_name(preset)} · sauvegarde du {nice_date(date)}",
                                ["sauvegarde"], "")
            if res:
                e = self.library.add(preset, res[0] or "Sauvegarde", res[1], res[2])
                self.library_panel.reload(select_id=e.id)
                self.refresh()

    def slot_pick_infos(self) -> list[dict]:
        """Données du sélecteur « Envoyer vers… » : pour chaque emplacement, ce qu'il contient et où il en est."""
        e = self.sel_entry()
        out = []
        for i in range(7):
            state, eid = self.wb.slot_state(i)
            saved = self.bank.slots[i].saved
            out.append({"slot": i, "color": PRESET_COLORS.get(i, "#888888"), "title": self.slot_title(i),
                        "amp": amp_name(saved) if saved else "—", "state": state,
                        "current": i == self.bank.current,
                        "target": bool(e) and eid == e.id and state != UNKNOWN,
                        "same": bool(e) and eid == e.id and state == SYNCED})
        return out

    def build_send_picker(self) -> SlotPicker:
        e = self.sel_entry()
        picker = SlotPicker(f"Envoyer « {e.name if e else ''} » vers…", self.slot_pick_infos(), self.window())
        picker.picked.connect(self.request_send)
        return picker

    def show_send_menu(self):
        self._picker = self.build_send_picker()
        self._picker.popup_at(self.btn_send)

    def build_more_menu(self) -> RoundMenu:
        e = self.sel_entry()
        menu = RoundMenu(parent=self)
        n = len(e.versions) if e else 0
        menu.addAction(Action(FluentIcon.TAG, "Créer une version…", triggered=self.create_version))
        menu.addAction(Action(FluentIcon.HISTORY, f"Historique et comparaison des versions ({n + 1})…",
                              triggered=self.open_history))
        menu.addSeparator()
        a = Action(FluentIcon.RETURN, "Revenir à la version d'origine", triggered=self.revert_original)
        a.setEnabled(bool(e and e.is_modified))
        menu.addAction(a)
        b = Action(FluentIcon.PIN, "Prendre cette version comme version d'origine", triggered=self.keep_as_original)
        b.setEnabled(bool(e and e.is_modified))
        menu.addAction(b)
        return menu

    def show_more_menu(self):
        self.build_more_menu().exec(self.btn_more.mapToGlobal(QPoint(0, self.btn_more.height())))

    def revert_original(self):
        e = self.sel_entry()
        if e is not None and e.is_modified:
            self.service.revert_original(e.id)

    def keep_as_original(self):
        e = self.sel_entry()
        if e is not None and e.is_modified:
            self.library.set_original(e.id)
            self.refresh()

    def build_slot_menu(self, i: int) -> RoundMenu:
        menu = RoundMenu(parent=self)
        state, eid = self.wb.slot_state(i)
        connected = bool(self.state.connected)
        a = Action(FluentIcon.PLAY, "Jouer", triggered=lambda _=False: self.play_slot(i))
        a.setEnabled(connected)
        menu.addAction(a)
        e = self.sel_entry()
        if e is not None:
            b = Action(FluentIcon.SEND, f"Envoyer « {e.name} » ici…", triggered=lambda _=False: self.request_send(i))
            b.setEnabled(connected)
            menu.addAction(b)
        if eid and state != UNKNOWN and self.library.get(eid):
            menu.addAction(Action(FluentIcon.LIBRARY, "Afficher dans la bibliothèque",
                                  triggered=lambda _=False: self.library_panel.reload(select_id=eid)))
        if state in (UNKNOWN, CHANGED):
            menu.addAction(Action(FluentIcon.DOWNLOAD, "Importer dans la bibliothèque…",
                                  triggered=lambda _=False: self.import_slot(i)))
        menu.addAction(Action(FluentIcon.HISTORY, "Sauvegardes de cet emplacement…",
                              triggered=lambda _=False: self.open_backups(i)))
        if state != UNREAD:
            sub = RoundMenu("Copier vers l'emplacement", self)
            sub.setIcon(FluentIcon.COPY)
            for j in range(7):
                if j != i:
                    c = Action(f"{j + 1} · {self.slot_title(j)}", triggered=lambda _=False, d=j: self.request_copy(i, d))
                    c.setEnabled(connected)
                    sub.addAction(c)
            menu.addMenu(sub)
        return menu

    def show_slot_menu(self, i: int, pos):
        self.build_slot_menu(i).exec(pos)

    # ------------------------------------------------------------------ édition
    def undo_redo(self, redo: bool = False) -> str:
        """Ctrl+Z / Ctrl+Y (appelé par la fenêtre principale) : annule / rétablit la dernière modification d'un preset
        de la bibliothèque. Renvoie le texte à afficher."""
        label = self.service.can_redo() if redo else self.service.can_undo()
        if label is None:
            return "Rien à rétablir" if redo else "Rien à annuler"
        (self.service.redo if redo else self.service.undo)()
        return f"{'Rétabli' if redo else 'Annulé'} : {label}"

    def reset_block(self):
        """Remet les réglages du bloc affiché à leurs valeurs par défaut."""
        if self.sel_id is None:
            return
        fid = self.sel_fid
        self.service.edit(self.sel_id, lambda p: p.reset_params(fid), f"réinitialisation {EFFECT_NAME[fid]}")

    def select_block(self, fid: int):
        self.sel_fid = fid
        self._rows_key = None
        self.refresh()

    def toggle_block(self, fid: int):
        w = self.sel_working()
        if w is not None:
            on = not w.enabled(fid)
            self.service.edit(self.sel_id, lambda p: p.set_enabled(fid, on),
                              f"{EFFECT_NAME[fid]} {'activé' if on else 'désactivé'}")

    def move_block(self, delta: int):
        w = self.sel_working()
        if w is None:
            return
        fid = self.sel_fid
        pos = w.order.index(fid) + delta
        if 0 <= pos <= 8:
            self.service.edit(self.sel_id, lambda p: p.move_block(fid, pos), "ordre des blocs")

    @staticmethod
    def dropped_order(order, src: int, target: int, after: bool) -> list[int]:
        """Nouvel ordre quand `src` est déposé avant (ou après) `target`."""
        rest = [f for f in order if f != src]
        i = rest.index(target) + (1 if after else 0)
        return rest[:i] + [src] + rest[i:]

    def _on_drop(self, src: int, target: int, after: bool = False):
        """Un bloc a été glissé sur un autre : il se place avant ou après lui, selon la moitié visée."""
        w = self.sel_working()
        if w is None or src == target:
            return
        new = self.dropped_order(w.order, src, target, after)
        self.sel_fid = src
        self._rows_key = None
        if new == list(w.order):
            self.refresh()
            return
        self.service.edit(self.sel_id, lambda p: p.set_order(new), "ordre des blocs")

    def _on_power(self, on: bool):
        w = self.sel_working()
        if w is not None and w.enabled(self.sel_fid) != on and not self.power.signalsBlocked():
            self.toggle_block(self.sel_fid)

    def _on_model(self, idx: int):
        w = self.sel_working()
        if w is None or idx < 0 or self.model_box.signalsBlocked():
            return
        model = self.model_box.itemData(idx)
        fid = self.sel_fid
        if model is not None and w.model(fid) != model:
            name = self._cat.effects[fid].model(model).name
            self.service.edit(self.sel_id, lambda p: p.set_model(fid, model), f"modèle {EFFECT_NAME[fid]} : {name}")
            what = ("le baffle (IR) associé et les réglages de l'ampli ont été remplacés par ceux de ce modèle"
                    if fid == 3 else f"les réglages de {EFFECT_NAME[fid]} ont été remis par défaut")
            InfoBar.info(title="Changement de modèle", content=f"{what} (Ctrl+Z pour annuler).", isClosable=True,
                         duration=4500, position=InfoBarPosition.TOP, parent=self.window())

    def _queue(self, key, value, apply, label="réglage"):
        """Envoie `apply(preset, valeur)` au thread de travail, en ne gardant que la dernière valeur d'un réglage."""
        eid = self.sel_id
        if eid is None:
            return
        if self._co.push((eid,) + key, value):
            def mutate(p):
                v = self._co.pop((eid,) + key)
                if v is not None:
                    apply(p, v)
            self.service.edit(eid, mutate, label, (eid,) + key)       # même clé : un curseur tiré = une étape

    def _on_param(self, off: int, v: int):
        fid = self.sel_fid
        row = next((r for r in self._rows if r.pdef.offset == off), None)
        name = row.pdef.name if row else "réglage"
        self._queue(("p", fid, off), v, lambda p, val: p.set_param(fid, off, val), f"{EFFECT_NAME[fid]} · {name}")

    def _on_master(self, v: int):
        self.master_label.setValue(v)
        if not self.master.signalsBlocked():
            self._queue(("master",), v, lambda p, val: setattr(p, "master", val), "volume")

    # ------------------------------------------------------------------ affichage
    def refresh(self):
        bank, cat = self.bank, self._cat
        self._names = custom_slot_names()
        for i, card in enumerate(self.cards):
            state, eid = self.wb.slot_state(i)
            saved = bank.slots[i].saved
            amp = cat.effects[3].model(saved.model(3)) if saved else None
            contains = bool(self.sel_id) and eid == self.sel_id and state not in (UNKNOWN, UNREAD)
            card.set_info(self.slot_title(i), amp.name if amp else "", state, contains, i == bank.current)
        w = self.sel_working()
        self._refresh_chain(w)
        self._refresh_block(w)
        self._update_actions()
        self.library_panel.refresh_badges()

    def _refresh_chain(self, w: Preset | None):
        order = tuple(w.order) if w else tuple(FX_IDS)
        if order != self._order_key:
            while self.chain_row.count():
                self.chain_row.takeAt(0)
            for n, fid in enumerate(order):
                if n:
                    self.chain_row.addWidget(self.arrows[n - 1])
                self.chain_row.addWidget(self.chips[fid], 1)
            self._order_key = order
        for fid, chip in self.chips.items():
            m = self._cat.effects[fid].model(w.model(fid)) if w else None
            chip.set_info(m.name if m else "", bool(w and w.enabled(fid)), fid == self.sel_fid)
            chip.setEnabled(w is not None)
        pos = order.index(self.sel_fid) if self.sel_fid in order else 0
        self.btn_left.setEnabled(w is not None and pos > 0)
        self.btn_right.setEnabled(w is not None and pos < 8)
        self.master.setEnabled(w is not None)
        if w is not None and not self.master.isSliderDown():
            self.master.blockSignals(True)
            self.master.setValue(w.master)
            self.master.blockSignals(False)
            self.master_label.setValue(w.master)

    def _refresh_block(self, w: Preset | None):
        e = self._cat.effects[self.sel_fid]
        color = EFFECT_COLOR[self.sel_fid]
        self.block_card.setTitle(f"{EFFECT_NAME[self.sel_fid]} · {e.label}")
        self.block_glyph.set_effect(self.sel_fid)
        self.empty_box.setVisible(w is None)
        for wd in (self.power, self.model_box, self.btn_reset):
            wd.setVisible(w is not None)
        self.param_grid.setVisible(w is not None)
        if w is None:
            self.param_grid.clear()
            self._rows, self._rows_key = [], None
            self.empty_label.setText("Aucun preset sélectionné.\nChoisis un preset dans la bibliothèque, crée-en un "
                                     "ou importe un emplacement du Mighty.")
            return
        model = w.model(self.sel_fid)
        mdef = e.model(model)
        key = (self.sel_id, self.sel_fid, model)
        if key != self._rows_key:                                  # nouveau preset / bloc / modèle : on reconstruit
            self.model_box.blockSignals(True)
            self.model_box.clear()
            for idx in sorted(e.models):
                self.model_box.addItem(e.models[idx].name, userData=idx)
            self.model_box.blockSignals(False)
            rows = []
            for p in (mdef.params if mdef else ()):
                row = ParamRow(p, accent=readable(color))
                row.changed.connect(lambda v, off=p.offset: self._on_param(off, v))
                rows.append(row)
            self._rows = rows
            self.param_grid.set_rows(rows)
            self._rows_key = key
        self.model_box.blockSignals(True)
        self.model_box.setCurrentIndex(self.model_box.findData(model))
        self.model_box.blockSignals(False)
        self.power.blockSignals(True)
        self.power.setChecked(w.enabled(self.sel_fid))
        self.power.blockSignals(False)
        for row in self._rows:
            row.set_value(w.param(self.sel_fid, row.pdef.offset))

    def entry_caption(self, e) -> str:
        parts = ["modifié depuis la version d'origine" if e.is_modified else "version d'origine"]
        slots = self.wb.entry_slots(e.id)
        if slots:
            parts.append("sur le Mighty : " + ", ".join(f"{s + 1} ({STATE_INFO[st][0].lower()})" for s, st in slots))
        else:
            parts.append("pas sur le Mighty" if self.state.connected else "Mighty non connecté")
        if self.service.audition and self.wb.sel == e.id:
            parts.append("écoute en cours")
        return " · ".join(parts)

    def _update_actions(self):
        e = self.sel_entry()
        connected = bool(self.state.connected)
        has = e is not None
        busy = self.service.busy
        self.btn_listen.blockSignals(True)
        self.btn_listen.setChecked(bool(self.service.audition and has))
        self.btn_listen.blockSignals(False)
        self.btn_listen.setEnabled(connected and has)
        self.btn_send.setEnabled(connected and has)
        self.btn_more.setEnabled(has)
        undo, redo = self.service.can_undo(), self.service.can_redo()
        self.btn_undo.setEnabled(undo is not None)
        self.btn_redo.setEnabled(redo is not None)
        self.btn_undo.setToolTip(f"Annuler : {undo} (Ctrl+Z)" if undo else "Rien à annuler (Ctrl+Z)")
        self.btn_redo.setToolTip(f"Rétablir : {redo} (Ctrl+Y)" if redo else "Rien à rétablir (Ctrl+Y)")
        if has:
            self.title_label.setText(e.name)
            self.caption_label.setText(self.entry_caption(e))
            self.status_dot.set_color(ORANGE if e.is_modified else GREEN)
            self.status_dot.setToolTip("Modifié depuis la version d'origine" if e.is_modified
                                       else "Identique à la version d'origine")
        else:
            self.title_label.setText("Aucun preset sélectionné")
            self.caption_label.setText("Choisis un preset dans la bibliothèque")
            self.status_dot.set_color(GREY)
            self.status_dot.setToolTip("")