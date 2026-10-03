"""
Un module de dashboard = un QDockWidget avec une barre de titre personnalisée
(bande fine colorée, sans texte redondant — le panneau a déjà son propre
titre). Le drag/redimensionnement passe par le mécanisme natif de Qt
(QMainWindow + QDockWidget) : c'est ce qui donne le tuilage sans espace mort.

La barre de titre grandit en mode Édition pour exposer deux boutons (replier
/ supprimer) ; en mode Performance elle redevient une simple bande fine, et
le CONTENU du module est désactivé en édition (setEnabled) — on ne doit pas
pouvoir toucher aux réglages d'un module pendant qu'on réarrange le
dashboard, cf. discussion.

Replier un module masque son contenu et le réduit à la hauteur de la bande
de titre ; les modules voisins récupèrent l'espace libéré (comportement
natif du dock Qt, rien à coder pour ça). Supprimer un module le détache du
dock (removeDockWidget) sans le détruire — c'est DashboardDockArea qui garde
la référence pour permettre de le rajouter plus tard (bouton "+").
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDockWidget, QWidget, QHBoxLayout
from qfluentwidgets import TransparentToolButton, FluentIcon

TITLE_STRIP_HEIGHT_LOCKED = 6
TITLE_STRIP_HEIGHT_EDIT = 22
BUTTON_SIZE = 18


def _dim(hex_color: str, factor: float = 0.4) -> str:
    """Assombrit une couleur d'accent pour indiquer le verrouillage."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = (int(c * factor) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


class _TitleStrip(QWidget):
    """Bande de titre : juste une couleur en mode Performance, deux petits
    boutons (replier / supprimer) en plus en mode Édition. Les zones vides
    de la bande restent le point de préhension pour le drag natif de Qt —
    les boutons, eux, consomment leur propre clic et ne déclenchent pas de
    drag (comportement standard de n'importe quel widget cliquable)."""

    collapse_toggled = Signal(bool)
    delete_requested = Signal()

    def __init__(self, accent_color: str, parent=None):
        super().__init__(parent)
        self._accent_color = accent_color
        self._collapsed = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)
        layout.addStretch()

        self._collapse_btn = TransparentToolButton(FluentIcon.CHEVRON_DOWN_MED, self)
        self._collapse_btn.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
        self._collapse_btn.setToolTip("Replier")
        self._collapse_btn.clicked.connect(self._on_collapse_clicked)
        layout.addWidget(self._collapse_btn)

        self._delete_btn = TransparentToolButton(FluentIcon.CLOSE, self)
        self._delete_btn.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
        self._delete_btn.setToolTip("Supprimer du dashboard")
        self._delete_btn.clicked.connect(self.delete_requested.emit)
        layout.addWidget(self._delete_btn)

        self.set_edit_mode(False)

    def set_edit_mode(self, active: bool):
        self._collapse_btn.setVisible(active)
        self._delete_btn.setVisible(active)
        self.setFixedHeight(TITLE_STRIP_HEIGHT_EDIT if active else TITLE_STRIP_HEIGHT_LOCKED)
        color = self._accent_color if active else _dim(self._accent_color)
        self.setStyleSheet(f"background-color: {color}; border-radius: 2px;")

    def _on_collapse_clicked(self):
        self._collapsed = not self._collapsed
        self._collapse_btn.setIcon(
            FluentIcon.CHEVRON_RIGHT_MED if self._collapsed else FluentIcon.CHEVRON_DOWN_MED
        )
        self._collapse_btn.setToolTip("Déplier" if self._collapsed else "Replier")
        self.collapse_toggled.emit(self._collapsed)


class ModuleDock(QDockWidget):
    delete_requested = Signal(object)  # (self) — DashboardDockArea gère le retrait/la mémorisation

    def __init__(self, module_id: str, title: str, accent_color: str, content: QWidget, parent=None):
        super().__init__(title, parent)
        self.module_id = module_id
        self._accent_color = accent_color
        self._content = content
        self._content_min_height = content.minimumSizeHint().height()

        self._strip = _TitleStrip(accent_color, self)
        self._strip.collapse_toggled.connect(self._on_collapse_toggled)
        self._strip.delete_requested.connect(lambda: self.delete_requested.emit(self))
        self.setTitleBarWidget(self._strip)

        self.setWidget(content)
        self.set_edit_mode(False)  # verrouillé par défaut

    def set_edit_mode(self, active: bool):
        self.setFeatures(
            QDockWidget.DockWidgetMovable if active else QDockWidget.NoDockWidgetFeatures
        )
        self._strip.set_edit_mode(active)
        # On ne peut pas modifier les réglages d'un module pendant qu'on
        # réarrange le dashboard (cf discussion) — désactivé en édition,
        # réactivé en performance.
        self._content.setEnabled(not active)

    def _on_collapse_toggled(self, collapsed: bool):
        self._content.setVisible(not collapsed)
        if collapsed:
            self.setFixedHeight(TITLE_STRIP_HEIGHT_EDIT)
        else:
            self.setMinimumHeight(self._content_min_height)
            self.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX : retire la contrainte fixe