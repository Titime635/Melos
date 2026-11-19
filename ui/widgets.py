"""
Petits composants partagés entre les panneaux.

NoWheel* désactive le changement de valeur à la molette sur les SpinBox/
Slider/ComboBox : très gênant quand on scrolle la page et qu'on frôle un de
ces widgets, la valeur change sans le vouloir. On laisse l'événement se
propager (event.ignore()) pour que le parent (la QScrollArea de la fenêtre)
scrolle normalement à la place.
"""

from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QAbstractSpinBox, QDoubleSpinBox, QSpinBox
from qfluentwidgets import ComboBox, qconfig

from ui.tab_widgets import TabSlider
from ui.theme import pal, qc

HEIGHT = 32
BUTTON_W = 26


class _StepButton(QAbstractButton):
    """Bouton « − » / « + » arrondi aux deux bouts d'un champ numérique (répète quand on le maintient)."""

    def __init__(self, sign: int, parent):
        super().__init__(parent)
        self._sign = sign
        self.setAutoRepeat(True)
        self.setAutoRepeatDelay(350)
        self.setAutoRepeatInterval(60)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        enabled = self.isEnabled()
        if enabled and self.isDown():
            p.setBrush(qc("accent", 0.28))
        elif enabled and self.underMouse():
            p.setBrush(qc("hover"))
        else:
            p.setBrush(qc("raised"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(r, 7, 7)
        p.setPen(QPen(qc("accent" if enabled else "faint"), 1.8, Qt.SolidLine, Qt.RoundCap))
        cx, cy, h = r.center().x(), r.center().y(), 4.5
        p.drawLine(cx - h, cy, cx + h, cy)
        if self._sign > 0:
            p.drawLine(cx, cy - h, cx, cy + h)
        p.end()


class _Stepper:
    """Champ numérique de l'appli : valeur centrée, bouton − à gauche et + à droite, sans molette (pas de changement en
    frôlant le champ en faisant défiler la page : l'événement remonte à la page)."""

    def _setup_stepper(self):
        self.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(HEIGHT)
        self.setMinimumWidth(112)
        self.setKeyboardTracking(False)
        self.lineEdit().setTextMargins(BUTTON_W + 4, 0, BUTTON_W + 4, 0)     # la valeur reste entre les deux boutons
        self._minus, self._plus = _StepButton(-1, self), _StepButton(1, self)
        self._minus.clicked.connect(self.stepDown)
        self._plus.clicked.connect(self.stepUp)
        self._restyle()
        qconfig.themeChanged.connect(lambda *_: self._restyle())

    def _fit_width(self):
        """Largeur minimale : le texte le plus long (valeur max, texte spécial, préfixe / suffixe) doit tenir entre les deux boutons."""
        if not hasattr(self, "_minus"):
            return
        from PySide6.QtGui import QFont, QFontMetrics
        f = QFont(self.font())
        f.setBold(True)
        fm = QFontMetrics(f)
        texts = [self.specialValueText()] + [f"{self.prefix()}{self.textFromValue(v)}{self.suffix()}"
                                             for v in (self.minimum(), self.maximum())]
        need = max(fm.horizontalAdvance(t) for t in texts if t) + 2 * (BUTTON_W + 8) + 4
        self.setMinimumWidth(max(112, need))

    def setSpecialValueText(self, text):
        super().setSpecialValueText(text)
        self._fit_width()

    def setSuffix(self, text):
        super().setSuffix(text)
        self._fit_width()

    def setPrefix(self, text):
        super().setPrefix(text)
        self._fit_width()

    def setRange(self, lo, hi):
        super().setRange(lo, hi)
        self._fit_width()

    def _restyle(self):
        try:
            c = pal()
            self.setStyleSheet(
                f"{self.__class__.__name__} {{ background: {c['raised']}; border: 1px solid {c['border']}; border-radius: 9px;"
                f" color: {c['text']}; font-weight: 600; padding: 0;"
                f" selection-background-color: {c['accent']}; selection-color: {c['on_accent']}; }}"
                f"{self.__class__.__name__}:hover {{ background: {c['hover']}; }}"
                f"{self.__class__.__name__}:focus {{ border: 1px solid {c['accent']}; background: {c['raised']}; }}"
                f"{self.__class__.__name__}:disabled {{ color: {c['faint']}; background: {c['raised']}; }}")
            self._minus.update()
            self._plus.update()
        except RuntimeError:                                   # widget détruit
            pass

    def _place_buttons(self):
        h = self.height() - 6
        self._minus.setGeometry(3, 3, BUTTON_W, h)
        self._plus.setGeometry(self.width() - 3 - BUTTON_W, 3, BUTTON_W, h)
        # Avec les Qt récents, le champ de texte d'un SpinBox sans flèches (ou habillé en feuille de style) se retrouve large de
        # 1 pixel : on lui redonne toute la place, la valeur restant centrée entre les deux boutons (marges du texte).
        le = self.lineEdit()
        if le is not None and self.width() > 40:
            le.setGeometry(1, 1, self.width() - 2, self.height() - 2)
        self._minus.raise_()
        self._plus.raise_()

    def wheelEvent(self, event):
        event.ignore()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_buttons()

    def showEvent(self, event):
        super().showEvent(event)
        self._place_buttons()

    def changeEvent(self, event):
        super().changeEvent(event)
        if hasattr(self, "_minus"):
            self._minus.update()
            self._plus.update()

    def event(self, event):
        out = super().event(event)
        if hasattr(self, "_minus") and event.type() in (QEvent.StyleChange, QEvent.FontChange, QEvent.LayoutRequest,
                                                         QEvent.PolishRequest, QEvent.Polish):
            self._place_buttons()
        return out


class NoWheelSpinBox(_Stepper, QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_stepper()


class NoWheelDoubleSpinBox(_Stepper, QDoubleSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_stepper()


class NoWheelSlider(TabSlider):
    """Curseur de la partition (rail fin, poignée ronde) sans changement à la molette : même curseur dans toute l'appli."""

    def wheelEvent(self, event):
        event.ignore()


class NoWheelComboBox(ComboBox):
    def wheelEvent(self, event):
        event.ignore()