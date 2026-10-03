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


class NoWheelComboBox(ComboBox):
    def wheelEvent(self, event):
        event.ignore()
