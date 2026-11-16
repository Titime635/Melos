"""
Palette d'outils d'édition de la partition (équivalent de celle de Songsterr) : des boutons rangés par onglet (Temps, Notes,
Mesure, Édition), grisés quand ils ne s'appliquent pas à la sélection, allumés quand l'effet est déjà posé. Une recherche
(loupe) filtre les outils de tous les onglets. Jamais de barre de défilement : les boutons passent à la ligne et la hauteur
du panneau s'ajuste au plus grand onglet.

Le panneau ne fait que montrer et relayer les clics ; ce que fait chaque outil est dans tabs/score_tools.py, l'application
sur la partition dans ui/tab_editing.py.
"""

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from tabs import score_tools as st
from ui.tab_widgets import SearchField, SegmentedPill
from ui.theme import card_style, pal

H = 32            # hauteur d'un bouton
GAP = 6           # espace entre deux boutons
GROUP = 12        # espace de plus avant un nouveau groupe
MORE_W = 16       # largeur du segment « ⋮ »


class ToolButton(QWidget):
    """Un outil : texte court, bulle d'aide, état grisé / allumé, segment « ⋮ » s'il a des variantes."""
    clicked = Signal(str)
    more_clicked = Signal(str, QPoint)

    def __init__(self, tool: st.Tool, parent=None):
        super().__init__(parent)
        self.tool = tool
        self.active, self._enabled, self._hover = False, True, None
        self.setMouseTracking(True)
        self.setToolTip(tool.tip)
        self.setCursor(Qt.PointingHandCursor)
        f = self.font()
        f.setPointSizeF(9.5)
        f.setBold(True)
        self.setFont(f)
        text = tool.label + (" ▾" if tool.menu_only else "")
        self.main_w = max(36, QFontMetrics(f).horizontalAdvance(text) + 16)
        self.more_w = MORE_W if tool.more and not tool.menu_only else 0
        self._text = text
        self.setFixedSize(self.main_w + self.more_w, H)

    def set_state(self, enabled: bool, active: bool):
        if (enabled, active) != (self._enabled, self.active):
            self._enabled, self.active = enabled, active
            self.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
            self.update()

    def _part(self, x: float) -> str:
        return "more" if self.more_w and x >= self.main_w else "main"

    def mouseMoveEvent(self, ev):
        part = self._part(ev.position().x())
        if part != self._hover:
            self._hover = part
            self.update()

    def leaveEvent(self, ev):
        self._hover = None
        self.update()

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton or not self._enabled:
            return
        if self._part(ev.position().x()) == "more" or self.tool.menu_only:
            self.more_clicked.emit(self.tool.id, self.mapToGlobal(QPoint(0, self.height() + 2)))
        else:
            self.clicked.emit(self.tool.id)

    def paintEvent(self, ev):
        c = pal()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self._enabled
        base = QColor(c["amber"]) if self.active and on else QColor(c["raised"])
        fg = QColor(c["on_accent"]) if self.active and on else QColor(c["text"] if on else c["faint"])
        parts = (("main", QRectF(0, 0, self.main_w, H)), ("more", QRectF(self.main_w, 0, self.more_w, H)))
        for name, r in parts:
            if r.width() <= 0:
                continue
            col = QColor(base)
            if on and self._hover == name and not self.active:
                col = QColor(c["hover"])
            if not on:
                col.setAlphaF(0.55)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            r2 = r.adjusted(0, 0, -1 if name == "main" and self.more_w else 0, 0)
            p.drawRoundedRect(r2, 7, 7)
        if self.more_w:                                           # raccord plat entre les deux segments
            p.setBrush(QColor(c["amber"]) if self.active and on else QColor(c["raised"]))
        p.setPen(fg)
        p.setFont(self.font())
        p.drawText(QRectF(0, 0, self.main_w, H), Qt.AlignCenter, self._text)
        if self.more_w:
            p.setPen(QColor(c["muted"] if on else c["faint"]))
            p.drawText(QRectF(self.main_w, 0, self.more_w, H), Qt.AlignCenter, "⋮")


class PalettePanel(QFrame):
    """Le panneau : onglets + voix + recherche, puis les boutons de l'onglet (ou les résultats de la recherche)."""
    tool_clicked = Signal(str)
    more_requested = Signal(str, QPoint)
    voice_chosen = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("palette")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 10)
        lay.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(10)
        self.tabs = SegmentedPill(self, height=30)
        for key, text in st.TABS:
            self.tabs.addItem(key, text, lambda k=key: self._tab(k))
        self.tabs.setCurrentItem("temps")
        head.addWidget(self.tabs)
        self.voice_label = QLabel("Voix", self)
        head.addWidget(self.voice_label)
        self.voices = SegmentedPill(self, height=30)
        for i in range(st.VOICES):
            self.voices.addItem(str(i), str(i + 1), lambda i=i: self.voice_chosen.emit(i))
        self.voices.setCurrentItem("0")
        self.voices.setToolTip("Voix éditée : la voix 1 est la mélodie principale, les voix 2 à 4 servent aux notes superposées")
        head.addWidget(self.voices)
        head.addStretch(1)
        self.box = QFrame(self)
        self.box.setFixedSize(210, 30)
        bl = QHBoxLayout(self.box)
        bl.setContentsMargins(10, 0, 8, 0)
        self.search = SearchField(self.box)
        self.search.setPlaceholderText("Chercher un outil…")
        self.search.textChanged.connect(lambda _t: self.relayout())
        bl.addWidget(self.search)
        head.addWidget(self.box)
        lay.addLayout(head)
        self.body = QWidget(self)
        lay.addWidget(self.body)
        self._tab_key = "temps"
        self.buttons: dict[str, ToolButton] = {}
        for t in st.TOOLS:
            b = ToolButton(t, self.body)
            b.clicked.connect(self.tool_clicked)
            b.more_clicked.connect(self.more_requested)
            self.buttons[t.id] = b
        self.apply_theme()

    def apply_theme(self):
        c = pal()
        self.setStyleSheet(card_style("#palette", radius=12))
        self.voice_label.setStyleSheet(f"color:{c['muted']};font-size:12px;background:transparent")
        self.box.setStyleSheet(f"QFrame{{background:{c['soft'] if 'soft' in c else c['raised']};border-radius:8px}}")
        self.search.apply_theme()
        for b in self.buttons.values():
            b.update()

    def set_voice(self, v: int):
        self.voices.setCurrentItem(str(v))

    def _tab(self, key: str):
        self._tab_key = key
        self.relayout()

    def _shown(self) -> list[st.Tool]:
        q = self.search.text().strip()
        if q:
            return st.search(q)
        return [t for t in st.TOOLS if t.tab == self._tab_key]

    def _flow(self, tools: list[st.Tool], width: int, place: bool) -> int:
        """Range les boutons de `tools` à la ligne dans `width` ; renvoie le nombre de lignes."""
        x, y, rows = 0, 0, 1
        for t in tools:
            b = self.buttons[t.id]
            gap = GROUP if (t.gap and x > 0) else 0
            if x > 0 and x + gap + b.width() > width:
                x, y, rows, gap = 0, y + H + GAP, rows + 1, 0
            x += gap
            if place:
                b.move(x, y)
            x += b.width() + GAP
        return rows

    def rows_needed(self, width: int) -> int:
        return max(self._flow([t for t in st.TOOLS if t.tab == key], width, False) for key, _ in st.TABS)

    def relayout(self):
        w = max(200, self.body.width() or (self.width() - 24))
        shown = self._shown()
        ids = {t.id for t in shown}
        for tid, b in self.buttons.items():
            b.setVisible(tid in ids)
        rows = max(self._flow(shown, w, True), self.rows_needed(w))
        h = rows * H + (rows - 1) * GAP
        if self.body.height() != h:
            self.body.setFixedHeight(h)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.relayout()

    def showEvent(self, ev):
        super().showEvent(ev)
        self.relayout()

    def update_states(self, fn):
        """`fn(tool) -> (utilisable, allumé)` pour chaque bouton."""
        for t in st.TOOLS:
            self.buttons[t.id].set_state(*fn(t))
