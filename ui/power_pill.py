"""Interrupteur « ACTIVE / COUPÉE » de l'en-tête des modules (setlist, batterie)."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QApplication
from ui.module_card import notify_power
from ui.theme import ON_SOFT, qc


def _font(px: int, bold: bool = False) -> QFont:
    f = QFont(QApplication.font())
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def text_color() -> QColor:
    return qc("text")


class PowerPill(QAbstractButton):
    def __init__(self, accent: str, tooltip: str = "", on_text: str = "ACTIVE", off_text: str = "COUPÉE", parent=None):
        super().__init__(parent)
        self._accent, self._on_text, self._off_text = accent, on_text, off_text
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(82, 22)
        self.setToolTip(tooltip)
        self.toggled.connect(lambda on: notify_power(self, on))

    def setChecked(self, on: bool):             # les panneaux l'appellent signaux coupés : on prévient la carte à la main
        super().setChecked(on)
        notify_power(self, self.isChecked())

    def showEvent(self, e):
        super().showEvent(e)
        notify_power(self, self.isChecked())

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if on:       # actif : pastille pleine à la couleur du module
            acc = QColor(self._accent)
            bg = acc.lighter(108) if self.underMouse() else acc
            p.setPen(QPen(acc, 1))
            p.setBrush(bg)
            fg = QColor(ON_SOFT)
        else:        # coupé : simple contour gris, point creux
            p.setPen(QPen(qc("border").lighter(135), 1))
            p.setBrush(qc("hover" if self.underMouse() else "raised"))
            fg = qc("faint")
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        text = self._on_text if on else self._off_text
        font = _font(11, True)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 0.6)
        p.setFont(font)
        tw = QFontMetrics(font).horizontalAdvance(text)
        x0 = (r.width() - (tw + 14)) / 2
        dot = QRectF(x0 + 1, r.height() / 2 - 3, 6, 6)
        if on:
            p.setPen(Qt.NoPen)
            p.setBrush(fg)
        else:
            p.setPen(QPen(fg, 1.3))
            p.setBrush(Qt.NoBrush)
            dot = dot.adjusted(.4, .4, -.4, -.4)
        p.drawEllipse(dot)
        p.setPen(fg)
        p.drawText(QRectF(x0 + 14, 0, tw + 2, r.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
        p.end()