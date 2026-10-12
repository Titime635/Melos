"""
Petits composants partagés entre les panneaux.

NoWheel* désactive le changement de valeur à la molette sur les SpinBox/
Slider/ComboBox : très gênant quand on scrolle la page et qu'on frôle un de
ces widgets, la valeur change sans le vouloir. On laisse l'événement se
propager (event.ignore()) pour que le parent (la QScrollArea de la fenêtre)
scrolle normalement à la place.
"""

from qfluentwidgets import SpinBox, Slider, ComboBox


class NoWheelSpinBox(SpinBox):
    def wheelEvent(self, event):
        event.ignore()


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