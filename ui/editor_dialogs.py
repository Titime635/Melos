"""
Fenêtres de l'éditeur, pensées pour se lire d'un coup d'œil :
  - OverwriteDialog : « Actuellement → Sera remplacé par » avec la chaîne d'effets de chaque preset en miniatures,
    les blocs qui changent soulignés, et les conséquences en trois pastilles (attention / information) ;
  - HistoryDialog   : versions d'un preset, comparaison de deux versions (liste des réglages qui changent), retour ;
  - BackupsDialog   : sauvegardes automatiques de l'ampli, aperçu, restauration ou import dans la bibliothèque.
"""

from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (CaptionLabel, ComboBox, FluentIcon, IconWidget, LineEdit, MessageBoxBase, PushButton,
                            ScrollArea, SubtitleLabel, themeColor)

from editor.catalog import get_catalog
from editor.diff import diff_presets
from editor.preset import Preset
from ui.editor_widgets import (EFFECT_COLOR, EFFECT_NAME, GREEN, GREY, ORANGE, RADIUS, TILE_FILL, ElidedLabel,
                               GlyphWidget, draw_glyph, fluent_tip, paint_icon, small_font, surface, text_color,
                               with_alpha)


def nice_date(iso: str) -> str:
    """« 2026-11-11T10:17:03+01:00 » -> « 11/11 10:17 »."""
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m %H:%M")
    except (ValueError, TypeError):
        return iso or ""


def amp_name(p: Preset) -> str:
    m = get_catalog().effects[3].model(p.model(3))
    return m.name if m else "?"


# ------------------------------------------------------------------------------------------------ composants
class MiniChain(QWidget):
    """La chaîne d'effets d'un preset en 9 miniatures (même pictogrammes que la page). Les blocs de `highlight`
    sont soulignés : ce sont ceux qui changent."""
    TILE, GAP = 28, 5

    def __init__(self, preset: Preset | None = None, highlight=(), parent=None):
        super().__init__(parent)
        self.preset, self.highlight = preset, set(highlight)
        self.setFixedSize(9 * self.TILE + 8 * self.GAP, self.TILE + 9)
        self._tip()

    def set_preset(self, preset, highlight=()):
        self.preset, self.highlight = preset, set(highlight)
        self._tip()
        self.update()

    def _tip(self):
        if self.preset is None:
            return
        cat = get_catalog()
        lines = []
        for fid in self.preset.order:
            m = cat.effects[fid].model(self.preset.model(fid))
            lines.append(f"{EFFECT_NAME[fid]} · {m.name if m else '?'} · {'actif' if self.preset.enabled(fid) else 'désactivé'}")
        fluent_tip(self, "\n".join(lines))

    def paintEvent(self, e):
        if self.preset is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for i, fid in enumerate(self.preset.order):
            x = i * (self.TILE + self.GAP)
            r = QRectF(x + .5, .5, self.TILE - 1, self.TILE - 1)
            on = self.preset.enabled(fid)
            c = QColor(EFFECT_COLOR[fid])
            p.setPen(QPen(c if on else QColor(95, 95, 100), 1.8))
            p.setBrush(TILE_FILL if on else QColor(46, 46, 50))
            p.drawRoundedRect(r, 6, 6)
            draw_glyph(p, fid, r.adjusted(5, 5, -5, -5), c if on else QColor(125, 125, 130), 1.6)
            if fid in self.highlight:
                p.setPen(Qt.NoPen)
                p.setBrush(themeColor())
                p.drawRoundedRect(QRectF(x + 4, self.TILE + 3, self.TILE - 8, 3), 1.5, 1.5)


class PresetCard(QFrame):
    """Carte d'aperçu d'un preset : légende, nom, ampli et volume, chaîne en miniatures."""

    def __init__(self, caption: str, name: str, preset: Preset | None, accent=None, highlight=(), note: str = "",
                 parent=None):
        super().__init__(parent)
        self.accent = QColor(accent) if accent else None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 11, 14, 12)
        lay.setSpacing(3)
        self.caption = CaptionLabel(caption.upper())
        self.caption.setStyleSheet("letter-spacing: 1px;")
        lay.addWidget(self.caption)
        self.name = ElidedLabel(name or "—", bold=True)
        lay.addWidget(self.name)
        self.sub = ElidedLabel(f"{amp_name(preset)} · volume {preset.master}" if preset else "Emplacement vide / non lu",
                               dim=True)
        lay.addWidget(self.sub)
        lay.addSpacing(5)
        self.chain = MiniChain(preset, highlight)
        lay.addWidget(self.chain, 0, Qt.AlignLeft)
        self.note = CaptionLabel(note)
        self.note.setVisible(bool(note))
        lay.addWidget(self.note)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        fill, border = surface(False, False, None)
        p.setBrush(fill)
        p.setPen(QPen(self.accent if self.accent else border, 2 if self.accent else 1))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), RADIUS + 2, RADIUS + 2)


class NoteRow(QWidget):
    """Une ligne de conséquence : pastille (! orange, i grise, coche verte) + texte qui passe à la ligne."""
    COLORS = {"warn": ORANGE, "info": GREY, "ok": GREEN}

    def __init__(self, kind: str, text: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.badge = _Badge(kind)
        lay.addWidget(self.badge, 0, Qt.AlignTop)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setStyleSheet(f"color: {'rgba(255,255,255,200)' if _dark() else 'rgba(0,0,0,200)'}; background: transparent;")
        lay.addWidget(self.label, 1)


def _dark() -> bool:
    from qfluentwidgets import isDarkTheme
    return isDarkTheme()


class _Badge(QWidget):
    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(20, 20)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        col = QColor(NoteRow.COLORS[self.kind])
        p.setPen(Qt.NoPen)
        p.setBrush(with_alpha(col, 60))
        p.drawEllipse(QRectF(0, 0, 20, 20))
        p.setPen(col)
        f = small_font(self.font(), 0, True)
        p.setFont(f)
        p.drawText(QRectF(0, 0, 20, 20), Qt.AlignCenter, {"warn": "!", "info": "i", "ok": "✓"}[self.kind])


# ------------------------------------------------------------------------------------------------ écraser
class OverwriteDialog(MessageBoxBase):
    """Confirmation avant d'écrire dans un emplacement : avant / après côte à côte, blocs modifiés soulignés,
    conséquences listées avec une pastille de gravité."""

    def __init__(self, parent, title: str, old_caption: str, old_name: str, old: Preset | None,
                 new_caption: str, new_name: str, new: Preset, notes, ok_text: str, accent=None):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel(title))
        self.viewLayout.addSpacing(6)
        changes = diff_presets(old, new) if old is not None else []
        changed = {c.fid for c in changes if c.fid is not None}            # blocs à souligner
        row = QHBoxLayout()
        row.setSpacing(12)
        self.old_card = PresetCard(old_caption, old_name, old)
        self.arrow = IconWidget(FluentIcon.RIGHT_ARROW)
        self.arrow.setFixedSize(22, 22)
        n = len(changes)
        note = (f"{n} différence{'s' if n > 1 else ''} avec l'actuel (blocs soulignés)" if old is not None and n else "")
        self.new_card = PresetCard(new_caption, new_name, new, accent or themeColor(), changed, note)
        row.addWidget(self.old_card, 1)
        row.addWidget(self.arrow, 0, Qt.AlignVCenter)
        row.addWidget(self.new_card, 1)
        self.viewLayout.addLayout(row)
        self.viewLayout.addSpacing(8)
        self.note_rows = []
        for kind, text in notes:
            r = NoteRow(kind, text)
            self.viewLayout.addWidget(r)
            self.note_rows.append(r)
        self.widget.setMinimumWidth(760)
        self.yesButton.setText(ok_text)
        self.cancelButton.setText("Annuler")


class NameDialog(MessageBoxBase):
    """Une seule question : un nom."""

    def __init__(self, parent, title: str, default: str = "", placeholder: str = "Nom"):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel(title))
        self.edit = LineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setText(default)
        self.edit.selectAll()
        self.viewLayout.addWidget(self.edit)
        self.widget.setMinimumWidth(380)
        self.yesButton.setText("Valider")
        self.cancelButton.setText("Annuler")
        self.edit.setFocus()

    def value(self) -> str:
        return self.edit.text().strip()


# ------------------------------------------------------------------------------------------------ listes
class _Row(QFrame):
    clicked = Signal(object)

    def __init__(self, key, parent=None):
        super().__init__(parent)
        self.key = key
        self.selected = False
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_selected(self, v):
        self.selected = v
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.key)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        fill, border = surface(self.selected, self._hover)
        p.setBrush(fill)
        p.setPen(QPen(border, 1.6 if self.selected else 1))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), RADIUS, RADIUS)
        if self.selected:
            p.setPen(Qt.NoPen)
            p.setBrush(themeColor())
            p.drawRoundedRect(QRectF(2, 8, 3.5, self.height() - 16), 1.75, 1.75)


class VersionRow(_Row):
    ICONS = {"current": FluentIcon.EDIT, "original": FluentIcon.PIN, "manual": FluentIcon.TAG, "auto": FluentIcon.SEND}

    def __init__(self, key, kind: str, title: str, date: str, parent=None):
        super().__init__(key, parent)
        self.kind = kind
        self.setFixedHeight(50)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 7, 10, 6)
        lay.setSpacing(0)
        self.title = ElidedLabel(title, bold=True)
        sub = {"current": "copie de travail", "original": "version d'origine",
               "manual": "version nommée", "auto": "instantané automatique"}[kind]
        self.sub = ElidedLabel(f"{sub} · {nice_date(date)}" if date else sub, dim=True)
        lay.addWidget(self.title)
        lay.addWidget(self.sub)


class ChangeRow(QWidget):
    """Un réglage qui change : pictogramme du bloc, libellé, ancienne valeur → nouvelle valeur."""

    def __init__(self, fid, label: str, old: str, new: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 3, 2, 3)
        lay.setSpacing(10)
        if fid is not None:
            lay.addWidget(GlyphWidget(fid, 24))
        else:
            ic = IconWidget(FluentIcon.SETTING)
            ic.setFixedSize(24, 24)
            lay.addWidget(ic)
        name = EFFECT_NAME.get(fid, "") if fid is not None else ""
        self.label = ElidedLabel(f"{name} · {label}" if name else label, bold=True)
        lay.addWidget(self.label, 1)
        dim = "rgba(255,255,255,140)" if _dark() else "rgba(0,0,0,140)"
        self.old = QLabel(old)
        self.old.setStyleSheet(f"color: {dim}; background: transparent;")
        self.new = QLabel(new)
        self.new.setStyleSheet(f"color: {themeColor().name()}; font-weight: bold; background: transparent;")
        arrow = IconWidget(FluentIcon.RIGHT_ARROW)
        arrow.setFixedSize(14, 14)
        for w in (self.old, arrow, self.new):
            lay.addWidget(w)
        fluent_tip(self, f"{label} : {old} → {new}")


def _scroll(inner_layout_spacing=6):
    sc = ScrollArea()
    sc.setFrameShape(QFrame.NoFrame)
    sc.setWidgetResizable(True)
    sc.setStyleSheet("ScrollArea { background: transparent; border: none; }")
    inner = QWidget()
    inner.setStyleSheet("background: transparent;")
    col = QVBoxLayout(inner)
    col.setContentsMargins(0, 0, 6, 0)
    col.setSpacing(inner_layout_spacing)
    sc.setWidget(inner)
    return sc, col


def _clear(col: QVBoxLayout):
    while col.count():
        it = col.takeAt(0)
        w = it.widget()
        if w is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()


# ------------------------------------------------------------------------------------------------ historique
class HistoryDialog(MessageBoxBase):
    """Versions d'un preset de la bibliothèque. Choisir une version, la comparer à la version actuelle (ou à une
    autre) : la liste des réglages qui changent s'affiche. « Restaurer » en refait la copie de travail (annulable)."""

    def __init__(self, parent, library, entry):
        super().__init__(parent)
        self.library, self.entry_id = library, entry.id
        self.chosen: tuple | None = None                  # (« version »|« original », id) à restaurer
        self.viewLayout.addWidget(SubtitleLabel(f"Versions de « {entry.name} »"))
        body = QHBoxLayout()
        body.setSpacing(14)
        self.viewLayout.addLayout(body)

        left = QVBoxLayout()
        left.setSpacing(6)
        body.addLayout(left, 0)
        self.list_scroll, self.list_col = _scroll(5)
        self.list_scroll.setFixedWidth(250)
        left.addWidget(self.list_scroll, 1)
        self.btn_create = PushButton(FluentIcon.ADD, "Nouvelle version…")
        fluent_tip(self.btn_create, "Garde un instantané nommé de la copie de travail")
        left.addWidget(self.btn_create)

        right = QVBoxLayout()
        right.setSpacing(8)
        body.addLayout(right, 1)
        cmp_row = QHBoxLayout()
        cmp_row.addWidget(CaptionLabel("Comparer avec"))
        self.cmp_box = ComboBox()
        cmp_row.addWidget(self.cmp_box, 1)
        right.addLayout(cmp_row)
        self.summary = SubtitleLabel("")
        right.addWidget(self.summary)
        self.change_scroll, self.change_col = _scroll(2)
        right.addWidget(self.change_scroll, 1)
        self.btn_delete = PushButton(FluentIcon.DELETE, "Supprimer cette version")
        right.addWidget(self.btn_delete, 0, Qt.AlignLeft)

        self.widget.setMinimumSize(820, 470)
        self.yesButton.setText("Restaurer cette version")
        self.cancelButton.setText("Fermer")
        self.rows: dict = {}
        self.items: list = []            # [(clé, genre, titre, date, preset)]
        self.sel = None
        self.btn_create.clicked.connect(self._create)
        self.btn_delete.clicked.connect(self._delete)
        self.cmp_box.currentIndexChanged.connect(lambda _i: self._show_changes())
        self.yesButton.clicked.disconnect()
        self.yesButton.clicked.connect(self._restore)
        self._load()

    # --- données
    def _entry(self):
        return self.library.get(self.entry_id)

    def _load(self, keep=None):
        e = self._entry()
        items = [(("current", ""), "current", "Version actuelle", e.modified, e.preset)]
        for v in reversed(e.versions):
            items.append((("version", v.id), v.kind, v.label, v.date, v.preset))
        if e.original is not None:
            items.append((("original", ""), "original", "Version d'origine", e.created, e.original))
        self.items = items
        _clear(self.list_col)
        self.rows = {}
        for key, kind, title, date, _p in items:
            r = VersionRow(key, kind, title, date)
            r.clicked.connect(self._select)
            self.list_col.addWidget(r)
            self.rows[key] = r
        self.list_col.addStretch(1)
        keys = [i[0] for i in items]
        if keep not in keys:                    # par défaut : la plus récente des versions qui diffère de l'actuelle
            keep = next((i[0] for i in items[1:] if diff_presets(i[4], e.preset)), keys[1] if len(keys) > 1 else keys[0])
        self._select(keep)

    def _item(self, key):
        return next(i for i in self.items if i[0] == key)

    def _select(self, key):
        self.sel = key
        for k, r in self.rows.items():
            r.set_selected(k == key)
        self.cmp_box.blockSignals(True)
        self.cmp_box.clear()
        for k, kind, title, date, _p in self.items:
            if k != key:
                self.cmp_box.addItem(title if kind != "auto" and kind != "manual" else f"{title} · {nice_date(date)}",
                                     userData=k)
        self.cmp_box.setCurrentIndex(0)                     # par défaut : la version actuelle (première de la liste)
        self.cmp_box.blockSignals(False)
        self._show_changes()

    def comparison(self):
        """(version de départ, version d'arrivée, changements) pour la sélection courante."""
        a = self._item(self.sel)
        k = self.cmp_box.currentData()
        b = self._item(k) if k is not None else a
        return a, b, diff_presets(a[4], b[4])

    def _show_changes(self):
        a, b, changes = self.comparison()
        _clear(self.change_col)
        if not changes:
            self.summary.setText("Aucune différence")
        else:
            self.summary.setText(f"{len(changes)} différence{'s' if len(changes) > 1 else ''}")
            for c in changes:
                self.change_col.addWidget(ChangeRow(c.fid, c.label, c.old, c.new))
        self.change_col.addStretch(1)
        kind = self.sel[0]
        cur = self._entry().preset
        self.yesButton.setEnabled(kind != "current" and bool(diff_presets(self._item(self.sel)[4], cur)))
        self.btn_delete.setVisible(kind == "version")
        self.btn_delete.setEnabled(kind == "version")

    # --- actions
    def _create(self):
        dlg = NameDialog(self.window(), "Nouvelle version",
                         f"Version du {datetime.now().strftime('%d/%m %H:%M')}", "Nom de la version")
        if dlg.exec():
            v = self.library.add_version(self.entry_id, dlg.value() or "Version", "manual")
            self._load(("version", v.id) if v else None)

    def _delete(self):
        if self.sel and self.sel[0] == "version":
            self.library.delete_version(self.entry_id, self.sel[1])
            self._load()

    def _restore(self):
        if self.sel and self.sel[0] in ("version", "original"):
            self.chosen = self.sel
            self.accept()


# ------------------------------------------------------------------------------------------------ sauvegardes
class BackupRow(_Row):
    def __init__(self, key, slot: int, date: str, reason: str, amp: str, parent=None):
        super().__init__(key, parent)
        self.setFixedHeight(50)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 7, 10, 6)
        lay.setSpacing(0)
        lay.addWidget(ElidedLabel(f"Emplacement {slot + 1} · {nice_date(date)}", bold=True))
        lay.addWidget(ElidedLabel(f"{amp} · {reason}" if reason else amp, dim=True))


class BackupsDialog(MessageBoxBase):
    """Sauvegardes automatiques de l'ampli (faites avant chaque écrasement et à la connexion). On peut en restaurer
    une dans son emplacement d'origine ou l'importer dans la bibliothèque."""

    def __init__(self, parent, backups, bank, slot_title, connected: bool, slot=None, slot_colors=None):
        super().__init__(parent)
        self.backups, self.bank, self.slot_title = backups, bank, slot_title
        self.slot_colors = slot_colors or {}
        self.action: str | None = None
        self.chosen = None                                 # (emplacement, preset)
        self.viewLayout.addWidget(SubtitleLabel("Sauvegardes automatiques de l'ampli"))
        body = QHBoxLayout()
        body.setSpacing(14)
        self.viewLayout.addLayout(body)
        left = QVBoxLayout()
        left.setSpacing(6)
        body.addLayout(left)
        flt = QHBoxLayout()
        flt.addWidget(CaptionLabel("Emplacement"))
        self.slot_box = ComboBox()
        self.slot_box.addItem("Tous", userData=None)
        for i in range(7):
            self.slot_box.addItem(f"{i + 1}", userData=i)
        flt.addWidget(self.slot_box, 1)
        left.addLayout(flt)
        self.list_scroll, self.list_col = _scroll(5)
        self.list_scroll.setFixedWidth(270)
        left.addWidget(self.list_scroll, 1)

        right = QVBoxLayout()
        right.setSpacing(8)
        body.addLayout(right, 1)
        self.card = PresetCard("Contenu sauvegardé", "", None)
        right.addWidget(self.card)
        self.diff_title = CaptionLabel("")
        right.addWidget(self.diff_title)
        self.change_scroll, self.change_col = _scroll(2)
        right.addWidget(self.change_scroll, 1)
        self.btn_import = PushButton(FluentIcon.DOWNLOAD, "Importer dans la bibliothèque")
        fluent_tip(self.btn_import, "Crée un preset de la bibliothèque à partir de cette sauvegarde (l'ampli n'est pas touché)")
        right.addWidget(self.btn_import, 0, Qt.AlignLeft)

        self.connected = connected
        self.widget.setMinimumSize(860, 480)
        self.yesButton.setText("Restaurer dans l'emplacement")
        self.cancelButton.setText("Fermer")
        self.rows, self.items, self.sel = {}, [], None
        self.slot_box.currentIndexChanged.connect(lambda _i: self._load())
        self.btn_import.clicked.connect(self._import)
        self.yesButton.clicked.disconnect()
        self.yesButton.clicked.connect(self._restore)
        if slot is not None:
            self.slot_box.setCurrentIndex(slot + 1)
        self._load()

    def _load(self):
        slot = self.slot_box.currentData()
        self.items = self.backups.list(slot)
        _clear(self.list_col)
        self.rows = {}
        for n, (path, s, reason, date, preset) in enumerate(self.items):
            r = BackupRow(n, s, date, reason, amp_name(preset))
            r.clicked.connect(self._select)
            self.list_col.addWidget(r)
            self.rows[n] = r
        if not self.items:
            self.list_col.addWidget(CaptionLabel("Aucune sauvegarde pour le moment."))
        self.list_col.addStretch(1)
        self._select(0 if self.items else None)

    def _select(self, n):
        self.sel = n
        for k, r in self.rows.items():
            r.set_selected(k == n)
        _clear(self.change_col)
        has = n is not None and n < len(self.items)
        self.btn_import.setEnabled(has)
        self.yesButton.setEnabled(has and self.connected)
        if not has:
            self.card.name.setText("—")
            self.card.chain.set_preset(None)
            self.card.sub.setText("")
            self.diff_title.setText("")
            self.change_col.addStretch(1)
            return
        _path, s, reason, date, preset = self.items[n]
        self.yesButton.setText(f"Restaurer dans l'emplacement {s + 1}")
        cur = self.bank.slots[s].saved
        self.card.caption.setText(f"SAUVEGARDE DU {nice_date(date)} · EMPLACEMENT {s + 1}")
        self.card.name.setText(self.slot_title(s) if cur is not None and cur.wire_bytes() == preset.wire_bytes()
                               else f"Ancien contenu de l'emplacement {s + 1}")
        self.card.sub.setText(f"{amp_name(preset)} · volume {preset.master}" + (f" · {reason}" if reason else ""))
        self.card.chain.set_preset(preset)
        if cur is None:
            self.diff_title.setText("Emplacement actuel non lu")
        else:
            changes = diff_presets(cur, preset)
            self.diff_title.setText("Identique au contenu actuel de l'emplacement" if not changes else
                                    f"Par rapport au contenu actuel : {len(changes)} différence"
                                    f"{'s' if len(changes) > 1 else ''}")
            for c in changes:
                self.change_col.addWidget(ChangeRow(c.fid, c.label, c.old, c.new))
        self.change_col.addStretch(1)

    def current(self):
        if self.sel is None or self.sel >= len(self.items):
            return None
        _p, s, reason, date, preset = self.items[self.sel]
        return s, preset, date

    def _restore(self):
        c = self.current()
        if c:
            self.action, self.chosen = "restore", c
            self.accept()

    def _import(self):
        c = self.current()
        if c:
            self.action, self.chosen = "import", c
            self.accept()


# ------------------------------------------------------------------------------------------------ « Envoyer vers… »
class SlotPickRow(QWidget):
    """Une ligne du sélecteur d'emplacement : pastille numérotée, nom, ampli, état par rapport à la bibliothèque."""
    picked = Signal(int)
    H = 50

    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        self.info = info
        self._hover = False
        self.setFixedHeight(self.H)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.picked.emit(self.info["slot"])

    def paintEvent(self, e):
        from ui.editor_widgets import STATE_INFO, STATE_SHORT, draw_badge
        i = self.info
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(4, 2, -4, -2)
        done = i["same"]                                   # l'emplacement a déjà exactement ce preset
        if self._hover:
            fill, border = surface(False, True)
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(r, RADIUS, RADIUS)
        if i["target"] and not done:                       # il contient ce preset (ancienne version) : cible logique
            p.setPen(Qt.NoPen)
            p.setBrush(themeColor())
            p.drawRoundedRect(QRectF(r.left(), r.top() + 9, 3.5, r.height() - 18), 1.75, 1.75)
        # pastille numérotée
        c = QColor(i["color"])
        d = QRectF(r.left() + 12, r.center().y() - 13, 26, 26)
        p.setPen(Qt.NoPen)
        p.setBrush(with_alpha(c, 110 if done else 255))
        p.drawEllipse(d)
        p.setFont(small_font(self.font(), 0, True))
        p.setPen(QColor("black") if c.lightness() > 150 else QColor("white"))
        p.drawText(d, Qt.AlignCenter, str(i["slot"] + 1))
        # état à droite
        label, col, _ = STATE_INFO[i["state"]]
        short = "Déjà à jour" if done else STATE_SHORT[i["state"]]
        sf = small_font(self.font(), 1, True)
        sw = QFontMetrics(sf).horizontalAdvance(short)
        right = r.right() - 12
        p.setFont(sf)
        p.setPen(QColor(col))
        p.drawText(QPointF(right - sw, r.center().y() + QFontMetrics(sf).ascent() / 2 - 1), short)
        draw_badge(p, QRectF(right - sw - 19, r.center().y() - 7, 14, 14), i["state"])
        right -= sw + 19 + 10
        if i["current"]:
            draw_badge(p, QRectF(right - 16, r.center().y() - 8, 16, 16), "play")
            right -= 22
        # nom + sous-titre
        x = d.right() + 12
        wtxt = max(20, right - x)
        tf = small_font(self.font(), -0.5, True)
        p.setFont(tf)
        p.setPen(text_color("dim" if done else "primary"))
        p.drawText(QPointF(x, r.center().y() - 3), QFontMetrics(tf).elidedText(i["title"], Qt.ElideRight, int(wtxt)))
        sf2 = small_font(self.font(), 1.5)
        sub = i["amp"]
        if i["current"]:
            sub += " · joué par l'ampli"
        if i["target"] and not done:
            sub += " · même preset"
        p.setFont(sf2)
        p.setPen(text_color("secondary"))
        p.drawText(QPointF(x, r.center().y() + 14), QFontMetrics(sf2).elidedText(sub, Qt.ElideRight, int(wtxt)))


class SlotPicker(QFrame):
    """Fenêtre flottante pour choisir l'emplacement de destination : les 7 emplacements avec leur contenu, leur
    état et celui qui contient déjà ce preset mis en avant. Touches 1-7 pour choisir, Échap pour fermer."""
    picked = Signal(int)

    def __init__(self, title: str, infos: list, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.rows: list[SlotPickRow] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(0)
        head = ElidedLabel(title, bold=True)
        head.setContentsMargins(0, 0, 0, 0)
        hw = QWidget()
        hl = QVBoxLayout(hw)
        hl.setContentsMargins(10, 0, 10, 6)
        hl.setSpacing(0)
        hl.addWidget(head)
        hl.addWidget(CaptionLabel("Choisis l'emplacement à écraser · touches 1 à 7"))
        lay.addWidget(hw)
        for info in infos:
            row = SlotPickRow(info)
            row.picked.connect(self._pick)
            lay.addWidget(row)
            self.rows.append(row)
        self.setFixedWidth(400)

    def _pick(self, slot: int):
        self.close()
        self.picked.emit(slot)

    def keyPressEvent(self, e):
        k = e.key() - Qt.Key_1
        if 0 <= k < len(self.rows):
            self._pick(self.rows[k].info["slot"])
        elif e.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = _dark()
        p.setBrush(QColor(43, 43, 43) if dark else QColor(249, 249, 249))
        p.setPen(QPen(QColor(255, 255, 255, 40) if dark else QColor(0, 0, 0, 40), 1))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 10, 10)

    def popup_at(self, button):
        """Sous le bouton, aligné à droite (et ramené dans l'écran)."""
        self.adjustSize()
        g = button.mapToGlobal(button.rect().bottomRight())
        x, y = g.x() - self.width(), g.y() + 6
        scr = button.screen().availableGeometry() if button.screen() else None
        if scr:
            x = max(scr.left() + 6, min(x, scr.right() - self.width() - 6))
            if y + self.height() > scr.bottom():
                y = button.mapToGlobal(button.rect().topLeft()).y() - self.height() - 6
        self.move(x, y)
        self.show()
        self.setFocus()