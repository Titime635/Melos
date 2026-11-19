"""
Habille les composants Fluent (boutons, listes déroulantes, champs de texte, nombres) avec la palette de la page Partition
(ui/theme.py) : mêmes gris de fond / relief / survol, mêmes coins arrondis, même teinte d'accent. Sans ça chaque onglet gardait
les gris et les contours propres à Fluent et l'appli paraissait faite de morceaux différents.

Principe : Fluent construit la feuille de style de chaque composant avec `FluentStyleSheet.content(thème)`. On y ajoute notre
bloc de règles, placé après celles de Fluent (donc prioritaire), à chaque fois que le thème change.
"""

import logging

from PySide6.QtGui import QColor
from qfluentwidgets import FluentStyleSheet, Theme, isDarkTheme

from ui.theme import DARK, LIGHT, mix, rgba

log = logging.getLogger("melos.style")
_installed = False
RADIUS = 8


def _palette(theme) -> dict:
    dark = isDarkTheme() if theme in (None, Theme.AUTO) else theme == Theme.DARK
    return DARK if dark else LIGHT


def _hex(c: QColor) -> str:
    return c.name(QColor.HexRgb)


def _button(p: dict) -> str:
    accent, text = QColor(p["accent"]), QColor(p["text"])
    checked_fg = _hex(mix(accent, text, 0.2 if p is DARK else 0.62))
    return f"""
PushButton, ToolButton, ToggleButton, ToggleToolButton {{
    background: {p['raised']}; border: 1px solid {p['border']}; border-radius: {RADIUS}px; color: {p['text']};
}}
PushButton:hover, ToolButton:hover, ToggleButton:hover, ToggleToolButton:hover {{ background: {p['hover']}; }}
PushButton:pressed, ToolButton:pressed, ToggleButton:pressed, ToggleToolButton:pressed {{
    background: {p['border']}; color: {p['muted']}; border: 1px solid {p['border']};
}}
PushButton:disabled, ToolButton:disabled, ToggleButton:disabled, ToggleToolButton:disabled {{
    background: {p['raised']}; color: {p['faint']}; border: 1px solid {p['border']};
}}
PushButton[isPlaceholderText=true] {{ color: {p['muted']}; }}
PrimaryPushButton, PrimaryToolButton {{
    color: {p['on_accent']}; background-color: {p['accent']}; border: 1px solid {p['accent']}; border-radius: {RADIUS}px;
}}
PrimaryPushButton:hover, PrimaryToolButton:hover {{ background-color: {_hex(mix(accent, text, 0.14))}; border: 1px solid {p['accent']}; }}
PrimaryPushButton:pressed, PrimaryToolButton:pressed {{ background-color: {_hex(mix(accent, QColor('#000000'), 0.2))};
    color: {p['on_accent']}; border: 1px solid {p['accent']}; }}
PrimaryPushButton:disabled, PrimaryToolButton:disabled {{ background-color: {p['raised']}; color: {p['faint']}; border: 1px solid {p['border']}; }}
ToggleButton:checked, ToggleToolButton:checked {{
    color: {checked_fg}; background-color: {rgba(p['accent'], 0.22)}; border: 1px solid {rgba(p['accent'], 0.45)};
}}
ToggleButton:checked:hover, ToggleToolButton:checked:hover {{ background-color: {rgba(p['accent'], 0.3)}; border: 1px solid {rgba(p['accent'], 0.55)}; }}
ToggleButton:checked:pressed, ToggleToolButton:checked:pressed {{ background-color: {rgba(p['accent'], 0.18)}; color: {checked_fg}; }}
ToggleButton:checked:disabled, ToggleToolButton:checked:disabled {{ background-color: {p['raised']}; color: {p['faint']}; border: 1px solid {p['border']}; }}
"""


def _fields(p: dict) -> str:
    focus = f"border: 1px solid {p['accent']};"
    return f"""
ComboBox, ModelComboBox {{
    background-color: {p['raised']}; border: 1px solid {p['border']}; border-radius: {RADIUS}px; color: {p['text']};
}}
ComboBox:hover, ModelComboBox:hover {{ background-color: {p['hover']}; }}
ComboBox:pressed, ModelComboBox:pressed {{ background-color: {p['border']}; color: {p['muted']}; border: 1px solid {p['border']}; }}
ComboBox:disabled, ModelComboBox:disabled {{ background: {p['raised']}; color: {p['faint']}; border: 1px solid {p['border']}; }}
ComboBox[isPlaceholderText=true], ModelComboBox[isPlaceholderText=true] {{ color: {p['muted']}; }}
LineEdit, TextEdit, PlainTextEdit, TextBrowser {{
    background-color: {p['raised']}; border: 1px solid {p['border']}; border-radius: {RADIUS}px; color: {p['text']};
    selection-background-color: {p['accent']}; selection-color: {p['on_accent']};
}}
LineEdit:hover, TextEdit:hover, PlainTextEdit:hover, TextBrowser:hover {{ background: {p['hover']}; }}
LineEdit:focus, TextEdit:focus, PlainTextEdit:focus, TextBrowser:focus,
LineEdit[transparent=true]:focus, LineEdit[transparent=false]:focus {{ {focus} background: {p['raised']}; }}
LineEdit:disabled, TextEdit:disabled, PlainTextEdit:disabled, TextBrowser:disabled {{ color: {p['faint']}; background-color: {p['raised']}; border: 1px solid {p['border']}; }}
SpinBox, DoubleSpinBox, CompactSpinBox, CompactDoubleSpinBox {{
    background-color: {p['raised']}; border: 1px solid {p['border']}; border-radius: {RADIUS}px; color: {p['text']};
    selection-background-color: {p['accent']}; selection-color: {p['on_accent']};
}}
SpinBox:hover, DoubleSpinBox:hover, CompactSpinBox:hover, CompactDoubleSpinBox:hover {{ background-color: {p['hover']}; }}
SpinBox:focus, DoubleSpinBox:focus, CompactSpinBox:focus, CompactDoubleSpinBox:focus,
SpinBox[transparent=true]:focus, SpinBox[transparent=false]:focus {{ {focus} background-color: {p['raised']}; }}
SpinBox:disabled, DoubleSpinBox:disabled, CompactSpinBox:disabled, CompactDoubleSpinBox:disabled {{
    color: {p['faint']}; background-color: {p['raised']}; border: 1px solid {p['border']}; }}
"""


def _dialog(p: dict) -> str:
    return f"""
QDialog {{ background-color: {p['surface']}; }}
#buttonGroup {{ background-color: {p['bg']}; border-top: 1px solid {p['border']}; }}
#centerWidget {{ background-color: {p['surface']}; border: 1px solid {p['border']}; border-radius: 12px; }}
MessageBoxBase #buttonGroup, MessageBox #buttonGroup {{ border-bottom-left-radius: 12px; border-bottom-right-radius: 12px; }}
"""


_OVERRIDES = {"DIALOG": _dialog, "BUTTON": _button, "COMBO_BOX": _fields, "LINE_EDIT": _fields, "SPIN_BOX": _fields}
# les composants « transparents » et « pilule » de Fluent viennent après les règles génériques : le bloc des boutons est donc
# glissé avant eux pour ne pas les écraser
_ANCHOR = "SplitDropButton,\nPrimarySplitDropButton {"


def install():
    """Branche les règles ci-dessus sur Fluent (une seule fois). Sans effet, sans casser l'appli, si Fluent change de forme."""
    global _installed
    if _installed:
        return
    _installed = True
    try:
        original = FluentStyleSheet.content

        def content(self, theme=Theme.AUTO):
            qss = original(self, theme)
            fn = _OVERRIDES.get(self.name)
            if fn is None:
                return qss
            try:
                extra = fn(_palette(theme))
            except Exception as exc:                  # un habillage raté ne doit jamais empêcher l'appli de s'afficher
                log.warning("habillage Fluent %s impossible : %s", self.name, exc)
                return qss
            if self.name == "BUTTON" and _ANCHOR in qss:
                return qss.replace(_ANCHOR, extra + _ANCHOR, 1)
            return qss + extra

        FluentStyleSheet.content = content
    except Exception as exc:
        log.warning("habillage Fluent désactivé : %s", exc)
