"""
Cliquer en dehors d'un champ de texte (zone de texte, valeur d'un SpinBox, liste éditable...) le quitte :
sans ça le focus y reste et le clavier (raccourcis compris, cf shortcuts/manager.py) reste captif.
"""

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QComboBox

from shortcuts.manager import is_text_input


def _owner(widget):
    """Le widget "composite" qui contient le champ : un SpinBox ou une ComboBox éditable
    (ses flèches / son bouton font partie du champ)."""
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, (QAbstractSpinBox, QComboBox)):
            return parent
        if parent is widget.window():
            break
        parent = parent.parentWidget()
    return widget


class FocusGuard(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress:
            focus = QApplication.focusWidget()
            if focus is not None and is_text_input(focus):
                target = QApplication.widgetAt(event.globalPosition().toPoint())
                owner = _owner(focus)
                if target is None or not (target is owner or owner.isAncestorOf(target)):
                    focus.clearFocus()
        return False