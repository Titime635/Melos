"""
Les 75 styles de batterie du Mighty Plug Pro : numéro affiché (1-75), catégorie, nom.

Le CC / SysEx de style prend le numéro brut = numéro affiché - 1 (0-74), cf ui/drum_panel.py.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    key: str
    label: str      # nom complet (info-bulle, sous-titre)
    short: str      # étiquette d'onglet
    color: str


CATEGORIES = (
    Category("MET", "Métronome", "Métro", "#90A4AE"),
    Category("ROCK", "Rock", "Rock", "#E53935"),
    Category("CTRY", "Country", "Country", "#A1887F"),
    Category("BLUES", "Blues", "Blues", "#1E88E5"),
    Category("METAL", "Metal", "Metal", "#8E24AA"),
    Category("FUNK", "Funk", "Funk", "#FB8C00"),
    Category("JAZZ", "Jazz", "Jazz", "#26A69A"),
    Category("BALD", "Ballade", "Ballade", "#F06292"),
    Category("POP", "Pop", "Pop", "#FDD835"),
    Category("REGGAE", "Reggae", "Reggae", "#43A047"),
    Category("ELEC", "Électro", "Électro", "#3D5AFE"),
)
BY_KEY = {c.key: c for c in CATEGORIES}

_RAW = """
MET|4/4 4th;4/4 8th;4/4 16th;4/4 2nd Tri;4/4 4th Tri;4/4 8th Tri;3/4 4th;3/4 8th
ROCK|Standard;Swing Rock;Power Beat;Smooth;Mega Drive;Hard Rock;Boogie
CTRY|Walk Line;Blue Grass;Country;Waltz;Train;Ctry Rock;Slowly
BLUES|Slow Blues;Chicago;R&B;Blues Rock;Road Train;Shuffle
METAL|2X Bass;Close Beat;Heavy Bass;Fast;Holy Case;Open Hat;Epic
FUNK|Bouns;East Coast;New Mann;R&B Funk;80 Funk;Soul;Uncle Jam
JAZZ|Blues Jazz;Classic 1;Classic 2;Easy Jazz;Fast;Walking;Smooth
BALD|Bluesy;Grooves;Bald Rock;Slow Rock;Tutorial;R&B Bald;Gospel
POP|Beach Side;Big City;Funky Pop;Modern;School Pop;Motown;Resistor
REGGAE|Sherriff;Santeria;Reggae 3;Reggae 4;Reggae 5;Reggae 6;Reggae 7
ELEC|Elec 1;Elec 2;Elec 3;ELEC-EDM;ELEC-TECH
"""

# STYLES[raw] = (catégorie, nom) ; raw = numéro affiché - 1
STYLES: list[tuple[str, str]] = []
for _line in _RAW.strip().splitlines():
    _cat, _names = _line.split("|")
    STYLES.extend((_cat, n) for n in _names.split(";"))

STYLE_COUNT = len(STYLES)   # 75
MAX_RAW = STYLE_COUNT - 1


def clamp_raw(raw: int) -> int:
    return max(0, min(MAX_RAW, int(raw)))


def style_info(raw: int) -> tuple[Category, str, int]:
    """(catégorie, nom, numéro affiché) du style de CC brut `raw`."""
    raw = clamp_raw(raw)
    cat, name = STYLES[raw]
    return BY_KEY[cat], name, raw + 1


def raws_of(category_key: str) -> list[int]:
    return [i for i, (cat, _n) in enumerate(STYLES) if cat == category_key]
