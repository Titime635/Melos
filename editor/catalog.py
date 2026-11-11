"""
Catalogue du Mighty Plug Pro : pour chaque bloc d'effet, la liste des modèles et de leurs paramètres
(nom, plage, défaut). Les données viennent de MightyEditor (editor/catalog_data.json) ; l'agencement des
octets d'un preset et les numéros de CC viennent de Mightier Amp et ont été vérifiés sur l'ampli
(cf tools/probe_presets.py).

Un preset = 128 octets (identique en lecture SysEx USB et dans un .mppropatch) :
    0        WAH (absent du Plug Pro, conservé tel quel)
    1..9     octet de type de chaque bloc : bits 0-5 = modèle (1..), bit 6 (0x40) = bloc désactivé
    10       SR (conservé tel quel)
    14,19... octets « nombre de paramètres » de chaque bloc, suivis des paramètres
    84       volume du preset ; 85-87 drapeau/tempo du delay ; 88 BITCTRL
    89..99   ordre des blocs (valeurs 1..9 entre un 0 et un 10)
    100..115 nom interne (16 octets, « NULL » sur les presets d'usine de l'utilisateur)
    116..127 12 octets de fin conservés tels quels
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

PRESET_LEN = 128
IDX_MASTER = 84
IDX_LINK1, LINK_COUNT = 89, 11
IDX_NAME, NAME_LEN = 100, 16
CC_MASTER = 73
DISABLED_BIT = 0x40
MODEL_MASK = 0x3F
MASTER_MAX = 100
PERCENT_MAX = 100

_DATA = Path(__file__).with_name("catalog_data.json")


@dataclass(frozen=True)
class ParamDef:
    name: str
    offset: int                    # position dans les paramètres du bloc (0 = premier)
    kind: str                      # "percent" (0-100) | "choice" (valeurs listées)
    default: int
    choices: tuple = ()            # ((valeur, libellé), ...) pour kind == "choice"

    def clamp(self, v: int) -> int:
        v = int(v)
        if self.kind == "choice":
            allowed = [c[0] for c in self.choices]
            return v if v in allowed else self.default
        return max(0, min(PERCENT_MAX, v))


@dataclass(frozen=True)
class ModelDef:
    index: int
    name: str
    params: tuple                  # tuple[ParamDef]
    link: dict | None = None       # ampli : baffle associé par défaut {"cab","level","low_cut","high_cut"}


@dataclass(frozen=True)
class EffectDef:
    id: int                        # 1..9 : octet de type = index dans le preset ET numéro de CC de sélection
    key: str                       # CMP, EFX, AMP, EQ, NG, MOD, DLY, RVB, CAB
    label: str
    count_index: int
    param_index: int               # index du premier paramètre dans le preset
    param_slots: int               # nombre d'octets de paramètres réservés
    cc_base: int                   # CC du premier paramètre
    models: dict = field(default_factory=dict)   # {index: ModelDef}

    def model(self, index: int) -> ModelDef | None:
        return self.models.get(index)

    def cc_for(self, offset: int) -> int:
        return self.cc_base + offset


class Catalog:
    def __init__(self, path: Path = _DATA):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        self.effects: dict[int, EffectDef] = {}
        for e in raw["effects"]:
            models = {}
            for idx, m in e["models"].items():
                params = tuple(ParamDef(p["name"], p["offset"], p["kind"], p["default"],
                                        tuple((c[0], c[1]) for c in p.get("choices", ())))
                               for p in m["params"])
                models[int(idx)] = ModelDef(int(idx), m["name"], params, m.get("link"))
            self.effects[e["id"]] = EffectDef(e["id"], e["key"], e["label"], e["count_index"], e["param_index"],
                                              e["param_slots"], e["cc_base"], models)
        self.by_key = {e.key: e for e in self.effects.values()}
        self.cab_by_name = {m.name: m.index for m in self.effects[9].models.values()}

    def __iter__(self):
        return iter(self.effects.values())


_catalog: Catalog | None = None


def get_catalog() -> Catalog:
    global _catalog
    if _catalog is None:
        _catalog = Catalog()
    return _catalog
