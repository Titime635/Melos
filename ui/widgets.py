"""
Petits composants partagés entre les panneaux.

NoWheel* désactive le changement de valeur à la molette sur les SpinBox/
Slider/ComboBox : très gênant quand on scrolle la page et qu'on frôle un de
ces widgets, la valeur change sans le vouloir. On laisse l'événement se
propager (event.ignore()) pour que le parent (la QScrollArea de la fenêtre)
scrolle normalement à la place.
"""

from PySide6.QtCore import QEvent
from qfluentwidgets import SpinBox, Slider, ComboBox


class NoWheelSpinBox(SpinBox):
    def wheelEvent(self, event):
        event.ignore()

    # Avec les Qt récents, le champ de texte du SpinBox de qfluentwidgets se retrouve large de 1 pixel (la valeur, « Manuelle »,
    # « 4 mes. »... disparaît : ne reste qu'un trait à côté des flèches). On lui redonne toute la place libre à gauche des flèches.
    def _fix_edit(self):
        le = self.lineEdit()
        if le is None or self.width() < 40 or not hasattr(self, "upButton"):
            return
        self.hBoxLayout.activate()
        right = self.upButton.x() - 4 if self.upButton.isVisibleTo(self) and self.upButton.x() > 0 else self.width() - 8
        le.setGeometry(10, 1, max(8, right - 10), max(8, self.height() - 2))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fix_edit()

    def showEvent(self, event):
        super().showEvent(event)
        self._fix_edit()

    def event(self, event):
        out = super().event(event)
        if event.type() in (QEvent.StyleChange, QEvent.FontChange, QEvent.LayoutRequest):
            self._fix_edit()
        return out


class NoWheelSlider(Slider):
    def wheelEvent(self, event):
        event.ignore()

    # Le curseur de qfluentwidgets ne place sa poignée que sur valueChanged : une valeur posée avec les
    # signaux bloqués (rafraîchissement depuis l'état partagé) ou avant l'affichage la laissait au
    # mauvais endroit alors que la barre était juste.
    def setValue(self, value):
        super().setValue(value)
        self._adjustHandlePos()

    def showEvent(self, event):
        super().showEvent(event)
        self._adjustHandlePos()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._adjustHandlePos()


class NoWheelComboBox(ComboBox):
    def wheelEvent(self, event):
        event.ignore()