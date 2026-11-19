"""
Éléments visuels du looper (cf ui/loop_panel.py) et du module Tempo (cf ui/tempo_panel.py) :
touches de transport colorées, barre de position avec temps et mesures, voyants de temps,
ligne de piste (muet / volume / suppression).

Tout est dessiné avec des couleurs d'accent fixes (lisibles en thème clair comme sombre) et
des fonds semi-transparents, pour ne pas dépendre du thème.
"""

import math

from PySide6.QtCore import Qt, Signal, QPointF, QRectF, QSize, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen, QPolygonF, QRadialGradient
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget
from qfluentwidgets import BodyLabel, FluentIcon, ToggleButton, TransparentToolButton, qconfig

from ui import icons
from ui.theme import MODULE_COLORS, ON_SOFT, STATE_COLORS as _STATES, accent_fg, pal, qc
from ui.widgets import NoWheelSlider

# couleurs d'état : palette douce commune (ui/theme.py)
REC = _STATES["rec"]
OVERDUB = _STATES["overdub"]
PLAY = _STATES["play"]
WAIT = _STATES["wait"]
NEUTRAL = _STATES["neutral"]
ACCENT = MODULE_COLORS["loop"]

STATE_COLORS = {
    "idle": NEUTRAL, "counting_in": WAIT, "recording": REC, "playing": PLAY,
    "overdubbing": OVERDUB, "stopped": NEUTRAL,
}


def _rgba(color: str, alpha: float) -> str:
    c = QColor(color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


class TransportButton(QPushButton):
    """Grosse touche de transport : fond teinté de sa couleur, plein quand l'action est en cours."""

    def __init__(self, kind: str, text: str, color: str, parent=None):
        super().__init__(parent)
        self._kind, self._label, self._color = kind, text, color
        self._active = False
        self._current = False          # c'est l'état en cours du looper : bouton teinté + halo qui pulse doucement
        self._pulse = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setKeyValueAt(0.5, 1.0)
        self._anim.setEndValue(0.0)
        self._anim.setDuration(1500)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._on_pulse)
        self._compact = False
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(40)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setIconSize(QSize(20, 20))
        self.set_content(kind, text)
        qconfig.themeChanged.connect(lambda *_: self._restyle())

    def set_content(self, kind: str | None = None, text: str | None = None, active: bool | None = None):
        if kind is not None:
            self._kind = kind
        if text is not None:
            self._label = text
        if active is not None:
            self._active = active
        self._restyle()

    def set_current(self, current: bool):
        """Marque le bouton de l'état en cours (Rec / Overdub / Play) : fond plus marqué et halo qui pulse."""
        if current == self._current:
            return
        self._current = current
        if current and self.isVisible():
            self._anim.start()
        else:
            self._anim.stop()
            self._pulse = 0.0
        self._restyle()
        self.update()

    def _on_pulse(self, value):
        self._pulse = float(value)
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if self._current and self._anim.state() != QVariantAnimation.Running:
            self._anim.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._anim.pause() if self._anim.state() == QVariantAnimation.Running else None

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._current or not self.isEnabled():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._active:                    # bouton plein (Stop pendant l'enregistrement) : reflet blanc qui respire
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, int(46 * self._pulse)))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 8, 8)
            p.end()
            return
        c = QColor(self._color)
        c.setAlphaF(0.35 + 0.5 * self._pulse)
        pen = QPen(c)
        pen.setWidthF(2.2)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1.1, 1.1, -1.1, -1.1), 8, 8)
        p.end()

    def set_compact(self, compact: bool):
        self._compact = compact
        self._restyle()

    def setEnabled(self, enabled: bool):
        super().setEnabled(enabled)
        self._restyle()

    def _restyle(self):
        fg = ON_SOFT if self._active else self._color
        self.setIcon(icons.transport_icon(self._kind, fg if self.isEnabled() else NEUTRAL))
        self.setText("" if self._compact else self._label)
        self.setToolTip(self._label)
        p = pal()
        text_color = ON_SOFT if self._active else p["text"]
        if self._active:
            bg, border = self._color, self._color
        elif self._current:
            bg, border = _rgba(self._color, 0.26), _rgba(self._color, 0.7)
        else:
            bg, border = _rgba(self._color, 0.14), _rgba(self._color, 0.45)
        self.setStyleSheet(
            f"QPushButton {{ background: {bg}; border: 1px solid {border}; border-radius: 8px;"
            f" color: {text_color}; font-weight: 600; padding: 4px 8px; }}"
            f"QPushButton:hover {{ background: {self._color if self._active else _rgba(self._color, 0.28)}; }}"
            f"QPushButton:disabled {{ background: {p['raised']}; border: 1px solid {p['border']};"
            f" color: {p['faint']}; }}"
        )


class PositionBar(QWidget):
    """Barre de position : la boucle (ou la mesure en cours) découpée en temps, avec un curseur,
    le temps courant en grand ("2.3" = mesure 2, temps 3) et l'action en attente."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(36)
        self.setMaximumHeight(54)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._snap = {"state": "idle", "pending": "", "beats": 4, "bars": 0, "frac": 0.0, "beat": -1,
                      "bar": 0, "active": False}
        self._pending_text = ""

    def set_snapshot(self, snap: dict, pending_text: str = ""):
        if snap != self._snap or pending_text != self._pending_text:
            self._snap, self._pending_text = snap, pending_text
            self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        snap = self._snap
        w, h = self.width(), self.height()
        rect = QRectF(0.5, 0.5, w - 1, h - 1)
        color = QColor(STATE_COLORS.get(snap["state"], NEUTRAL))
        fg = qc("text")

        p.setPen(Qt.NoPen)
        p.setBrush(qc("raised"))
        p.drawRoundedRect(rect, 7, 7)

        bars, beats = snap["bars"], max(1, snap["beats"])
        if snap["active"] or snap["state"] == "stopped":
            fill = QColor(color)
            fill.setAlpha(92)
            p.setBrush(fill)
            p.drawRoundedRect(QRectF(0.5, 0.5, max(0.0, (w - 1) * snap["frac"]), h - 1), 7, 7)

        # Graduations : un trait par temps, plus long en début de mesure
        total = max(1, bars) * beats
        for i in range(1, total):
            x = w * i / total
            strong = i % beats == 0
            pen = QPen(qc("faint") if strong else qc("border"))
            pen.setWidthF(1.6 if strong else 1.0)
            p.setPen(pen)
            p.drawLine(int(x), int(h * (0.18 if strong else 0.55)), int(x), h - 4)

        if snap["active"]:
            x = (w - 1) * snap["frac"]
            pen = QPen(color)
            pen.setWidthF(3.2)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawLine(int(x), 4, int(x), h - 4)

        font = QFont(self.font())
        font.setBold(True)
        font.setPointSizeF(max(9.0, h * 0.30))
        p.setFont(font)
        p.setPen(fg)
        if snap["beat"] >= 0 and (snap["active"] or snap["state"] == "stopped"):
            p.drawText(QRectF(10, 0, w * 0.4, h), Qt.AlignVCenter | Qt.AlignLeft,
                       f"{snap['bar'] + 1}.{snap['beat'] + 1}")
        small = QFont(self.font())
        small.setPointSizeF(max(8.0, h * 0.24))
        p.setFont(small)
        if self._pending_text:
            p.setPen(QColor(WAIT))
            p.drawText(QRectF(0, 0, w - 10, h), Qt.AlignVCenter | Qt.AlignRight, self._pending_text)
        elif bars:
            p.setPen(qc("muted"))
            p.drawText(QRectF(0, 0, w - 10, h), Qt.AlignVCenter | Qt.AlignRight,
                       f"{bars} mesure{'s' if bars > 1 else ''}")
        p.end()


class BeatDots(QWidget):
    """Une pastille par temps de la mesure. Le temps courant s'allume d'un coup puis s'éteint en fondu
    jusqu'au suivant, avec un halo ; le temps 1 est plus gros et d'une autre couleur."""

    FIRST = QColor(MODULE_COLORS["tempo"])       # 1er temps : la couleur du module Tempo
    OTHER = QColor("#5b9bff")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(30)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._beats, self._beat, self._active, self._phase = 4, -1, False, 0.0

    def sizeHint(self) -> QSize:
        return QSize(120, 30)

    def set_state(self, beats: int, beat: int, active: bool, phase: float = 0.0):
        """`phase` : avancement dans le temps courant (0 = le temps vient de tomber, 1 = le suivant arrive)."""
        phase = round(phase, 2)
        if (beats, beat, active, phase) != (self._beats, self._beat, self._active, self._phase):
            self._beats, self._beat, self._active, self._phase = beats, beat, active, phase
            self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = max(1, self._beats)
        gap = 8.0
        size = min(20.0, (self.width() - 8 - (n - 1) * gap) / (n + 0.25), self.height() - 6)
        if size < 5:
            p.end()
            return
        total = n * size + 0.25 * size + (n - 1) * gap
        x = (self.width() - total) / 2
        cy = self.height() / 2
        for i in range(n):
            first = i == 0
            d = size * (1.25 if first else 1.0)
            r = d / 2
            cx = x + r
            x += d + gap
            color = QColor(self.FIRST if first else self.OTHER)
            lit = self._active and i == self._beat
            level = (1.0 - self._phase) ** 1.5 if lit else 0.0   # 1 au coup, tombe vers 0
            if lit:
                halo = QRadialGradient(QPointF(cx, cy), r * 2.3)
                c0 = QColor(color); c0.setAlpha(int(150 * level))
                c1 = QColor(color); c1.setAlpha(0)
                halo.setColorAt(0.35, c0)
                halo.setColorAt(1.0, c1)
                p.setPen(Qt.NoPen)
                p.setBrush(halo)
                p.drawEllipse(QPointF(cx, cy), r * 2.3, r * 2.3)
            ring = QColor(color); ring.setAlpha(int(110 + 145 * level))
            fill = QColor(color); fill.setAlpha(int(34 + 221 * level))
            pen = QPen(ring)
            pen.setWidthF(1.6)
            p.setPen(pen)
            p.setBrush(fill)
            grow = 1.0 + 0.12 * level
            p.drawEllipse(QPointF(cx, cy), (r - 0.8) * grow, (r - 0.8) * grow)
        p.end()


class PillButton(QPushButton):
    """Bouton en gélule dessiné à la main : fond teinté, plein quand il est actif, avec une petite icône
    animable. Types : "metronome" (balancier qui bat avec le tempo), "countin" (une pastille par temps du
    décompte, allumées au fil du décompte), "tap" (flash à chaque appui), "" (texte seul)."""

    def __init__(self, text: str, color: str, kind: str = "", checkable: bool = False,
                 on_text: str = ON_SOFT, parent=None):
        super().__init__(parent)
        self._text, self._color, self._kind, self._on_text = text, QColor(color), kind, QColor(on_text)
        self._swing = 0          # -1 / 0 / 1 : côté du balancier
        self._marker = -1        # pastilles allumées (décompte) ; -1 = repos
        self._dots = 4
        self._flash = 0.0
        self.setCheckable(checkable)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(36)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.setDuration(260)
        self._anim.valueChanged.connect(self._on_flash)
        self.setText(text)

    # --- Animations pilotées de l'extérieur ---

    def set_swing(self, side: int):
        if side != self._swing:
            self._swing = side
            self.update()

    def set_marker(self, lit: int, total: int = 4):
        if (lit, total) != (self._marker, self._dots):
            self._marker, self._dots = lit, max(1, total)
            self.update()

    def flash(self):
        self._anim.stop()
        self._anim.start()

    def _on_flash(self, value):
        self._flash = float(value)
        self.update()

    def _label_font(self) -> QFont:
        font = QFont(self.font())
        font.setBold(True)
        if self._kind == "tap":
            font.setLetterSpacing(QFont.AbsoluteSpacing, 2.0)
        return font

    def _text_width(self, font: QFont) -> float:
        """Largeur réelle du libellé (gras + espacement des lettres) : sinon il est rogné."""
        spacing = font.letterSpacing() if font.letterSpacingType() == QFont.AbsoluteSpacing else 0.0
        if not self._text:
            return 0.0
        return QFontMetricsF(font).horizontalAdvance(self._text) + spacing * len(self._text) + 4

    def sizeHint(self) -> QSize:
        icon = {"metronome": 22, "countin": 4 * 8 + 6, "tap": 0}.get(self._kind, 0)
        return QSize(int(self._text_width(self._label_font())) + icon + 36, 38)

    # --- Dessin ---

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = rect.height() / 2
        col = QColor(self._color)
        enabled = self.isEnabled()
        on = self.isChecked() or self._flash > 0.0
        hover = self.underMouse() and enabled
        theme_fg = qc("text")

        if not enabled:
            bg, border, fg = qc("raised"), qc("border"), qc("faint")
        elif self.isChecked():       # actif : teinte douce de la couleur, comme les boutons de la partition
            bg, border, fg = QColor(col), QColor(col), accent_fg(col)
            bg.setAlpha(hover and 78 or 56); border.setAlpha(115)
        else:
            bg, border, fg = qc("hover" if hover else "raised"), qc("border"), theme_fg
        if enabled and self._flash > 0.0 and not self.isChecked():
            bg = QColor(col); bg.setAlpha(int(40 + 130 * self._flash))
            border = QColor(col); border.setAlpha(115)
        if self.isDown() and enabled:
            bg = bg.darker(112)

        pen = QPen(border); pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(bg)
        p.drawRoundedRect(rect, min(radius, 10), min(radius, 10))

        icon_w = {"metronome": 18.0, "countin": 4 * 8.0 + 2}.get(self._kind, 0.0)
        if self._kind == "countin":
            icon_w = self._dots * 8.0 + 2
        font = self._label_font()
        p.setFont(font)
        tw = self._text_width(font)
        gap = 8.0 if icon_w and self._text else 0.0
        total = icon_w + gap + tw
        x0 = rect.center().x() - total / 2
        ic = QRectF(x0, rect.center().y() - 11, icon_w, 22)
        if self._kind == "metronome":
            self._paint_metronome(p, ic, fg, on and enabled)
        elif self._kind == "countin":
            self._paint_countin(p, ic, fg, enabled)
        p.setPen(fg)
        p.drawText(QRectF(x0 + icon_w + gap, rect.top(), tw + 8, rect.height()), Qt.AlignVCenter | Qt.AlignLeft, self._text)
        p.end()

    def _paint_metronome(self, p, ic: QRectF, fg: QColor, active: bool):
        pen = QPen(fg); pen.setWidthF(1.7); pen.setJoinStyle(Qt.RoundJoin); pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        cx, top, bottom = ic.center().x(), ic.top() + 1, ic.bottom() - 1
        w = ic.width()
        p.drawPolygon(QPolygonF([QPointF(cx - w * 0.52, bottom), QPointF(cx + w * 0.52, bottom),
                                 QPointF(cx + w * 0.22, top), QPointF(cx - w * 0.22, top)]))
        side = self._swing if active else 0
        tip = QPointF(cx + side * w * 0.30, top + 2)
        base = QPointF(cx, bottom - 3)
        p.drawLine(base, tip)
        t = 0.62
        weight = QPointF(base.x() + (tip.x() - base.x()) * t, base.y() + (tip.y() - base.y()) * t)
        p.setBrush(fg)
        p.drawEllipse(weight, 2.2, 2.2)

    def _paint_countin(self, p, ic: QRectF, fg: QColor, enabled: bool):
        n = self._dots
        for i in range(n):
            cx = ic.left() + 4 + i * 8.0
            lit = (self._marker >= 0 and i <= self._marker) or (self.isChecked() and self._marker < 0)
            c = QColor(fg)
            pen = QPen(c); pen.setWidthF(1.4)
            p.setPen(pen)
            if lit:
                p.setBrush(c)
            else:
                p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(cx, ic.center().y()), 2.6 if i else 3.2, 2.6 if i else 3.2)


class ChoiceButton(QPushButton):
    """Choix exclusif en pastille rectangulaire (ex : une signature rythmique) : plein quand choisi."""

    def __init__(self, text: str, color: str, on_text: str = ON_SOFT, parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(34)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._color, self._on_text = color, on_text
        self._restyle()
        qconfig.themeChanged.connect(self._restyle)   # thème changé depuis les Réglages

    def _restyle(self, *_):
        color, on_text = self._color, self._on_text
        c = QColor(color)
        rgba = lambda a: f"rgba({c.red()},{c.green()},{c.blue()},{a})"
        p = pal()
        checked_fg = accent_fg(c).name()
        self.setStyleSheet(
            f"QPushButton {{ background: {p['raised']}; border: 1px solid {p['border']};"
            f" border-radius: 8px; color: {p['text']}; font-weight: 600; padding: 2px 6px; }}"
            f"QPushButton:hover {{ background: {p['hover']}; }}"
            f"QPushButton:checked {{ background: {rgba(0.22)}; border: 1px solid {rgba(0.45)}; color: {checked_fg}; }}"
            f"QPushButton:checked:hover {{ background: {rgba(0.3)}; }}"
            f"QPushButton:disabled {{ color: {p['faint']}; background: {p['raised']}; }}")


class TrackRow(QWidget):
    """Une piste : nom, muet, volume, suppression."""

    muted_changed = Signal(int, bool)
    gain_changed = Signal(int, float)
    delete_requested = Signal(int)

    def __init__(self, index: int, name: str, gain: float, muted: bool, parent=None):
        super().__init__(parent)
        self._index = index
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        label = BodyLabel(name)
        label.setMinimumWidth(70)
        row.addWidget(label)

        self._mute = TransparentToolButton(FluentIcon.MUTE if muted else FluentIcon.VOLUME)
        self._mute.setToolTip("Couper / rétablir cette piste")
        self._muted = muted
        self._mute.clicked.connect(self._toggle_mute)
        row.addWidget(self._mute)

        self._slider = NoWheelSlider(Qt.Horizontal)
        self._slider.setRange(0, 150)
        self._slider.setValue(round(gain * 100))
        self._slider.setMinimumWidth(50)
        self._slider.setToolTip("Volume de la piste")
        self._slider.valueChanged.connect(lambda v: self.gain_changed.emit(self._index, v / 100))
        row.addWidget(self._slider, stretch=1)

        delete = TransparentToolButton(FluentIcon.DELETE)
        delete.setToolTip("Supprimer la piste")
        delete.clicked.connect(lambda: self.delete_requested.emit(self._index))
        row.addWidget(delete)
        self._apply_muted()

    def _toggle_mute(self):
        self._muted = not self._muted
        self._apply_muted()
        self.muted_changed.emit(self._index, self._muted)

    def _apply_muted(self):
        self._mute.setIcon(FluentIcon.MUTE if self._muted else FluentIcon.VOLUME)
        self._slider.setEnabled(not self._muted)