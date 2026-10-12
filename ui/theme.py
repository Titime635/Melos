"""Thème de l'appli : "auto" (celui de Windows), "light" ou "dark" (réglage de la page Réglages)."""

from qfluentwidgets import Theme, setTheme

THEMES = {"auto": Theme.AUTO, "light": Theme.LIGHT, "dark": Theme.DARK}


def apply_theme(name: str):
    setTheme(THEMES.get(name, Theme.AUTO))
