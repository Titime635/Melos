"""
Composants visuels de la page Partition : boutons à états, sélecteur à deux positions, curseurs fins, fenêtres flottantes.
Tout est dessiné ici avec la palette de ui/theme.py (3 niveaux de gris + couleurs douces) pour que la page soit cohérente.

États d'un bouton : repos, survol, appuyé, actif (coché, teinte de sa couleur), désactivé, focus clavier.
"""

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFontMetrics, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QApplication, QFrame, QGridLayout, QHBoxLayout, QLineEdit, QSizePolicy, QSlider,
                               QStyle, QVBoxLayout, QWidget)

from qfluentwidgets import qconfig

from ui import tab_icons
from ui.theme import mix, pal, qc, rgba

ICON = 18          # taille des icônes dans les boutons


def _tinted(bg: QColor, fg: QColor, t: float) -> QColor:
    return mix(bg, fg, t)


class TabButton(QAbstractButton):
    """Bouton de la page Partition. `kind` : « ghost » (transparent), « soft » (en relief), « accent » (action principale).
    Coché : teinte de `color` (couleur de la palette ou « #rrggbb »), par défaut l'accent."""

    def __init__(self, text: str = "", icon: str | None = None, kind: str = "soft", parent=None, color: str | None = None,
                 height: int = 32, icon_size: int = ICON, align: str = "center", radius: int = 8):
        super().__init__(parent)
        self._radius = radius
        self._icon_name, self._kind, self._color = icon, kind, color
        self._left = align == "left"
        self._h, self._isize = height, icon_size
        self._t = 0.0                                     # 0 = repos, 1 = survol (animé)
        self._kbd_focus = False
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(120)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._set_t)
        self.setText(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    # ---------- configuration ----------
    def setIconName(self, name: str | None):
        if name != self._icon_name:
            self._icon_name = name
            self.updateGeometry()
            self.update()

    def setKind(self, kind: str):
        self._kind = kind
        self.update()

    def setColor(self, color: str | None):
        self._color = color
        self.update()

    def setText(self, text: str):
        super().setText(text)
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        if not self.text():
            return QSize(self._h if self._icon_name else 40, self._h)
        w = QFontMetrics(self.font()).horizontalAdvance(self.text()) + 26
        if self._icon_name:
            w += self._isize + 7
        return QSize(w, self._h)

    def minimumSizeHint(self) -> QSize:
        if self._left:                              # ligne de liste : le texte se rogne plutôt que d'élargir la fenêtre
            return QSize(60, self._h)
        return self.sizeHint()

    # ---------- survol / focus ----------
    def _set_t(self, v):
        self._t = float(v)
        self.update()

    def _animate(self, to: float):
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(to)
        self._anim.start()

    def enterEvent(self, e):
        super().enterEvent(e)
        if self.isEnabled():
            self._animate(1.0)

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self._animate(0.0)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == e.Type.EnabledChange:
            self._t = 0.0
            self.setCursor(Qt.PointingHandCursor if self.isEnabled() else Qt.ArrowCursor)
            self.update()

    def focusInEvent(self, e):
        self._kbd_focus = e.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason)
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e):
        self._kbd_focus = False
        super().focusOutEvent(e)
        self.update()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.click()
            return
        super().keyPressEvent(e)

    # ---------- dessin ----------
    def _colors(self):
        p = pal()
        tint = QColor(p.get(self._color, self._color)) if self._color else QColor(p["accent"])
        surface, raised, hover = QColor(p["surface"]), QColor(p["raised"]), QColor(p["hover"])
        text, muted, faint = QColor(p["text"]), QColor(p["muted"]), QColor(p["faint"])
        border = None
        enabled, down, on = self.isEnabled(), self.isDown(), self.isChecked()
        t = self._t if enabled else 0.0
        if self._kind == "accent":
            base = QColor(p["accent"])
            bg = mix(base, QColor("white" if qc("bg").lightness() < 128 else "black"), 0.10 * t)
            if down:
                bg = mix(base, QColor("black"), 0.12)
            fg = QColor(p["on_accent"])
            if not enabled:
                bg, fg = mix(raised, surface, 0.3), faint
            return bg, fg, border
        if on and enabled:
            bg = QColor(tint)
            bg.setAlphaF(0.20 + 0.08 * t + (0.08 if down else 0))
            fg = mix(tint, text, 0.18)
            border = QColor(tint)
            border.setAlphaF(0.45)
            return bg, fg, border
        rest = raised if self._kind == "soft" else QColor(0, 0, 0, 0)
        target = hover if self._kind == "soft" else raised
        bg = mix(rest, target, t)
        if down and enabled:
            bg = mix(target, QColor("black"), 0.18)
        fg = mix(muted if self._kind == "ghost" else text, text, t) if enabled else faint
        if not enabled and self._kind == "soft":
            bg = mix(raised, surface, 0.45)
        if on and not enabled:
            fg = faint
        return bg, fg, border

    def paintEvent(self, e):
        bg, fg, border = self._colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = self._radius
        p.setPen(QPen(border, 1) if border is not None else Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, radius, radius)
        if self._kbd_focus:
            ring = QColor(pal()["accent"])
            ring.setAlphaF(0.9)
            p.setPen(QPen(ring, 1.6))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), radius - 1, radius - 1)
        text = self.text()
        icon = tab_icons.icon(self._icon_name, fg.name(QColor.HexRgb), self._isize) if self._icon_name else None
        fm = self.fontMetrics()
        gap = 7 if (icon and text) else 0
        iw = self._isize if icon else 0
        avail = self.width() - 12 - iw - gap if text else 0
        shown = fm.elidedText(text, Qt.ElideRight, max(0, avail)) if text else ""
        tw = fm.horizontalAdvance(shown) if shown else 0
        x = 12 if self._left else (self.width() - (iw + gap + tw)) / 2
        if icon:
            icon.paint(p, int(x), (self.height() - iw) // 2, iw, iw)
            x += iw + gap
        if shown:
            p.setPen(fg)
            p.drawText(QRectF(x, 0, tw + 2, self.height()), Qt.AlignVCenter | Qt.AlignLeft, shown)


class _PillItem:
    def __init__(self, pill, key: str, text: str):
        self._pill, self.key, self._text = pill, key, text

    def click(self):
        self._pill._select(self.key)

    def text(self) -> str:
        return self._text


class SegmentedPill(QWidget):
    """Deux (ou plus) positions côte à côte, la position active teintée. API proche de SegmentedWidget."""
    changed = Signal(str)

    def __init__(self, parent=None, height: int = 32):
        super().__init__(parent)
        self._h = height
        self._items: list[tuple[str, str, str | None]] = []     # (clé, texte, icône)
        self._cbs: dict[str, object] = {}
        self._cur = ""
        self._hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        qconfig.themeChanged.connect(lambda *_: self.update())

    @property
    def items(self) -> dict:
        """Positions par clé, chacune avec `.click()` et `.text()` (même usage que sur SegmentedWidget de Fluent)."""
        return {k: _PillItem(self, k, t) for k, t, _ in self._items}

    def _select(self, key: str):
        if key != self._cur:
            self._cur = key
            self.update()
            cb = self._cbs.get(key)
            if cb:
                cb()
            self.changed.emit(key)

    def addItem(self, key: str | None = None, text: str = "", callback=None, icon: str | None = None, *,
                routeKey: str | None = None, onClick=None):
        key = key if key is not None else routeKey            # mêmes noms de paramètres que SegmentedWidget de Fluent
        callback = callback or onClick
        self._items.append((key, text, icon))
        if callback:
            self._cbs[key] = callback
        if not self._cur:
            self._cur = key
        self.updateGeometry()
        self.update()

    def setCurrentItem(self, key: str):
        if key != self._cur:
            self._cur = key
            self.update()

    def currentItem(self) -> str:
        return self._cur

    currentRouteKey = currentItem                              # même nom que sur SegmentedWidget de Fluent

    def _widths(self):
        fm = self.fontMetrics()
        return [fm.horizontalAdvance(t) + 28 + (ICON - 2 + 6 if ic else 0) for _, t, ic in self._items]

    def sizeHint(self) -> QSize:
        return QSize(sum(self._widths()) + 8, self._h)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _index_at(self, x: float) -> int:
        edge = 4
        for i, w in enumerate(self._widths()):
            if edge <= x < edge + w:
                return i
            edge += w
        return -1

    def mouseMoveEvent(self, e):
        i = self._index_at(e.position().x())
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def mousePressEvent(self, e):
        i = self._index_at(e.position().x())
        if e.button() == Qt.LeftButton and 0 <= i < len(self._items):
            self._select(self._items[i][0])

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = pal()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c["raised"]))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)
        x = 4.0
        for i, ((key, text, icon), w) in enumerate(zip(self._items, self._widths())):
            seg = QRectF(x, 4, w, self.height() - 8)
            on = key == self._cur
            if on:
                tint = QColor(c["accent"])
                tint.setAlphaF(0.22)
                p.setBrush(tint)
                p.setPen(QPen(rgba_c(c["accent"], 0.4), 1))
                p.drawRoundedRect(seg.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
            elif i == self._hover:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(c["hover"]))
                p.drawRoundedRect(seg, 6, 6)
            fg = mix(QColor(c["accent"]), QColor(c["text"]), 0.2) if on else QColor(c["text"] if i == self._hover else c["muted"])
            ix = seg.left() + 14
            if icon:
                tab_icons.icon(icon, fg.name(QColor.HexRgb), ICON - 2).paint(p, int(ix), int(seg.center().y() - (ICON - 2) / 2),
                                                                             ICON - 2, ICON - 2)
                ix += ICON - 2 + 6
            p.setPen(fg)
            p.drawText(QRectF(ix, seg.top(), seg.right() - ix, seg.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
            x += w


def rgba_c(color: str, alpha: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(alpha)
    return c


class TabSlider(QSlider):
    """Curseur horizontal fin : rail, partie remplie colorée, poignée ronde (halo au survol). Un clic saute à l'endroit visé."""

    def __init__(self, orientation=Qt.Horizontal, parent=None, fill: str = "accent", groove: int = 4):
        super().__init__(orientation, parent)
        self._fill, self._groove = fill, groove
        self._hot = False
        self._band: tuple[int, int] | None = None          # zone mise en avant (zone de boucle), en unités du curseur
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(22)
        self.setFocusPolicy(Qt.TabFocus)

    def setBand(self, lo: int | None, hi: int | None = None):
        """Met une zone en avant sur le rail (ex. la zone de boucle) ; `None` l'enlève."""
        band = None if lo is None or hi is None or hi <= lo else (int(lo), int(hi))
        if band != self._band:
            self._band = band
            self.update()

    def _span(self):
        m = 8
        return m, max(1, self.width() - 2 * m)

    def _value_at(self, x: float) -> int:
        m, span = self._span()
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), int(round(x - m)), span)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.isEnabled():
            self.setSliderDown(True)
            self.setValue(self._value_at(e.position().x()))
            e.accept()
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.isSliderDown():
            self.setValue(self._value_at(e.position().x()))
            e.accept()
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.isSliderDown():
            self.setSliderDown(False)
            e.accept()
        else:
            super().mouseReleaseEvent(e)

    def enterEvent(self, e):
        self._hot = True
        self.update()

    def leaveEvent(self, e):
        self._hot = False
        self.update()

    def paintEvent(self, e):
        c = pal()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        m, span = self._span()
        rng = self.maximum() - self.minimum()
        frac = (self.value() - self.minimum()) / rng if rng > 0 else 0.0
        x, cy, g = m + span * frac, self.height() / 2, self._groove
        on = self.isEnabled()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c["hover"]))
        p.drawRoundedRect(QRectF(m, cy - g / 2, span, g), g / 2, g / 2)
        fill = QColor(c[self._fill] if self._fill in c else self._fill)
        if not on:
            fill = QColor(c["faint"])
        if self._band and rng > 0:                                  # zone de boucle : rail épaissi, à la couleur d'accent
            x0 = m + span * max(0.0, min(1.0, (self._band[0] - self.minimum()) / rng))
            x1 = m + span * max(0.0, min(1.0, (self._band[1] - self.minimum()) / rng))
            band = QColor(c["accent"])
            band.setAlphaF(0.55 if on else 0.25)
            p.setBrush(band)
            p.drawRoundedRect(QRectF(x0, cy - g * 1.3, max(3.0, x1 - x0), g * 2.6), g * 0.9, g * 0.9)
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(m, cy - g / 2, max(0.0, x - m), g), g / 2, g / 2)
        active = (self._hot or self.isSliderDown() or self.hasFocus()) and on
        if active:
            halo = QColor(fill)
            halo.setAlphaF(0.22)
            p.setBrush(halo)
            p.drawEllipse(QPointF(x, cy), 10.0, 10.0)
        p.setBrush(QColor(c["text"]) if on else QColor(c["faint"]))
        p.drawEllipse(QPointF(x, cy), 6.5 if active else 5.5, 6.5 if active else 5.5)


class PopupCard(QFrame):
    """Fenêtre flottante (se ferme d'un clic à côté) : carte arrondie du niveau « relief », avec bordure."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = pal()
        p.setBrush(QColor(c["raised"]))
        p.setPen(QPen(QColor(c["border"]).lighter(125), 1))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 12, 12)

    def _bounds(self, anchor: QWidget | None, point: QPoint | None = None) -> QRect | None:
        """Zone où la fenêtre doit rester : l'intérieur de la fenêtre de l'application (jamais plus que l'écran)."""
        win = anchor.window() if anchor is not None else (self.parentWidget().window() if self.parentWidget() else None)
        scr = QGuiApplication.screenAt(point) if point is not None else (anchor.screen() if anchor is not None else None)
        r = scr.availableGeometry() if scr is not None else None
        if win is not None and win is not self:
            w = QRect(win.mapToGlobal(QPoint(0, 0)), win.size())
            r = w if r is None else w.intersected(r)
        return r

    def _clamp(self, x: int, y: int, r: QRect | None) -> tuple[int, int]:
        if r is None:
            return x, y
        x = max(r.left() + 6, min(x, r.right() - self.width() - 5))
        y = max(r.top() + 6, min(y, r.bottom() - self.height() - 5))
        return x, y

    def place_at(self, global_pos: QPoint):
        """Coin haut-gauche au point donné (clic droit), ramenée dans la fenêtre de l'application."""
        self.adjustSize()
        self.move(*self._clamp(global_pos.x(), global_pos.y(), self._bounds(None, global_pos)))

    def place_near(self, widget: QWidget, above: bool = False, align_right: bool = False):
        """Sous (ou au-dessus de) `widget`, aligné à gauche (ou à droite), ramené dans la fenêtre de l'application."""
        self.adjustSize()
        r = self._bounds(widget)
        top_left = widget.mapToGlobal(widget.rect().topLeft())
        below = widget.mapToGlobal(widget.rect().bottomLeft()).y() + 6
        above_y = top_left.y() - self.height() - 6
        x = top_left.x() + (widget.width() - self.width() if align_right else 0)
        y = above_y if above else below
        if r is not None:                                   # le côté choisi ne tient pas : l'autre côté, sinon on reste dans la fenêtre
            fits = lambda yy: yy >= r.top() + 6 and yy + self.height() <= r.bottom() - 5
            if not fits(y) and fits(above_y if not above else below):
                y = above_y if not above else below
        self.move(*self._clamp(x, y, r))


class ChoicePopup(PopupCard):
    """Grille de puces à choisir (ex. vitesses de lecture)."""
    chosen = Signal(int)

    def __init__(self, labels: list[str], columns: int = 4, parent=None):
        super().__init__(parent)
        lay = QGridLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)
        self._btns: list[TabButton] = []
        for i, text in enumerate(labels):
            b = TabButton(text, None, "soft", self, height=30)
            b.setCheckable(True)
            b.setFixedWidth(58)
            b.clicked.connect(lambda _=False, i=i: self._pick(i))
            lay.addWidget(b, i // columns, i % columns)
            self._btns.append(b)

    def _pick(self, i: int):
        self.close()
        self.chosen.emit(i)

    def popup_for(self, widget: QWidget, current: int):
        for i, b in enumerate(self._btns):
            b.setChecked(i == current)
        self.place_near(widget, above=True)
        self.show()


class ChoiceModel(QObject):
    """Liste de choix sans interface, avec l'API d'un QComboBox (addItem / clear / currentData / findData /
    currentIndexChanged…) : le code existant garde ses appels, l'affichage est géré ailleurs (fenêtre flottante, bouton)."""
    currentIndexChanged = Signal(int)
    changed = Signal()                     # la liste ou la sélection a changé (pour redessiner)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[tuple[str, object]] = []
        self._cur = -1

    def clear(self):
        self._items, self._cur = [], -1
        self.changed.emit()

    def addItem(self, text: str, userData=None):
        self._items.append((text, userData))
        if self._cur < 0:
            self._cur = 0
        self.changed.emit()

    def count(self) -> int:
        return len(self._items)

    def currentIndex(self) -> int:
        return self._cur

    def setCurrentIndex(self, i: int):
        i = i if 0 <= i < len(self._items) else -1
        if i != self._cur:
            self._cur = i
            self.currentIndexChanged.emit(i)
        self.changed.emit()

    def currentData(self):
        return self._items[self._cur][1] if 0 <= self._cur < len(self._items) else None

    def currentText(self) -> str:
        return self._items[self._cur][0] if 0 <= self._cur < len(self._items) else ""

    def itemData(self, i: int):
        return self._items[i][1] if 0 <= i < len(self._items) else None

    def itemText(self, i: int) -> str:
        return self._items[i][0] if 0 <= i < len(self._items) else ""

    def findData(self, data) -> int:
        return next((i for i, (_, d) in enumerate(self._items) if d == data), -1)


class SearchField(QLineEdit):
    """Champ de recherche / lien : laisse passer flèches, Entrée et Échap à la liste de résultats ouverte (cf. song_search)."""
    move = Signal(int)                        # -1 = haut, +1 = bas
    accept = Signal()                         # Entrée sur un résultat surligné
    dismiss = Signal()                        # Échap ou perte du focus

    def __init__(self, parent=None):
        super().__init__(parent)
        self.popup_open = False
        self.setFrame(False)
        self._clear = self.addAction(tab_icons.icon("close", pal()["muted"], 14), QLineEdit.TrailingPosition)
        self._clear.setToolTip("Effacer")
        self._clear.triggered.connect(self.clear)
        self._clear.setVisible(False)
        self.textChanged.connect(lambda t: self._clear.setVisible(bool(t)))
        self.apply_theme()

    def apply_theme(self):
        c = pal()
        self.setStyleSheet(f"QLineEdit{{background:transparent;border:none;color:{c['text']};font-size:14px;"
                           f"selection-background-color:{rgba(c['accent'], 0.45)};selection-color:{c['text']}}}")
        self._clear.setIcon(tab_icons.icon("close", c["muted"], 14))

    def keyPressEvent(self, ev):
        if self.popup_open:
            if ev.key() in (Qt.Key_Down, Qt.Key_Up):
                self.move.emit(1 if ev.key() == Qt.Key_Down else -1)
                return
            if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.accept.emit()
                return
        if ev.key() == Qt.Key_Escape:
            self.dismiss.emit()
            return
        super().keyPressEvent(ev)

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        self.dismiss.emit()


class TitleField(QWidget):
    """Affiche le morceau (« Titre » et « Artiste · état ») ; un clic le change en champ de recherche / lien."""
    editing_changed = Signal(bool)

    def __init__(self, parent=None, height: int = 44):
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(140)
        self.setCursor(Qt.IBeamCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.title, self.artist, self._status = "", "", ""
        self.placeholder = "Rechercher un morceau ou coller un lien Songsterr"
        self.editing = False
        self._t = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(120)
        self._anim.valueChanged.connect(lambda v: (setattr(self, "_t", float(v)), self.update()))
        self.edit = SearchField(self)
        self.edit.setPlaceholderText(self.placeholder)
        self.edit.hide()
        self.edit.setFixedHeight(height - 8)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(40, 4, 8, 4)
        lay.addWidget(self.edit)

    # ---------- contenu ----------
    def set_track(self, title: str, artist: str):
        self.title, self.artist = title, artist
        self.update()

    def set_full(self, status: str):                  # remplace l'ancien libellé d'état (messages, erreurs)
        self._status = status
        self.setToolTip(status if status and not self.editing else "")
        self.update()

    def start_edit(self, select_all: bool = True):
        if self.editing:
            return
        self.editing = True
        self.edit.show()
        self.edit.setFocus(Qt.MouseFocusReason)
        if select_all:
            self.edit.selectAll()
        self.editing_changed.emit(True)
        self.update()

    def finish_edit(self):
        if not self.editing:
            return
        self.editing = False
        self.edit.hide()
        self.editing_changed.emit(False)
        self.update()

    # ---------- interaction ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and not self.editing:
            self.start_edit()
        super().mousePressEvent(e)

    def enterEvent(self, e):
        self._anim.stop(); self._anim.setStartValue(self._t); self._anim.setEndValue(1.0); self._anim.start()

    def leaveEvent(self, e):
        self._anim.stop(); self._anim.setStartValue(self._t); self._anim.setEndValue(0.0); self._anim.start()

    def paintEvent(self, e):
        c = pal()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        focus = self.editing
        bg = mix(QColor(c["raised"]), QColor(c["hover"]), 0.0 if focus else self._t * 0.6)
        p.setBrush(bg)
        p.setPen(QPen(rgba_c(c["accent"], 0.7), 1.2) if focus else QPen(QColor(c["border"]), 1))
        p.drawRoundedRect(r, 10, 10)
        p.drawPixmap(14, (self.height() - 18) // 2, tab_icons.pixmap("search", c["accent"] if focus else c["muted"], 18))
        if focus:
            return
        x0, w = 40, self.width() - 40 - 12
        fm = self.fontMetrics()
        if self.title:
            f = self.font(); f.setPointSizeF(10.5); f.setWeight(f.Weight.DemiBold)
            p.setFont(f)
            p.setPen(QColor(c["text"]))
            title = fm.elidedText(self.title, Qt.ElideRight, w)
            p.drawText(QRectF(x0, 5, w, 19), Qt.AlignVCenter | Qt.AlignLeft, QFontMetrics(f).elidedText(self.title, Qt.ElideRight, w))
            f2 = self.font(); f2.setPointSizeF(8.5)
            p.setFont(f2)
            p.setPen(QColor(c["muted"]))
            sub = " · ".join(x for x in (self.artist, self._status) if x)
            p.drawText(QRectF(x0, 23, w, 16), Qt.AlignVCenter | Qt.AlignLeft, QFontMetrics(f2).elidedText(sub, Qt.ElideRight, w))
        else:
            f = self.font(); f.setPointSizeF(10)
            p.setFont(f)
            p.setPen(QColor(c["muted"]))
            p.drawText(QRectF(x0, 0, w, self.height()), Qt.AlignVCenter | Qt.AlignLeft,
                       QFontMetrics(f).elidedText(self._status or self.placeholder, Qt.ElideRight, w))


# ---------------------------------------------------------------------------------------------------------------------
# Menu contextuel (clic droit sur la partition) : carte du niveau « relief », lignes à états (repos / survol / désactivé)
# ---------------------------------------------------------------------------------------------------------------------
class _MenuRow(QAbstractButton):
    def __init__(self, icon: str | None, text: str, hint: str = "", color: str | None = None, parent=None):
        super().__init__(parent)
        self._icon, self._hint, self._color = icon, hint, color
        self.setText(text)
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedHeight(34)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, e):
        c, on = pal(), self.isEnabled()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 1, -2, -1)
        if on and (self._hover or self.isDown()):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c["hover"]) if not self.isDown() else mix(QColor(c["hover"]), QColor(c["text"]), 0.12))
            p.drawRoundedRect(r, 8, 8)
        tint = QColor(self._color or (c["text"] if on else c["faint"]))
        if not on:
            tint = QColor(c["faint"])
        x = 10
        if self._icon:
            p.drawPixmap(x, (self.height() - 18) // 2, tab_icons.pixmap(self._icon, tint.name(), 18))
            x += 28
        p.setPen(QColor(c["text"]) if on else QColor(c["faint"]))
        right = self.width() - 10
        if self._hint:
            p.setPen(QColor(c["muted"]) if on else QColor(c["faint"]))
            hw = self.fontMetrics().horizontalAdvance(self._hint)
            p.drawText(QRectF(right - hw, 0, hw, self.height()), Qt.AlignVCenter | Qt.AlignRight, self._hint)
            right -= hw + 10
            p.setPen(QColor(c["text"]) if on else QColor(c["faint"]))
        txt = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, max(10, right - x))
        p.drawText(QRectF(x, 0, max(10, right - x), self.height()), Qt.AlignVCenter | Qt.AlignLeft, txt)


class ScoreMenu(PopupCard):
    """Menu à la souris : un titre (« Mesure 12 »), des lignes avec icône, des séparateurs. Se ferme au clic, puis l'action s'exécute."""

    def __init__(self, parent=None, width: int = 270):
        super().__init__(parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(6, 8, 6, 8)
        self._lay.setSpacing(1)
        self._w = width
        self._title = None
        self.setFixedWidth(width)

    def set_title(self, text: str):
        from ui.track_list import _Elided
        if self._title is None:
            self._title = _Elided(type("CaptionLabel", (), {}), text, self)
            self._title.setContentsMargins(0, 0, 0, 0)
            self._lay.insertWidget(0, self._title)
        else:
            self._title.setText(text)

    def add_item(self, icon: str | None, text: str, callback, enabled: bool = True, hint: str = "", color: str | None = None):
        row = _MenuRow(icon, text, hint, color, self)
        row.setEnabled(enabled)
        row.clicked.connect(lambda: (self.close(), callback()))
        self._lay.addWidget(row)
        return row

    def add_separator(self):
        sep = QFrame(self)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{pal()['border']}")
        self._lay.addSpacing(3)
        self._lay.addWidget(sep)
        self._lay.addSpacing(3)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    def popup_at(self, global_pos: QPoint):
        self.adjustSize()
        self.place_at(global_pos)
        self.show()


# ---------------------------------------------------------------------------------------------------------------------
# Glisser-déposer maison (pas de QDrag) : un widget « source » + une pastille qui suit la souris. Le widget qui a reçu le
# clic garde la souris même hors de sa fenêtre ; l'appelant reçoit les positions globales et décide de la cible (ici :
# une mesure de la partition, dans la page web).
# ---------------------------------------------------------------------------------------------------------------------
class DragGhost(QWidget):
    def __init__(self, text: str, color: str):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self._text, self._color = text, QColor(color)
        f = self.font()
        f.setWeight(f.Weight.DemiBold)
        self.setFont(f)
        self.resize(QFontMetrics(f).horizontalAdvance(text) + 36, 28)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bg = QColor(self._color)
        bg.setAlphaF(0.30)
        base = QColor(pal()["raised"])
        p.setBrush(base)
        p.setPen(Qt.NoPen)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.drawRoundedRect(r, 14, 14)
        p.setBrush(bg)
        p.setPen(QPen(self._color, 1.4))
        p.drawRoundedRect(r, 14, 14)
        p.setBrush(self._color)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(14, self.height() / 2), 4, 4)
        p.setPen(QColor(pal()["text"]))
        p.drawText(QRectF(24, 0, self.width() - 28, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self._text)

    def follow(self, global_pos: QPoint):
        self.move(global_pos + QPoint(14, 12))


class DragSource(QObject):
    """Installe le glisser-déposer sur `widget` (sans lui voler ses clics : un clic simple le traverse, y compris pour un bouton).

    started(pos) au premier mouvement de plus de startDragDistance ; moved(pos) ; dropped(pos) au relâchement ; cancelled()
    si Échap. `clicked` est émis pour un clic sans glissement (utile pour les lignes de liste qui ne sont pas des boutons)."""
    started = Signal(QPoint)
    moved = Signal(QPoint)
    dropped = Signal(QPoint)
    cancelled = Signal()
    clicked = Signal()

    def __init__(self, widget: QWidget, parent=None):
        super().__init__(parent or widget)
        self._w = widget
        self._press: QPoint | None = None
        self.dragging = False
        widget.installEventFilter(self)

    def cancel(self):
        if self.dragging:
            self.dragging = False
            self.cancelled.emit()
        self._press = None

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
            self._press, self.dragging = ev.globalPosition().toPoint(), False
        elif t == QEvent.MouseMove and self._press is not None and (ev.buttons() & Qt.LeftButton):
            pos = ev.globalPosition().toPoint()
            if not self.dragging and (pos - self._press).manhattanLength() > QApplication.startDragDistance():
                self.dragging = True
                self.started.emit(pos)
            if self.dragging:
                self.moved.emit(pos)
                return True
        elif t == QEvent.MouseButtonRelease and ev.button() == Qt.LeftButton and self._press is not None:
            was, self._press = self.dragging, None
            self.dragging = False
            if was:
                self.dropped.emit(ev.globalPosition().toPoint())
                return True                                  # le bouton ne doit pas croire à un clic
            self.clicked.emit()
        return False