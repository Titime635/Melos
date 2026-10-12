"""Interrupteur « ACTIVE / COUPÉE » de l'en-tête des modules (setlist, batterie)."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QApplication
from qfluentwidgets import isDarkTheme


def _font(px: int, bold: bool = False) -> QFont:
    f = QFont(QApplication.font())
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def text_color() -> QColor:
    return QColor("#f2f2f2" if isDarkTheme() else "#1f1f1f")


class PowerPill(QAbstractButton):
    def __init__(self, accent: str, tooltip: str = "", on_text: str = "ACTIVE", off_text: str = "COUPÉE", parent=None):
        super().__init__(parent)
        self._accent, self._on_text, self._off_text = accent, on_text, off_text
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(82, 22)
        self.setToolTip(tooltip)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if on:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(self._accent))
            fg = QColor("white")
        else:
            border = text_color()
            border.setAlpha(110)
            p.setPen(QPen(border, 1))
            p.setBrush(Qt.NoBrush)
            fg = text_color()
            fg.setAlpha(170)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        text = self._on_text if on else self._off_text
        font = _font(11, True)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 0.6)
        p.setFont(font)
        tw = QFontMetrics(font).horizontalAdvance(text)
        x0 = (r.width() - (tw + 14)) / 2
        p.setPen(Qt.NoPen)
        p.setBrush(fg)
        p.drawEllipse(QRectF(x0 + 1, r.height() / 2 - 3, 6, 6))
        p.setPen(fg)
        p.drawText(QRectF(x0 + 14, 0, tw + 2, r.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
        p.end()
