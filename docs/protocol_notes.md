# Notes de protocole — NUX Mighty Plug Pro (USB-MIDI)

Toutes les infos ci-dessous ont été **vérifiées empiriquement** sur le device
réel (pas juste déduites du code source de mightier_amp).

## Ports MIDI (Windows)
> Section **déduite** (noms vus dans la config + comportement connu de Windows), pas encore
> confirmée par un test de rebranchement sur le device. À vérifier : noms de ports après
> rebranchement sur une autre prise USB, et détection d'un débranchement quand l'appli est au repos
> (la liste des ports de Windows peut rester périmée tant qu'un port est ouvert).

- mido nomme les ports `<nom> <index>` ; l'index est la position dans la liste (`NUX NMP-03 0` en entrée,
  `NUX NMP-03 1` en sortie car `Microsoft GS Wavetable Synth` occupe la sortie 0) et peut changer si un
  autre périphérique MIDI apparaît. Windows peut aussi préfixer le nom (`2- NUX NMP-03`) après un changement
  de prise USB.
- Conséquence : les ports sont retrouvés par mot-clé (`protocol.PORT_KEYWORD`), jamais par nom exact.

## Presets
- `program_change` standard, canal MIDI 1
- 7 presets (index 0 à 6)
- Bidirectionnel : le device notifie aussi les changements faits physiquement
- Pas d'écho de confirmation immédiat après un changement envoyé — c'est normal,
  pas un bug

## Tuner
- **Nécessite un SysEx d'activation, un simple CC ne suffit pas.**
- SysEx : `[0x43, 0x58, 0x70, 0x6F, 0x01, <on>, <mode>, <ref_pitch>, <muted>, 0, 0, 0]`
  - `0x43 0x58` : header vendor NUX
  - `0x70` : privacy "private"
  - `0x6F` : message type "tuner settings"
  - `0x01` : direction "set"
  - `<mode>` : melos reste toujours en mode 0 (chromatique) ; les accordages sont gérés côté PC
    (`midi/tunings.py`), les modes guitare/basse de l'ampli ne sont pas utilisés
  - `<muted>` : toujours 0 — le son de l'ampli n'est jamais coupé
  - `<ref_pitch>` : **hypothèse non validée** — octet = Hz − 430 (10 = 440 Hz), plage 430-450 Hz
    (`protocol.tuner_ref_byte`)
- Une fois activé, retour en CC :
  - CC 11 : état (1 = signal détecté ; ne reflète pas l'état d'activation → l'interrupteur de l'UI est un flag local)
  - CC 12 : **classe de hauteur (0-11) comptée à partir du LA, sans octave** — 0 = A, 2 = B, 5 = D, 7 = E, 10 = G.
    Pitch class réelle = `(cc12 + 9 + shift) % 12` (`protocol.tuner_pitch_class`). Les deux mi (grave et aigu) donnent
    donc la même valeur : melos les distingue par la corde choisie / déjà accordée (`midi/tunings.analyze`)
  - CC 71 : lit toujours 0 (numéro de corde inutilisable)
  - CC 72 : écart en cents, **≈ 50 = accordé**, échelle mesurée ×1 (1 unité ≈ 1 cent). Mesures avec cordes accordées :
    E grave 48, A 52, D 48, G 48, E aigu 54, **B 60** → le si lit environ +10 : melos garde un zéro par note
    (`cent_zero_notes`) en plus du zéro global. L'échelle exacte (cents réels par unité) reste à confirmer
    avec un accordeur de référence ; plage observée 35-69
- Mesures faites avec la guitare de l'utilisateur, un seul ampli : à reprendre si un autre Mighty se comporte autrement.

## Batterie d'accompagnement
- Direct en CC, pas de SysEx nécessaire
- CC 77 (DRUMENABLE), 78 (DRUMTYPE), 79 (DRUMLEVEL)
- **75 styles** : CC 78 = numéro affiché − 1 (0-74). Catégories (numéros affichés) : MET 1-8, ROCK 9-15, CTRY 16-22,
  BLUES 23-28, METAL 29-35, FUNK 36-42, JAZZ 43-49, BALD 50-56, POP 57-63, REGGAE 64-70, ELEC 71-75
  (`midi/drum_styles.py`). L'ancienne liste de 67 styles est fausse.
- Volume : le CC 79 couvre 0-127 mais la batterie devient trop forte dès ~25 ; le curseur 0-100 % de l'UI est ramené sur
  0-32 avec une courbe (`protocol.drum_level_from_percent`)
- CC 104/105/106 (EQ bass/middle/treble)
- Tempo : PAS un CC, passe par un SysEx `kSYX_DRUM` (0x19), même en-tête que le tuner (`43 58 70 19 <dir>`).
  Données (d'après mightier_amp, `sendDrumsTempo`) : `enabled, style, volume, bass, middle, treble, tempoH, tempoL`
  avec tempo = H*128 + L (2 octets 7 bits), plage 40-240. Il embarque TOUS les réglages batterie : on renvoie les valeurs
  courantes (cf `protocol.build_drum_sysex`). **Non testé sur le matériel** : à vérifier (le tempo change-t-il ? le motif
  redémarre-t-il si on change le tempo batterie en marche ?)

## Looper
- **N'existe PAS sur le Plug Pro.** Feature exclusive à la Mighty Space.
- Les CC 80/81/107 vus dans le code mightier_amp appartiennent à la classe
  partagée `PlugProCommunication`, mais l'interface `Looper` n'est implémentée
  que par `NuxMightySpace extends NuxMightyPlugPro implements Tuner, Looper`
- Conclusion : loop = 100% côté PC (sounddevice), dès la V1

## Format des messages en USB (vs BLE)
- Le code mightier_amp préfixe tout de `0x80, 0x80` (timestamp bytes BLE-MIDI)
- **En USB, ces 2 bytes sont absents** — mido gère ça nativement, on envoie
  juste le message MIDI standard sans préfixe

## Audio USB (Windows)
- Le Mighty expose une interface audio USB (entrée « Microphone (… NUX NMP-03) », sortie « Haut-parleurs (… NUX NMP-03) »).
  Les noms diffèrent selon l'API audio (MME tronque / préfixe `2-`), donc melos retrouve les périphériques par mot-clé
  (`system_volume_keyword`) quand on change d'API.
- Le volume Windows de la sortie du Mighty s'ajoute au curseur de l'appli : melos le remet à 100 % à l'ouverture du flux
  (`audio/system_volume.py`, désactivable).
- Latence : mesurée par l'utilisateur à ~250 ms de compensation avec l'API par défaut (MME, latence « high » de
  PortAudio) ; plus de latence perceptible en WASAPI avec latence « low ». Le moteur annonce les latences d'entrée et de
  sortie réellement obtenues (`stream.latency`), affichées dans les Réglages. Flux à 44,1 kHz : en WASAPI partagé,
  `auto_convert` rééchantillonne si la carte tourne à 48 kHz.