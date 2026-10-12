"""
Module Batterie d'accompagnement + EQ.

- Interrupteur « ACTIVE / COUPÉE » dans l'en-tête.
- Une tuile affiche le style courant (icône de sa catégorie, nom, catégorie et numéro) ; un clic ouvre le
  sélecteur : onglets de catégories (+ onglet Favoris), styles de la catégorie en grille, étoile pour mettre
  un style en favori. Les 75 styles et leurs catégories sont dans midi/drum_styles.py.
- Volume, puis EQ (Grave / Médium / Aigu) : le module s'adapte à sa hauteur (EQ masqué, puis volume).

Tout passe en CC direct, pas de SysEx (cf docs/protocol_notes.md). Comme pour les presets et le tuner, on ne
peut pas compter sur un écho fiable du device après une commande envoyée par l'host : chaque action appelle
donc un setter sur AmpState en plus d'envoyer le CC. Numéro affiché = CC brut + 1.

Quand le looper a la synchro activée, démarrer la batterie attend le prochain début de mesure de sa grille
(cf ui/loop_panel.py : request_drum_start) ; le tempo est envoyé par DeviceSync (cf midi/sync.py).
"""

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)
from qfluentwidgets import CaptionLabel

from midi import protocol
from midi.drum_styles import BY_KEY, CATEGORIES, STYLES, raws_of, style_info
from midi.sender import MidiSender
from state.amp_state import AmpState
from ui.drum_icons import draw_category_icon, draw_star
from ui.module_card import MODULE_COLORS, ModuleCard
from ui.popup_utils import show_popup_under
from ui.power_pill import PowerPill, text_color
from ui.widgets import NoWheelSlider

STAR_COLOR = QColor("#FFC107")
TILE_H = 58
ROW_H = 30
GAP = 10


def _font(px: int, bold: bool = False) -> QFont:
    f = QFont(QApplication.font())
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def _faint(alpha: int) -> QColor:
    c = text_color()
    c.setAlpha(alpha)
    return c


class StyleTile(QAbstractButton):
    """Style courant : grande tuile cliquable (ouvre le sélecteur) avec l'étoile des favoris à droite."""

    favorite_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._raw = 0
        self._favorite = False
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setFixedHeight(TILE_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip("Choisir un style")

    def set_style(self, raw: int, favorite: bool):
        self._raw, self._favorite = raw, favorite
        self.update()

    def _star_rect(self) -> QRectF:
        return QRectF(self.width() - 36, (self.height() - 28) / 2, 28, 28)

    def mouseReleaseEvent(self, event):
        if self._star_rect().contains(event.position()) and event.button() == Qt.LeftButton:
            self.favorite_clicked.emit()
            return
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        over = self._star_rect().contains(event.position())
        if over != self._hover:
            self._hover = over
            self.setToolTip("Retirer des favoris" if self._favorite else "Ajouter aux favoris") if over \
                else self.setToolTip("Choisir un style")
            self.update()

    def leaveEvent(self, _event):
        self._hover = False
        self.update()

    def paintEvent(self, _event):
        cat, name, number = style_info(self._raw)
        color = QColor(cat.color)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        fill = QColor(color); fill.setAlpha(34 if not self.underMouse() else 52)
        edge = QColor(color); edge.setAlpha(150)
        p.setPen(QPen(edge, 1.2)); p.setBrush(fill)
        p.drawRoundedRect(r, 10, 10)

        d = TILE_H - 16
        badge = QRectF(8, 8, d, d)
        p.setPen(Qt.NoPen); p.setBrush(color)
        p.drawEllipse(badge)
        dark = (color.lightness() > 150)
        draw_category_icon(p, cat.key, badge.adjusted(9, 9, -9, -9), QColor("#1b1b1b") if dark else QColor("white"))

        x = badge.right() + 12
        w = self.width() - x - 44
        p.setPen(text_color()); p.setFont(_font(17, True))
        p.drawText(QRectF(x, 7, w, 24), Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetrics(p.font()).elidedText(name, Qt.ElideRight, int(w)))
        p.setPen(_faint(170)); p.setFont(_font(12))
        p.drawText(QRectF(x, 31, w, 18), Qt.AlignVCenter | Qt.AlignLeft, f"{cat.label}  ·  n° {number}")

        star = self._star_rect().adjusted(4, 4, -4, -4)
        if self._favorite:
            draw_star(p, star, STAR_COLOR, True)
        else:
            draw_star(p, star, _faint(210 if self._hover else 110), False)
        p.end()


class CategoryChip(QAbstractButton):
    """Onglet de catégorie : icône + étiquette."""

    def __init__(self, key: str, label: str, color: str, parent=None):
        super().__init__(parent)
        self.key, self._label, self._color = key, label, QColor(color)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(60, 52)
        self.setToolTip(label)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.isChecked():
            fill = QColor(self._color); fill.setAlpha(55)
            edge = QColor(self._color); edge.setAlpha(210)
            p.setPen(QPen(edge, 1.4)); p.setBrush(fill)
            p.drawRoundedRect(r, 9, 9)
        elif self.underMouse():
            fill = text_color(); fill.setAlpha(18)
            p.setPen(Qt.NoPen); p.setBrush(fill)
            p.drawRoundedRect(r, 9, 9)
        draw_category_icon(p, self.key, QRectF(self.width() / 2 - 11, 6, 22, 22), self._color)
        p.setFont(_font(10, True))
        p.setPen(text_color() if self.isChecked() else _faint(190))
        p.drawText(QRectF(0, 31, self.width(), 16), Qt.AlignCenter, self._label)
        p.end()


class StyleItem(QWidget):
    """Un style dans la grille du sélecteur : pastille numérotée, nom, étoile."""

    chosen = Signal(int)
    star_toggled = Signal(int)

    def __init__(self, raw: int, current: bool, favorite: bool, parent=None):
        super().__init__(parent)
        self.raw, self._current, self._favorite = raw, current, favorite
        self._hover = False
        self.setFixedHeight(38)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

    def _star_rect(self) -> QRectF:
        return QRectF(self.width() - 28, (self.height() - 22) / 2, 22, 22)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        if self._star_rect().adjusted(-4, -6, 4, 6).contains(event.position()):
            self.star_toggled.emit(self.raw)
        else:
            self.chosen.emit(self.raw)

    def enterEvent(self, _event):
        self._hover = True; self.update()

    def leaveEvent(self, _event):
        self._hover = False; self.update()

    def paintEvent(self, _event):
        cat, name, number = style_info(self.raw)
        color = QColor(cat.color)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self._current:
            fill = QColor(color); fill.setAlpha(60)
            edge = QColor(color); edge.setAlpha(220)
            p.setPen(QPen(edge, 1.3)); p.setBrush(fill)
        elif self._hover:
            fill = text_color(); fill.setAlpha(20)
            p.setPen(Qt.NoPen); p.setBrush(fill)
        else:
            p.setPen(Qt.NoPen); p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 8, 8)

        chip = QRectF(6, (self.height() - 24) / 2, 24, 24)
        p.setPen(Qt.NoPen); p.setBrush(color)
        p.drawEllipse(chip)
        p.setPen(QColor("#1b1b1b") if color.lightness() > 150 else QColor("white"))
        p.setFont(_font(11 if number < 100 else 9, True))
        p.drawText(chip, Qt.AlignCenter, str(number))

        w = self.width() - 36 - 34
        p.setPen(text_color()); p.setFont(_font(14, self._current))
        p.drawText(QRectF(38, 0, w, self.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetrics(p.font()).elidedText(name, Qt.ElideRight, int(w)))

        star = self._star_rect().adjusted(3, 3, -3, -3)
        if self._favorite:
            draw_star(p, star, STAR_COLOR, True)
        elif self._hover or self._current:
            draw_star(p, star, _faint(120), False)
        p.end()


class StylePicker(QFrame):
    """Volet de choix du style : onglets de catégories (+ Favoris) puis grille des styles."""

    style_chosen = Signal(int)       # CC brut
    favorite_toggled = Signal(int)   # CC brut

    COLUMNS = 2

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("DrumStylePicker")
        self.setStyleSheet("#DrumStylePicker { background: palette(window); "
                           "border: 1px solid rgba(128,128,128,0.45); border-radius: 10px; }")
        self.setFixedWidth(404)
        self._current = 0
        self._favorites: list[int] = []
        self._tab = "FAV"

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        grid = QGridLayout()
        grid.setSpacing(4)
        self._chips: dict[str, CategoryChip] = {}
        chips = [("FAV", "Favoris", "#FFC107")] + [(c.key, c.short, c.color) for c in CATEGORIES]
        for i, (key, label, color) in enumerate(chips):
            chip = CategoryChip(key, label, color)
            chip.clicked.connect(lambda _c=False, k=key: self._select_tab(k))
            self._chips[key] = chip
            grid.addWidget(chip, i // 6, i % 6)
        root.addLayout(grid)

        self._title = CaptionLabel("")
        root.addWidget(self._title)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setFixedHeight(4 * 38 + 3 * 4 + 2)
        self._scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        root.addWidget(self._scroll)

    def open(self, anchor: QWidget, current: int, favorites: list[int]):
        self._current, self._favorites = current, list(favorites)
        cat = style_info(current)[0].key
        self._select_tab(cat)
        show_popup_under(self, anchor, False)

    def set_favorites(self, favorites: list[int]):
        self._favorites = list(favorites)
        self._select_tab(self._tab)

    def set_current(self, current: int):
        self._current = current
        if self.isVisible():
            self._select_tab(self._tab)

    def _select_tab(self, key: str):
        self._tab = key
        for k, chip in self._chips.items():
            chip.setChecked(k == key)
        if key == "FAV":
            raws = sorted(self._favorites)
            self._title.setText("Favoris" if raws else "Aucun favori — clique sur l'étoile d'un style pour l'ajouter.")
        else:
            raws = raws_of(key)
            self._title.setText(f"{BY_KEY[key].label} · {len(raws)} styles")
        body = QWidget()
        lay = QGridLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        for i, raw in enumerate(raws):
            item = StyleItem(raw, raw == self._current, raw in self._favorites)
            item.chosen.connect(self._on_chosen)
            item.star_toggled.connect(self.favorite_toggled)
            lay.addWidget(item, i // self.COLUMNS, i % self.COLUMNS)
        lay.setRowStretch(len(raws) // self.COLUMNS + 1, 1)
        for c in range(self.COLUMNS):
            lay.setColumnStretch(c, 1)
        self._scroll.setWidget(body)

    def _on_chosen(self, raw: int):
        self.hide()
        self.style_chosen.emit(raw)


class DrumPanel(ModuleCard):
    adaptive = True

    def __init__(self, state: AmpState, sender: MidiSender, parent=None):
        super().__init__(parent, accent=MODULE_COLORS["drums"])
        self.setTitle("Batterie")

        self._state = state
        self._sender = sender
        self._sync = None            # LoopPanel qui cale le démarrage sur la mesure (set_sync)
        self._pending_start = False  # démarrage demandé, en attente de la mesure

        self._build_ui()

        self._state.drum_updated.connect(self._refresh)
        self._refresh()

    def _build_ui(self):
        self._switch = PowerPill(MODULE_COLORS["drums"], "Active : la batterie joue (calée sur la mesure du looper "
                                                          "si le calage est activé).\nCoupée : silence.")
        self._switch.toggled.connect(self._on_enable_toggled)
        self.headerLayout.addWidget(self._switch)

        layout = QVBoxLayout()
        layout.setSpacing(GAP)
        self.viewLayout.addLayout(layout)

        self._tile = StyleTile()
        self._tile.clicked.connect(self._open_picker)
        self._tile.favorite_clicked.connect(lambda: self._toggle_favorite(self._state.drum_style))
        layout.addWidget(self._tile)

        self._picker = StylePicker(self)
        self._picker.style_chosen.connect(self._on_style_changed)
        self._picker.favorite_toggled.connect(self._toggle_favorite)

        # Volume : curseur en % (0-100), converti en CC sur la plage utilisable (cf midi/protocol.py)
        self._level_w = QWidget()
        lv = QVBoxLayout(self._level_w)
        lv.setContentsMargins(0, 0, 0, 0)
        self._level_slider, self._level_label = self._make_slider()
        self._level_slider.setRange(0, 100)
        self._level_slider.valueChanged.connect(lambda v: self._level_label.setText(f"{v}%"))
        self._level_slider.valueChanged.connect(self._on_level_changed)
        lv.addWidget(self._slider_row("Volume", self._level_slider, self._level_label, strong=True))
        layout.addWidget(self._level_w)

        # EQ
        self._eq_w = QWidget()
        eq = QVBoxLayout(self._eq_w)
        eq.setContentsMargins(0, 0, 0, 0)
        eq.setSpacing(2)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: rgba(128,128,128,0.35);")
        eq.addWidget(sep)
        self._bass_slider, self._bass_label = self._make_slider()
        self._middle_slider, self._middle_label = self._make_slider()
        self._treble_slider, self._treble_label = self._make_slider()
        for text, slider, label in (("Grave", self._bass_slider, self._bass_label),
                                    ("Médium", self._middle_slider, self._middle_label),
                                    ("Aigu", self._treble_slider, self._treble_label)):
            slider.valueChanged.connect(self._on_eq_changed)
            eq.addWidget(self._slider_row(text, slider, label))
        layout.addWidget(self._eq_w)
        layout.addStretch()

    @staticmethod
    def _make_slider():
        slider = NoWheelSlider(Qt.Horizontal)
        slider.setRange(0, 127)
        label = QLabel("0")
        label.setFixedWidth(40)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        slider.valueChanged.connect(lambda v: label.setText(str(v)))
        return slider, label

    @staticmethod
    def _slider_row(text: str, slider, label, strong: bool = False) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        name = QLabel(text)
        name.setFixedWidth(58)
        f = name.font(); f.setBold(strong); name.setFont(f)
        h.addWidget(name)
        h.addWidget(slider, stretch=1)
        h.addWidget(label)
        row.setFixedHeight(ROW_H)
        return row

    # --- Taille / densité ---

    def _base_height(self) -> int:
        return self.chrome_height() + 4 + TILE_H

    def minimumSizeHint(self) -> QSize:
        return QSize(230, self._base_height())

    def sizeHint(self) -> QSize:
        return QSize(380, self._base_height() + GAP + ROW_H + GAP + 4 + 3 * (ROW_H + 2))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        room = self.height() - self._base_height()
        level_h = GAP + ROW_H
        eq_h = GAP + 4 + 3 * (ROW_H + 2)
        self._level_w.setVisible(room >= level_h)
        self._eq_w.setVisible(room >= level_h + eq_h)

    # --- Sélecteur / favoris ---

    def _open_picker(self):
        self._picker.open(self._tile, self._state.drum_style, self._state.drum_favorites)

    def _toggle_favorite(self, raw: int):
        self._state.toggle_drum_favorite(raw)
        self._picker.set_favorites(self._state.drum_favorites)

    # --- Actions utilisateur : on envoie ET on met à jour AmpState nous-mêmes ---
    # (pas d'écho garanti pour une commande host, même logique que le fix presets)

    def set_sync(self, loop_panel):
        """Branche le looper dont la grille cale le démarrage de la batterie."""
        self._sync = loop_panel

    def toggle_enabled(self):
        """Active / coupe la batterie comme son interrupteur (raccourci clavier). Un démarrage en attente de la
        mesure (looper quantifié) compte comme « activée » : un 2e appui l'annule."""
        self._on_enable_toggled(not (self._state.drum_enabled or self._pending_start))
        self._refresh()

    def _on_enable_toggled(self, checked: bool):
        if checked:
            if self._sync is not None and self._sync.request_drum_start(self._start_now):
                self._pending_start = True  # le départ réel (ordre MIDI) viendra à la mesure
                return
            self._start_now()
        else:
            self._pending_start = False
            if self._sync is not None:
                self._sync.drum_stopped()
            self._sender.drum_enable(False)
            self._state.set_drum_enabled(False)

    def _start_now(self):
        self._pending_start = False
        self._sender.drum_enable(True)
        self._state.set_drum_enabled(True)

    def _on_style_changed(self, raw: int):
        """`raw` : CC brut (0-74) ; le numéro affiché est raw + 1."""
        self._sender.drum_set_style(raw)
        self._state.set_drum_style(raw)

    def _on_level_changed(self, percent: int):
        level = protocol.drum_level_from_percent(percent)
        self._sender.drum_set_level(level)
        self._state.set_drum_level(level)

    def _on_eq_changed(self, _value: int):
        # Les 3 curseurs EQ partagent ce handler : MidiSender.drum_set_eq
        # envoie toujours les 3 valeurs courantes ensemble
        bass = self._bass_slider.value()
        middle = self._middle_slider.value()
        treble = self._treble_slider.value()
        self._sender.drum_set_eq(bass, middle, treble)
        self._state.set_drum_eq(bass, middle, treble)

    # --- Réaction à l'état (couvre aussi les changements physiques éventuels) ---

    def _refresh(self):
        self._switch.blockSignals(True)
        self._switch.setChecked(self._state.drum_enabled or self._pending_start)
        self._switch.blockSignals(False)
        if not self._state.drum_enabled and not self._pending_start and self._sync is not None:
            self._sync.drum_stopped()  # coupée depuis l'ampli : plus de repère de phase

        self._tile.set_style(self._state.drum_style, self._state.drum_style in self._state.drum_favorites)
        self._picker.set_current(self._state.drum_style)

        # Volume : ne déplace le curseur que si la valeur CC a vraiment changé (sinon l'arrondi
        # de la conversion le ferait sauter d'un cran à chaque mouvement)
        if protocol.drum_level_from_percent(self._level_slider.value()) != self._state.drum_level:
            self._level_slider.blockSignals(True)
            self._level_slider.setValue(protocol.drum_percent_from_level(self._state.drum_level))
            self._level_slider.blockSignals(False)
        self._level_label.setText(f"{self._level_slider.value()}%")

        for widget, label, value in (
            (self._bass_slider, self._bass_label, self._state.drum_bass),
            (self._middle_slider, self._middle_label, self._state.drum_middle),
            (self._treble_slider, self._treble_label, self._state.drum_treble),
        ):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
            label.setText(str(value))