"""
Outils d'édition de la partition : tout ce que propose la palette de Songsterr, sur le modèle de tabs/model.py.

Une table (`TOOLS`) décrit chaque bouton de la palette (onglet, libellé, bulle d'aide, ce qu'il modifie) ; `tool_state` dit s'il
est utilisable et allumé pour la sélection courante ; `apply_tool` l'applique à UNE copie de la mesure (voix `ctx.voice`) :
la sauvegarde dans « Ma version » est faite par ui/tab_editing.py. Aucune dépendance à Qt : testable seul.

  cible « note »   : l'effet va sur la note de la corde choisie (désactivé s'il n'y en a pas)
  cible « beat »   : l'effet va sur le temps entier
  cible « bar »    : l'effet va sur la mesure
  cible « op »     : une action (déplacer, copier, supprimer...)
  cible « prompt » : demande un texte à l'utilisateur (le contrôleur s'en charge)
"""

import copy
from dataclasses import asdict, dataclass, field

from . import score_edits as se
from .model import Beat, Measure

TABS = (("temps", "Temps"), ("notes", "Notes"), ("mesure", "Mesure"), ("edition", "Édition"))
VOICES = 4


class ToolError(Exception):
    """L'outil ne peut pas s'appliquer ici (message pour la barre d'état)."""


@dataclass(frozen=True)
class Tool:
    id: str
    tab: str
    label: str                    # texte du bouton (court)
    tip: str                      # bulle d'aide
    scope: str                    # note | beat | bar | op | prompt
    more: tuple = ()              # variantes : ((argument, texte du menu), ...) ; la première est celle du bouton
    menu_only: bool = False       # le bouton ouvre seulement le menu des variantes
    gap: bool = False             # un espace avant ce bouton (début de groupe)


@dataclass
class Ctx:
    """Contexte d'une action : tuning de la piste (MIDI, corde 0 = la plus aiguë), voix modifiée, presse-papiers."""
    tuning: list = field(default_factory=list)
    voice: int = 0
    clip: dict | None = None


@dataclass
class Result:
    beat: int | None = None       # temps à sélectionner ensuite
    string: int | None = None     # corde à sélectionner ensuite
    clip: dict | None = None      # nouveau contenu du presse-papiers
    msg: str = ""


# ---------------------------------------------------------------------------------------------------------
# valeurs : (cible, attribut, {argument: valeur}, [(attribut à remettre à zéro, valeur)])  -- le premier argument est celui du bouton

BENDS = {"bend100": [(0, 0), (60, 100)], "bend50": [(0, 0), (60, 50)], "bend150": [(0, 0), (60, 150)], "bend200": [(0, 0), (60, 200)],
         "br100": [(0, 0), (30, 100), (60, 0)], "pre100": [(0, 100), (60, 100)], "prer100": [(0, 100), (30, 100), (60, 0)]}
WHAMMY = {"dip": [(0, 0), (30, -100), (60, 0)], "dive": [(0, 0), (60, -200)], "hold": [(0, 0), (60, 0)],
          "predive": [(0, -200), (60, -200)], "predivedive": [(0, -200), (60, -400)]}
RASGUEADOS = ("ii", "mi", "miitriplet", "pmptriplet", "amitriplet", "ppp", "amii", "eami")
DYNAMICS = ("mf", "ppp", "pp", "p", "mp", "f", "ff", "fff")
KEY_NAMES = {-7: "Do♭ (7 ♭)", -6: "Sol♭ (6 ♭)", -5: "Ré♭ (5 ♭)", -4: "La♭ (4 ♭)", -3: "Mi♭ (3 ♭)", -2: "Si♭ (2 ♭)", -1: "Fa (1 ♭)",
             0: "Do (aucune altération)", 1: "Sol (1 ♯)", 2: "Ré (2 ♯)", 3: "La (3 ♯)", 4: "Mi (4 ♯)", 5: "Si (5 ♯)", 6: "Fa♯ (6 ♯)",
             7: "Do♯ (7 ♯)"}

VALUES: dict[str, tuple] = {
    "dot": ("beat", "dots", {"": 1}, ()),
    "ddot": ("beat", "dots", {"": 2}, ()),
    "tup": ("beat", "tuplet", {"3": 3, "5": 5, "6": 6, "7": 7, "9": 9, "10": 10, "12": 12}, ()),
    "fermata": ("beat", "fermata", {"medium": "medium", "short": "short", "long": "long"}, ()),
    "dyn": ("beat", "velocity", {d: d for d in DYNAMICS}, ()),
    "cre": ("beat", "crescendo", {"": "cre"}, ()),
    "dec": ("beat", "crescendo", {"": "dec"}, ()),
    "lr": ("beat", "let_ring", {"": True}, ()),
    "pm": ("beat", "palm_mute", {"": True}, ()),
    "grace_b": ("beat", "grace", {"": "beforeBeat"}, ()),
    "grace_o": ("beat", "grace", {"": "onBeat"}, ()),
    "pick_d": ("beat", "pick", {"": "down"}, ()),
    "pick_u": ("beat", "pick", {"": "up"}, ()),
    "ghost": ("note", "ghost", {"": True}, (("dead", False),)),
    "acc": ("note", "accent", {"": 1}, ()),
    "hac": ("note", "accent", {"": 2}, ()),
    "stac": ("note", "staccato", {"": True}, ()),
    "dead": ("note", "dead", {"": True}, (("ghost", False),)),
    "vib": ("note", "vibrato", {"": True}, (("vibrato_wide", False),)),
    "vibw": ("note", "vibrato_wide", {"": True}, (("vibrato", False),)),
    "harm": ("note", "harmonic", {a: a for a in ("natural", "artificial", "pinch", "tap", "semi", "feedback")}, ()),
    "tie": ("note", "tie", {"": True}, ()),
    "hammer": ("note", "hammer", {"": True}, ()),
    "sl_s": ("note", "slide", {"": "shift"}, ()),
    "sl_l": ("note", "slide", {"": "legato"}, ()),
    "sl_ib": ("note", "slide", {"": "into_from_below"}, ()),
    "sl_ia": ("note", "slide", {"": "into_from_above"}, ()),
    "sl_od": ("note", "slide", {"": "out_down"}, ()),
    "sl_ou": ("note", "slide", {"": "out_up"}, ()),
    "bend": ("note", "bend", {k: v for k, v in BENDS.items()}, ()),
    "tap": ("note", "lh_tap", {"": True}, ()),
    "whammy": ("beat", "whammy", {k: v for k, v in WHAMMY.items()}, ()),
    "brush_u": ("beat", "brush", {"bu": "bu", "au": "au"}, ()),
    "brush_d": ("beat", "brush", {"bd": "bd", "ad": "ad"}, ()),
    "rasg": ("beat", "rasgueado", {a: a for a in RASGUEADOS}, ()),
    "tremolo": ("beat", "tremolo", {"2": 2, "1": 1, "3": 3}, ()),
    "wah_o": ("beat", "wah", {"": "open"}, ()),
    "wah_c": ("beat", "wah", {"": "closed"}, ()),
    "ped_d": ("beat", "pedal", {"": "down"}, ()),
    "ped_u": ("beat", "pedal", {"": "up"}, ()),
    "golpe": ("beat", "golpe", {"finger": "finger", "thumb": "thumb"}, ()),
    "dead_slap": ("beat", "dead_slap", {"": True}, ()),
    "rep_s": ("bar", "repeat_start", {"": True}, ()),
    "rep_e": ("bar", "repeat_end", {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "8": 8}, ()),
    "dbl": ("bar", "double_bar", {"": True}, ()),
    "pickup": ("bar", "pickup", {"": True}, ()),
}


def _t(id, tab, label, tip, scope, more=(), menu_only=False, gap=False):
    return Tool(id, tab, label, tip, scope, tuple(more), menu_only, gap)


_TUP = tuple((n, f"{n}-olet ({n} temps à la place de {d})") for n, d in ((3, 2), (5, 4), (6, 4), (7, 4), (9, 8), (10, 8), (12, 8)))
TOOLS: list[Tool] = [
    # ---- temps
    *[_t(f"d{b}", "temps", str(b), f"Durée : {n} (1/{b})", "op", gap=(b == 64)) for b, n in
      ((64, "quadruple-croche"), (32, "triple-croche"), (16, "double-croche"), (8, "croche"), (4, "noire"), (2, "blanche"), (1, "ronde"))],
    _t("dot", "temps", "•", "Point : allonge de la moitié (touche .)", "beat", gap=True),
    _t("ddot", "temps", "••", "Double point : allonge des trois quarts", "beat"),
    _t("rest", "temps", "Sil.", "Silence : transforme le temps en silence (touche R)", "op", gap=True),
    _t("tup", "temps", "3", "Triolet (et autres n-olets avec ⋮)", "beat", [(str(n), t) for n, t in _TUP]),
    _t("fermata", "temps", "Fer.", "Point d'orgue", "beat",
       [("medium", "Point d'orgue moyen"), ("short", "Point d'orgue court"), ("long", "Point d'orgue long")], gap=True),
    _t("dyn", "temps", "mf", "Nuance (mf ; ⋮ pour ppp … fff)", "beat", [(d, d) for d in DYNAMICS]),
    _t("cre", "temps", "cresc.", "Crescendo à partir de ce temps", "beat"),
    _t("dec", "temps", "dim.", "Diminuendo à partir de ce temps", "beat"),
    _t("lr", "temps", "L.R.", "Let ring : laisser sonner", "beat", gap=True),
    _t("pm", "temps", "P.M.", "Palm mute : sourdine de paume", "beat"),
    _t("grace_b", "temps", "Gr.", "Note d'ornement avant le temps", "beat", gap=True),
    _t("grace_o", "temps", "Gr.=", "Note d'ornement sur le temps", "beat"),
    _t("pick_d", "temps", "⊓", "Coup de médiator vers le bas", "beat", gap=True),
    _t("pick_u", "temps", "V", "Coup de médiator vers le haut", "beat"),
    _t("text", "temps", "TXT", "Annotation au-dessus du temps", "prompt", gap=True),
    _t("chord", "temps", "Acc.", "Nom d'accord au-dessus du temps (le diagramme n'est pas dessiné)", "prompt"),
    # ---- notes
    _t("ghost", "notes", "(0)", "Note fantôme (entre parenthèses)", "note"),
    _t("acc", "notes", ">", "Accent", "note"),
    _t("hac", "notes", "^", "Accent fort", "note"),
    _t("stac", "notes", "St.", "Staccato", "note"),
    _t("dead", "notes", "x", "Note étouffée (morte)", "note"),
    _t("vib", "notes", "~", "Vibrato", "note", gap=True),
    _t("vibw", "notes", "≈", "Vibrato large", "note"),
    _t("harm", "notes", "◇", "Harmonique naturelle (⋮ : artificielle, pincée, tapée, semi, larsen)", "note",
       [("natural", "Harmonique naturelle"), ("artificial", "Harmonique artificielle"), ("pinch", "Harmonique pincée"),
        ("tap", "Harmonique tapée"), ("semi", "Semi-harmonique"), ("feedback", "Larsen")]),
    _t("tie", "notes", "⌒", "Liaison : tient la note précédente de la même corde", "note", gap=True),
    _t("hammer", "notes", "H/P", "Hammer-on / pull-off vers la note suivante", "note"),
    _t("sl_s", "notes", "0/1", "Glissé", "note", gap=True),
    _t("sl_l", "notes", "⌒/", "Glissé lié (legato)", "note"),
    _t("sl_ib", "notes", "/0", "Glissé d'entrée par le bas", "note"),
    _t("sl_ia", "notes", "\\0", "Glissé d'entrée par le haut", "note"),
    _t("sl_od", "notes", "0\\", "Glissé de sortie vers le bas", "note"),
    _t("sl_ou", "notes", "0/", "Glissé de sortie vers le haut", "note"),
    _t("bend", "notes", "↗", "Tiré (bend) d'un ton ; ⋮ pour la hauteur, le relâché, le pré-tiré", "note",
       [("bend100", "Tiré d'un ton"), ("bend50", "Tiré d'un demi-ton"), ("bend150", "Tiré d'un ton et demi"),
        ("bend200", "Tiré de deux tons"), ("br100", "Tiré et relâché"), ("pre100", "Pré-tiré"), ("prer100", "Pré-tiré et relâché")], gap=True),
    _t("whammy", "notes", "⇅", "Levier : plongeon bref (⋮ : plongeon, tenu, pré-plongeon)", "beat",
       [("dip", "Levier : aller-retour"), ("dive", "Levier : plongeon"), ("hold", "Levier : tenu"),
        ("predive", "Levier : pré-plongeon"), ("predivedive", "Levier : pré-plongeon puis plongeon")]),
    _t("brush_u", "notes", "Bal.↑", "Balayage vers le haut (⋮ : arpège)", "beat",
       [("bu", "Balayage vers le haut"), ("au", "Arpège vers le haut")], gap=True),
    _t("brush_d", "notes", "Bal.↓", "Balayage vers le bas (⋮ : arpège)", "beat",
       [("bd", "Balayage vers le bas"), ("ad", "Arpège vers le bas")]),
    _t("rasg", "notes", "rasg.", "Rasgueado (⋮ : autres motifs)", "beat", [(a, f"Rasgueado {a}") for a in RASGUEADOS]),
    _t("trill", "notes", "tr", "Trille (la note alterne avec celle deux cases plus loin)", "op"),
    _t("tap", "notes", "TAP", "Tapping (main gauche)", "note"),
    _t("tremolo", "notes", "///", "Trémolo de médiator (⋮ : 1 à 3 barres)", "beat",
       [("2", "Trémolo, 2 barres (double-croche)"), ("1", "Trémolo, 1 barre (croche)"), ("3", "Trémolo, 3 barres (triple-croche)")]),
    _t("golpe", "notes", "Gol.", "Golpe : coup sur la table (⋮ : doigt / pouce)", "beat",
       [("finger", "Golpe du doigt"), ("thumb", "Golpe du pouce")]),
    _t("wah_o", "notes", "Wah○", "Pédale wah ouverte", "beat", gap=True),
    _t("wah_c", "notes", "Wah+", "Pédale wah fermée", "beat"),
    _t("dead_slap", "notes", "X", "Coup mort (rythmique étouffée, frappée)", "beat"),
    _t("ped_d", "notes", "Ped.", "Pédale de sustain : enfoncer", "beat", gap=True),
    _t("ped_u", "notes", "Ped.✱", "Pédale de sustain : relâcher", "beat"),
    # ---- mesure
    _t("rep_s", "mesure", "||:", "Début de reprise", "bar"),
    _t("rep_e", "mesure", ":||", "Fin de reprise (⋮ : nombre de passages)", "bar", [(str(n), f"{n} passages") for n in (2, 3, 4, 5, 6, 8)]),
    _t("alt", "mesure", "1.", "Fin alternative (maison) : 1re fin (⋮ : 2e, 3e, 4e)", "bar",
       [(str(n), f"{n}{'re' if n == 1 else 'e'} fin") for n in (1, 2, 3, 4)]),
    _t("dbl", "mesure", "||", "Double barre", "bar"),
    _t("ts", "mesure", "4/4", "Signature rythmique de cette mesure", "prompt", gap=True),
    _t("tempo", "mesure", "♩=", "Tempo à partir de cette mesure", "prompt"),
    _t("pickup", "mesure", "Anacr.", "Mesure d'anacrouse (plus courte que la signature)", "bar"),
    _t("key", "mesure", "Arm.", "Armure à partir de cette mesure", "bar", [(str(k), n) for k, n in KEY_NAMES.items()], menu_only=True),
    _t("sect", "mesure", "sect.", "Titre de section sur la mesure", "prompt", gap=True),
    # ---- édition
    _t("mv_nu", "edition", "Note▲", "Monte la note d'une corde (même hauteur)", "op"),
    _t("mv_nd", "edition", "Note▼", "Descend la note d'une corde (même hauteur)", "op"),
    _t("mv_bu", "edition", "Temps▲", "Monte tout le temps d'une corde (mêmes hauteurs)", "op"),
    _t("mv_bd", "edition", "Temps▼", "Descend tout le temps d'une corde (mêmes hauteurs)", "op"),
    _t("semi_p", "edition", "+½", "Note plus aiguë d'un demi-ton (case +1)", "op", gap=True),
    _t("semi_m", "edition", "−½", "Note plus grave d'un demi-ton (case −1)", "op"),
    _t("oct_p", "edition", "+8ve", "Note une octave plus haut (case +12)", "op"),
    _t("oct_m", "edition", "−8ve", "Note une octave plus bas (case −12)", "op"),
    _t("swap_l", "edition", "Temps◀", "Échange ce temps avec le précédent", "op", gap=True),
    _t("swap_r", "edition", "Temps▶", "Échange ce temps avec le suivant", "op"),
    _t("ins", "edition", "+ Temps", "Insère un silence après ce temps (touche Inser)", "op"),
    _t("complete", "edition", "Compl.", "Complète la mesure avec des silences", "op"),
    _t("cut_b", "edition", "✂ T", "Couper le temps (il devient un silence)", "op", gap=True),
    _t("cut_m", "edition", "✂ M", "Couper toute la mesure (la voix devient des silences)", "op"),
    _t("copy_b", "edition", "Copier T", "Copier le temps", "op"),
    _t("copy_m", "edition", "Copier M", "Copier la mesure (la voix choisie)", "op"),
    _t("paste", "edition", "Coller", "Coller le temps ou la mesure copiés à la place de la sélection", "op"),
    _t("del_note", "edition", "Suppr. N", "Supprimer la note (touche Suppr)", "op", gap=True),
    _t("del_beat", "edition", "Suppr. T", "Supprimer le temps (touches Maj+Suppr)", "op"),
    _t("del_bar", "edition", "Vider M", "Vider la mesure (la voix devient des silences ; le nombre de mesures ne change pas)", "op"),
]
BY_ID = {t.id: t for t in TOOLS}
BASES_TOOLS = {f"d{b}": b for b in se.BASES}


# ---------------------------------------------------------------------------------------------------------
# lecture de l'état

def _obj(scope, m: Measure, b: Beat | None, n):
    return {"bar": m, "beat": b, "note": n}[scope]


def _cur(tool: Tool, m, b, n):
    scope, attr, choices, _ = VALUES[tool.id]
    obj = _obj(scope, m, b, n)
    if obj is None:
        return None
    cur = getattr(obj, attr)
    if tool.id in ("pm", "lr") and not cur and b is not None and b.notes:        # certains temps le portent note par note
        return all(getattr(x, attr) for x in b.notes)
    return cur


def _is_on(tool: Tool, cur, arg: str | None) -> bool:
    choices = VALUES[tool.id][2]
    if arg is None:
        return bool(cur) if tool.more else cur == next(iter(choices.values()))
    return cur == choices[arg]


def tool_state(tool: Tool, m: Measure | None, j: int, s: int, ctx: Ctx) -> tuple[bool, bool]:
    """(utilisable, allumé) pour la sélection (mesure `m`, temps `j`, corde `s`) ; la mesure peut être None."""
    if m is None:
        return False, False
    bs = se.view(m, ctx.voice)
    b = bs[j] if 0 <= j < len(bs) else None
    n = se.find_note(b, s) if b is not None else None
    sc = tool.scope
    if tool.id in BASES_TOOLS:
        return b is not None, b is not None and b.base == BASES_TOOLS[tool.id]
    if tool.id == "alt":
        return True, bool(m.alt_ending)
    if tool.id == "key":
        return True, m.key != 0
    if tool.id == "tempo" or tool.id == "sect" or tool.id == "ts":
        return True, False
    if tool.id == "trill":
        return n is not None, n is not None and n.trill is not None
    if sc == "prompt":
        return b is not None, bool(b and (b.text if tool.id == "text" else b.chord))
    if sc == "op":
        return _op_enabled(tool.id, m, bs, j, s, b, n, ctx), False
    if sc == "bar":
        return True, _is_on(tool, _cur(tool, m, b, n), None)
    if sc == "beat":
        return b is not None, b is not None and _is_on(tool, _cur(tool, m, b, n), None)
    return n is not None, n is not None and _is_on(tool, _cur(tool, m, b, n), None)


def variant_on(tool: Tool, m: Measure, j: int, s: int, ctx: Ctx, arg: str) -> bool:
    """La variante `arg` (menu ⋮) est-elle celle qui est posée ?"""
    bs = se.view(m, ctx.voice)
    b = bs[j] if 0 <= j < len(bs) else None
    n = se.find_note(b, s) if b is not None else None
    if tool.id == "alt":
        return int(arg) in m.alt_ending
    if tool.id == "key":
        return m.key == int(arg)
    if tool.id in VALUES:
        return _cur(tool, m, b, n) == VALUES[tool.id][2][arg]
    return False


def _op_enabled(tid, m, bs, j, s, b, n, ctx) -> bool:
    if tid == "paste":
        return ctx.clip is not None and (b is not None or ctx.clip["kind"] == "bar")
    if tid in ("copy_m", "cut_m", "del_bar"):
        return True
    if b is None:
        return False
    if tid in ("mv_nu", "mv_nd", "semi_p", "semi_m", "oct_p", "oct_m", "del_note"):
        return n is not None
    if tid == "swap_l":
        return j > 0
    if tid == "swap_r":
        return j + 1 < len(bs)
    if tid in ("mv_bu", "mv_bd"):
        return bool(b.notes)
    return True


# ---------------------------------------------------------------------------------------------------------
# application

def _off(value):
    return False if isinstance(value, bool) else (0 if isinstance(value, int) else None)


def _set(obj, attr, value):
    setattr(obj, attr, copy.deepcopy(value))


def apply_tool(tool: Tool, m: Measure, j: int, s: int, ctx: Ctx, arg: str | None = None) -> Result:
    """Applique l'outil à la mesure `m` (une copie de travail). Lève ToolError si ce n'est pas possible."""
    ok, _ = tool_state(tool, m, j, s, ctx)
    if not ok:
        raise ToolError("Choisis d'abord " + ("une note (case) sur la partition" if tool.scope == "note" else "un temps sur la partition"))
    v = ctx.voice
    b = se.beats(m, v)[j] if j >= 0 and j < len(se.beats(m, v)) else None
    n = se.find_note(b, s) if b is not None else None
    if tool.id in BASES_TOOLS:
        se.set_duration(m, j, base=BASES_TOOLS[tool.id], v=v)
        return Result(beat=j)
    if tool.id == "alt":
        k = int(arg or 1)
        cur = list(m.alt_ending)
        m.alt_ending = sorted(set(cur) - {k}) if k in cur else sorted(set(cur) | {k})
        return Result(beat=j)
    if tool.id == "key":
        m.key, m.key_minor = max(-7, min(7, int(arg or 0))), False
        return Result(beat=j)
    if tool.id == "trill":
        n.trill = None if n.trill is not None else min(se.MAX_FRET, n.fret + 2)
        return Result(beat=j)
    if tool.id in VALUES:
        scope, attr, choices, clears = VALUES[tool.id]
        obj = _obj(scope, m, b, n)
        key = arg if arg is not None else next(iter(choices))
        if key not in choices:
            raise ToolError("Variante inconnue")
        cur = _cur(tool, m, b, n)
        if tool.id in ("pm", "lr"):
            was = bool(cur)
        elif arg is None and tool.more:
            was = bool(cur)                                                  # le bouton principal éteint n'importe quelle variante
        else:
            was = cur == choices[key]
        value = _off(choices[key]) if was else choices[key]
        _set(obj, attr, value)
        if not was:
            for a, val in clears:
                setattr(obj, a, val)
        if tool.id in ("pm", "lr"):                                          # le temps et ses notes disent la même chose
            for x in b.notes:
                setattr(x, attr, bool(value))
        return Result(beat=j)
    return _apply_op(tool.id, m, j, s, ctx, b, n)


def _clamp_string(n, nstr: int):
    n.string = max(0, min(nstr - 1, n.string))


def _apply_op(tid: str, m: Measure, j: int, s: int, ctx: Ctx, b: Beat | None, n) -> Result:
    v = ctx.voice
    nstr = len(ctx.tuning) or 6
    if tid == "rest":
        se.make_rest(m, j, v)
        return Result(beat=j)
    if tid == "ins":
        return Result(beat=se.insert_beat(m, j, b.base, v))
    if tid == "complete":
        if not se.complete_with_rests(m, v):
            raise ToolError("La mesure est déjà complète" if se.fill(m, v)[0] == se.fill(m, v)[1] else "La mesure est trop longue : raccourcis un temps")
        return Result(beat=j)
    if tid in ("semi_p", "semi_m", "oct_p", "oct_m"):
        step = {"semi_p": 1, "semi_m": -1, "oct_p": 12, "oct_m": -12}[tid]
        if not 0 <= n.fret + step <= se.MAX_FRET:
            raise ToolError(f"Hors du manche (cases 0 à {se.MAX_FRET})")
        n.fret += step
        n.dead = False
        return Result(beat=j)
    if tid in ("mv_nu", "mv_nd", "mv_bu", "mv_bd"):
        delta = -1 if tid.endswith("u") else 1
        movers = [n] if tid.startswith("mv_n") else list(b.notes)
        if len(ctx.tuning) < 2:
            raise ToolError("Accordage de la piste inconnu")
        taken = {x.string for x in b.notes if x not in movers}
        out = []
        for x in movers:
            ns = x.string + delta
            if not 0 <= ns < len(ctx.tuning):
                raise ToolError("Il n'y a plus de corde dans cette direction")
            if ns in taken or ns in [y[1] for y in out]:
                raise ToolError("La corde visée est déjà occupée")
            fret = ctx.tuning[x.string] + x.fret - ctx.tuning[ns]
            if not 0 <= fret <= se.MAX_FRET:
                raise ToolError("Cette hauteur n'existe pas sur la corde visée")
            out.append((x, ns, fret))
        for x, ns, fret in out:
            x.string, x.fret = ns, fret
        b.notes.sort(key=lambda x: x.string)
        return Result(beat=j, string=max(0, min(nstr - 1, s + delta)))
    if tid in ("swap_l", "swap_r"):
        k = j - 1 if tid == "swap_l" else j + 1
        bs = se.beats(m, v)
        bs[j], bs[k] = bs[k], bs[j]
        return Result(beat=k)
    if tid in ("copy_b", "cut_b"):
        clip = {"kind": "beat", "data": asdict(b)}
        if tid == "cut_b":
            se.make_rest(m, j, v)
        return Result(beat=j, clip=clip, msg="Temps copié" if tid == "copy_b" else "Temps coupé")
    if tid in ("copy_m", "cut_m"):
        clip = {"kind": "bar", "data": [asdict(x) for x in se.beats(m, v)]}
        if tid == "cut_m":
            m.voices[v] = se.rest_beats(m.length)
        return Result(beat=min(j, len(se.beats(m, v)) - 1), clip=clip, msg="Mesure copiée" if tid == "copy_m" else "Mesure coupée")
    if tid == "paste":
        return _paste(m, j, ctx, nstr)
    if tid == "del_note":
        se.set_fret(m, j, s, None, v)
        return Result(beat=j)
    if tid == "del_beat":
        return Result(beat=se.remove_beat(m, j, v))
    if tid == "del_bar":
        m.voices[v] = se.rest_beats(m.length)
        return Result(beat=0)
    raise ToolError("Outil inconnu")


def _paste(m: Measure, j: int, ctx: Ctx, nstr: int) -> Result:
    clip, v = ctx.clip, ctx.voice
    if not clip:
        raise ToolError("Rien à coller : copie d'abord un temps ou une mesure")
    new = [se._beat_from(copy.deepcopy(d)) for d in (clip["data"] if clip["kind"] == "bar" else [clip["data"]])]
    for b in new:
        for n in b.notes:
            _clamp_string(n, nstr)
    bs = se.beats(m, v)
    if clip["kind"] == "bar":
        m.voices[v] = new
        return Result(beat=0, msg="Mesure collée")
    bs[j] = new[0]
    return Result(beat=j, msg="Temps collé")


# ---------------------------------------------------------------------------------------------------------
# armure sur toute la fin de la piste (comme Songsterr)

def set_key_from(measures: list[Measure], first: int, key: int) -> list[int]:
    """Armure `key` de la mesure `first` jusqu'à la fin ; renvoie les mesures changées (leurs indices)."""
    changed = []
    for m in measures[first:]:
        if (m.key, m.key_minor) != (key, False):
            m.key, m.key_minor = key, False
            changed.append(m.index)
    return changed


def search(query: str) -> list[Tool]:
    """Outils dont le libellé ou l'aide contient `query` (sans tenir compte des accents ni de la casse)."""
    import unicodedata

    def norm(t: str) -> str:
        return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")
    words = norm(query).split()
    return [t for t in TOOLS if all(w in norm(t.label + " " + t.tip + " " + " ".join(x[1] for x in t.more)) for w in words)] if words else []
