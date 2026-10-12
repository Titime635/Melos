"""Éléments dessinés du module Tuner : bouton diapason, cadran en arc, cordes."""

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QAbstractButton, QApplication, QSizePolicy, QWidget

from ui.power_pill import text_color

GREEN = QColor("#2ecc71")
WARM = QColor("#f2994a")
SPAN_DEG = 60.0          # l'arc va de -60° à +60° autour de la verticale
RANGE_CENTS = 50.0


def _font(px: float, bold: bool = False) -> QFont:
    f = QFont(QApplication.font())
    f.setPixelSize(max(6, int(px)))
    f.setBold(bold)
    return f


def _faint(alpha: int) -> QColor:
    c = text_color(); c.setAlpha(alpha)
    return c


def draw_fork(p: QPainter, rect: QRectF, color: QColor):
    """Diapason : deux branches en U, tige, petite boule."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    s = min(rect.width(), rect.height()) / 24.0
    p.translate(rect.center().x() - 12 * s, rect.center().y() - 12 * s)
    p.scale(s, s)
    p.setPen(QPen(color, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    u = QPainterPath()
    u.moveTo(8, 2.5); u.lineTo(8, 11.5)
    u.cubicTo(8, 15.2, 16, 15.2, 16, 11.5)
    u.lineTo(16, 2.5)
    p.drawPath(u)
    p.drawLine(QPointF(12, 14.6), QPointF(12, 19.5))
    p.setPen(Qt.NoPen); p.setBrush(color)
    p.drawEllipse(QPointF(12, 20.6), 1.9, 1.9)
    p.restore()


class ForkToggle(QAbstractButton):
    """Bouton d'activation de l'accordeur (diapason) : plein à la couleur du module quand il est actif."""

    def __init__(self, accent: str, parent=None):
        super().__init__(parent)
        self._accent = QColor(accent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(44, 24)
        self.setToolTip("Activer / couper l'accordeur")

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        on = self.isChecked()
        if on:
            p.setPen(Qt.NoPen); p.setBrush(self._accent); fg = QColor("#1b1b1b")
        else:
            border = text_color(); border.setAlpha(120 if not self.underMouse() else 200)
            p.setPen(QPen(border, 1)); p.setBrush(Qt.NoBrush); fg = _faint(190)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        draw_fork(p, QRectF(r.center().x() - 9, r.center().y() - 9, 18, 18), fg)
        p.end()


class TunerGauge(QWidget):
    """Arc gradué ♭ … ♯, aiguille, note en énorme au centre, écart en cents dessous."""

    def __init__(self, accent: str, parent=None):
        super().__init__(parent)
        self._accent = QColor(accent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(96)
        self._active = False
        self._signal = False
        self._label = "—"
        self._cents = 0.0
        self._in_tune = False
        self._fallback = False
        self._hint = ""
        self._angle = 0.0
        self._target = 0.0
        self._fade = 0.35
        self._fade_target = 0.35
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._animate)

    def sizeHint(self) -> QSize:
        return QSize(300, 190)

    def set_reading(self, active: bool, signal: bool, label: str, cents: float, in_tune: bool, hint: str = ""):
        self._active, self._signal = active, signal
        self._label, self._cents, self._in_tune, self._hint = label, cents, in_tune, hint
        c = max(-RANGE_CENTS * 1.1, min(RANGE_CENTS * 1.1, cents))
        self._target = c / RANGE_CENTS * SPAN_DEG if (active and signal) else 0.0
        self._fade_target = 1.0 if (active and signal) else (0.45 if active else 0.25)
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def _animate(self):
        self._angle += (self._target - self._angle) * 0.28
        self._fade += (self._fade_target - self._fade) * 0.2
        if abs(self._target - self._angle) < 0.05 and abs(self._fade_target - self._fade) < 0.01:
            self._angle, self._fade = self._target, self._fade_target
            self._timer.stop()
        self.update()

    # --- Dessin ---

    def _geometry(self):
        w, h = self.width(), self.height()
        m = 8
        r_w = (w - 2 * m) / (2 * math.sin(math.radians(SPAN_DEG))) - 6
        r_h = (h - 2 * m) / 1.42
        R = max(30.0, min(r_w, r_h))
        cx = w / 2
        cy = (h - R * 1.40) / 2 + R
        return cx, cy, R

    def paintEvent(self, _e):
        cx, cy, R = self._geometry()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        thick = max(6.0, R * 0.075)
        ring = R - thick / 2
        rect = QRectF(cx - ring, cy - ring, 2 * ring, 2 * ring)

        # anneau de fond + zone juste
        base = QPainterPath()
        base.arcMoveTo(rect, 90 + SPAN_DEG)
        base.arcTo(rect, 90 + SPAN_DEG, -2 * SPAN_DEG)
        pen = QPen(_faint(46), thick, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        p.drawPath(base)
        tol = 3.0 / RANGE_CENTS * SPAN_DEG
        zone = QPainterPath()
        zone.arcMoveTo(rect, 90 + tol)
        zone.arcTo(rect, 90 + tol, -2 * tol)
        g = QColor(GREEN); g.setAlpha(int(70 + 150 * self._fade) if self._in_tune and self._signal else 90)
        p.setPen(QPen(g, thick, Qt.SolidLine, Qt.FlatCap))
        p.drawPath(zone)

        # graduations (tous les 5 cents, repères à 0 / ±25 / ±50)
        for c in range(-50, 51, 5):
            a = math.radians(90 - c / RANGE_CENTS * SPAN_DEG)
            major = c in (-50, -25, 0, 25, 50)
            r1 = R - thick - R * 0.03
            r2 = r1 - R * (0.09 if major else 0.045)
            col = _faint(200 if major else 110)
            p.setPen(QPen(col, 2.0 if c == 0 else 1.3, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(cx + r1 * math.cos(a), cy - r1 * math.sin(a)),
                       QPointF(cx + r2 * math.cos(a), cy - r2 * math.sin(a)))

        # ♭ et ♯ aux extrémités
        sym_font = _font(R * 0.17, True)
        p.setFont(sym_font); p.setPen(_faint(200))
        for sign, sym in ((-1, "♭"), (1, "♯")):
            a = math.radians(90 - sign * SPAN_DEG)
            x, y = cx + (R * 0.97) * math.cos(a), cy - (R * 0.97) * math.sin(a)
            p.drawText(QRectF(x - R * 0.2 + sign * R * 0.0, y + R * 0.04, R * 0.4, R * 0.24), Qt.AlignHCenter | Qt.AlignTop, sym)

        # aiguille (le long de l'anneau)
        if self._active:
            col = QColor(GREEN if self._in_tune else WARM) if self._signal else _faint(120)
            col.setAlpha(int(255 * (0.25 + 0.75 * self._fade)))
            a = math.radians(90 - self._angle)
            r_out, r_in = R + thick * 0.15, R - thick - R * 0.12
            p.setPen(QPen(col, max(3.0, R * 0.03), Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(cx + r_in * math.cos(a), cy - r_in * math.sin(a)),
                       QPointF(cx + r_out * math.cos(a), cy - r_out * math.sin(a)))
            p.setPen(Qt.NoPen); p.setBrush(col)
            p.drawEllipse(QPointF(cx + r_out * math.cos(a), cy - r_out * math.sin(a)), thick * 0.55, thick * 0.55)

        # note en énorme + cents
        ncx, ncy = cx, cy - R * 0.30
        if self._active and self._signal and self._in_tune:
            halo = QColor(GREEN); halo.setAlpha(int(40 + 40 * self._fade))
            p.setPen(QPen(halo, max(3.0, R * 0.05))); p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(ncx, ncy), R * 0.36, R * 0.36)
            p.setPen(QPen(GREEN, max(2.0, R * 0.025)))
            p.drawEllipse(QPointF(ncx, ncy), R * 0.36, R * 0.36)
        label = self._label if self._active and (self._signal or self._label != "—") else "—"
        big = _font(R * (0.62 if len(label) <= 2 else 0.5) if label != "—" else R * 0.30, True)
        col = text_color(); col.setAlpha(int(255 * (0.35 + 0.65 * self._fade)))
        p.setFont(big); p.setPen(col)
        p.drawText(QRectF(ncx - R * 0.55, ncy - R * 0.36, R * 1.1, R * 0.72), Qt.AlignCenter, label)

        small = _font(max(11.0, R * 0.14), True)
        p.setFont(small)
        if not self._active:
            text, tc = "Accordeur coupé", _faint(150)
        elif not self._signal:
            text, tc = (self._hint or "Joue une corde"), _faint(150)
        else:
            v = int(round(self._cents))
            v = max(-99, min(99, v))
            text = "0 cent" if v == 0 else f"{'+' if v > 0 else '−'}{abs(v)} cents"
            tc = QColor(GREEN) if self._in_tune else text_color()
        p.setPen(tc)
        p.drawText(QRectF(cx - R * 0.8, cy + R * 0.10, R * 1.6, R * 0.28), Qt.AlignHCenter | Qt.AlignVCenter, text)
        p.end()


class StringChip(QAbstractButton):
    """Une corde de l'accordage : note + numéro. Cliquer la vise (mode manuel)."""

    def __init__(self, index: int, label: str, number: int, accent: str, parent=None):
        super().__init__(parent)
        self.index, self._label, self._number = index, label, number
        self._accent = QColor(accent)
        self.auto = False       # corde reconnue par l'auto-détection
        self.selected = False   # visée à la main
        self.tuned = False      # accordée
        self.live = False       # dans la tolérance en ce moment
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(30, 34)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip(f"Corde {number} : cliquer pour l'accorder seule (recliquer : retour en auto)")

    def set_string(self, label: str, number: int):
        self._label, self._number = label, number
        self.setToolTip(f"Corde {number} : cliquer pour l'accorder seule (recliquer : retour en auto)")
        self.update()

    def set_flags(self, auto=False, selected=False, tuned=False, live=False):
        if (auto, selected, tuned, live) != (self.auto, self.selected, self.tuned, self.live):
            self.auto, self.selected, self.tuned, self.live = auto, selected, tuned, live
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = min(10.0, r.height() / 2)
        if self.tuned:
            fill = QColor(GREEN); fill.setAlpha(60); edge = QColor(GREEN); fg = text_color()
        elif self.selected:
            fill = QColor(self._accent); fill.setAlpha(210); edge = QColor(self._accent); fg = QColor("#1b1b1b")
        elif self.auto:
            fill = QColor(self._accent); fill.setAlpha(45); edge = QColor(self._accent); fg = text_color()
        else:
            fill = _faint(14 if not self.underMouse() else 28); edge = _faint(70); fg = text_color()
        p.setPen(QPen(edge, 2.0 if (self.live or self.tuned) else 1.2))
        p.setBrush(fill)
        p.drawRoundedRect(r, radius, radius)
        if self.live:
            ring = QColor(GREEN); ring.setAlpha(110)
            p.setPen(QPen(ring, 3)); p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), radius + 1, radius + 1)
        tall = r.height() >= 44
        p.setPen(fg)
        p.setFont(_font(16 if r.width() >= 40 else 13, True))
        p.drawText(QRectF(r.left(), r.top() + (3 if tall else 0), r.width(), r.height() - (16 if tall else 0)),
                   Qt.AlignCenter, self._label)
        if tall:
            n = QColor(fg); n.setAlpha(140)
            p.setPen(n); p.setFont(_font(10))
            p.drawText(QRectF(r.left(), r.bottom() - 17, r.width(), 14), Qt.AlignCenter, str(self._number))
        if self.tuned:
            p.setPen(QPen(GREEN, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            x, y = r.right() - 9, r.top() + 8
            p.drawPolyline(QPolygonF([QPointF(x - 3.5, y), QPointF(x - 1, y + 2.8), QPointF(x + 3.5, y - 2.5)]))
        p.end()
