"""Fenêtre « Association des pistes » : choisir à la main quelle piste audio de Songsterr correspond à chaque
instrument de la partition (pour isoler / couper). Le résultat est mémorisé par morceau."""

from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QVBoxLayout
from qfluentwidgets import BodyLabel, CaptionLabel, ComboBox, PrimaryPushButton, PushButton, isDarkTheme

AUTO, NONE = "__auto__", "__none__"


class StemDialog(QDialog):
    def __init__(self, tracks, stems: list[str], titles: dict[str, str], auto: list[set], current: dict, parent=None):
        """`tracks` : pistes ; `stems` : pistes audio disponibles ; `titles` : stem -> nom de la vidéo « solo » qui la
        contient seule ; `auto` : association automatique par piste ; `current` : {indice: ensemble} choisi à la main."""
        super().__init__(parent)
        self.setWindowTitle("Association des pistes audio")
        self.setMinimumWidth(620)
        self.setObjectName("stemDialog")
        self.setStyleSheet("#stemDialog{background:%s}" % ("#272727" if isDarkTheme() else "#f3f3f3"))
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(BodyLabel("Quelle piste audio correspond à chaque instrument ?", self))
        lay.addWidget(CaptionLabel("Utilisé par les boutons isoler / couper. Les choix sont mémorisés pour ce morceau.", self))
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        self._boxes: list[ComboBox | None] = []
        label = lambda s: f"{s}  ·  {titles[s]}" if titles.get(s) else s
        for i, t in enumerate(tracks):
            sub = t.name.split(" | ")
            name = f"{t.instrument or 'Piste'}  —  {' | '.join(sub[:3])}"
            box = ComboBox(self)
            auto_txt = ", ".join(sorted(auto[i])) or "aucune"
            box.addItem(f"Automatique  ({auto_txt})", userData=AUTO)
            box.addItem("Aucune (ne pas isoler / couper)", userData=NONE)
            for s in stems:
                box.addItem(label(s), userData=s)
            if i in current:
                chosen = sorted(current[i])
                box.setCurrentIndex(box.findData(chosen[0]) if chosen else 1)
            box.setMinimumWidth(320)
            form.addRow(BodyLabel(name, self), box)
            self._boxes.append(box)
        lay.addLayout(form)
        row = QHBoxLayout()
        row.addStretch(1)
        reset = PushButton("Tout en automatique", self)
        reset.clicked.connect(lambda: [b.setCurrentIndex(0) for b in self._boxes])
        ok = PrimaryPushButton("Enregistrer", self)
        ok.clicked.connect(self.accept)
        cancel = PushButton("Annuler", self)
        cancel.clicked.connect(self.reject)
        for w in (reset, cancel, ok):
            row.addWidget(w)
        lay.addLayout(row)

    def result_map(self) -> dict[int, set[str]]:
        out: dict[int, set[str]] = {}
        for i, box in enumerate(self._boxes):
            data = box.currentData()
            if data == NONE:
                out[i] = set()
            elif data not in (AUTO, None):
                out[i] = {data}
        return out