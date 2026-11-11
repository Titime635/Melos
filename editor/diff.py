"""Différences lisibles entre deux presets (comparaison de versions)."""

from dataclasses import dataclass

from .catalog import get_catalog
from .preset import Preset

# Noms des blocs tels que MightyEditor les affiche (le catalogue garde CMP, NG, CAB…)
BLOCK_NAMES = {1: "COMP", 2: "EFX", 3: "AMP", 4: "EQ", 5: "GATE", 6: "MOD", 7: "DLY", 8: "RVB", 9: "IR"}


@dataclass
class Change:
    fid: int | None          # bloc concerné (None : réglage général)
    kind: str                # enabled | model | param | order | master
    label: str               # « Gain », « Modèle », « Activation »…
    old: str
    new: str


def _fmt(pdef, v: int) -> str:
    if pdef.kind == "choice":
        for val, name in pdef.choices:
            if val == v:
                return name
    return str(v)


def diff_presets(a: Preset, b: Preset) -> list[Change]:
    """Ce qui change en passant de `a` à `b`."""
    cat = get_catalog()
    out: list[Change] = []
    for fid in a.order:
        e = cat.effects[fid]
        if a.enabled(fid) != b.enabled(fid):
            out.append(Change(fid, "enabled", "Activation", "activé" if a.enabled(fid) else "désactivé",
                              "activé" if b.enabled(fid) else "désactivé"))
        ma, mb = e.model(a.model(fid)), e.model(b.model(fid))
        if a.model(fid) != b.model(fid):
            out.append(Change(fid, "model", "Modèle", ma.name if ma else "?", mb.name if mb else "?"))
            continue                                           # les réglages d'un autre modèle ne se comparent pas
        for p in (ma.params if ma else ()):
            va, vb = a.param(fid, p.offset), b.param(fid, p.offset)
            if va != vb:
                out.append(Change(fid, "param", p.name, _fmt(p, va), _fmt(p, vb)))
    if list(a.order) != list(b.order):
        out.append(Change(None, "order", "Ordre des blocs", " › ".join(BLOCK_NAMES[f] for f in a.order),
                          " › ".join(BLOCK_NAMES[f] for f in b.order)))
    if a.master != b.master:
        out.append(Change(None, "master", "Volume", str(a.master), str(b.master)))
    return out
