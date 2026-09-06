# Notes de protocole — NUX Mighty Plug Pro (USB-MIDI)

Toutes les infos ci-dessous ont été **vérifiées empiriquement** sur le device
réel (pas juste déduites du code source de mightier_amp).

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
- Une fois activé, retour en CC :
  - CC 11 : état (1 = actif)
  - CC 12 : note MIDI détectée
  - CC 71 : numéro de corde (non testé en détail)
  - CC 72 : écart en cents — **zéro exact non confirmé**, plage observée 35-69
    pendant le test, à recalibrer avec une corde accordée de référence

## Batterie d'accompagnement
- Direct en CC, pas de SysEx nécessaire
- CC 77 (DRUMENABLE), 78 (DRUMTYPE), 79 (DRUMLEVEL)
- CC 104/105/106 (EQ bass/middle/treble)
- Tempo : PAS un CC, passe par un SysEx différent (`kSYX_DRUM`, tempo encodé
  sur 2 bytes 7-bit) — **non testé empiriquement**, à valider avant de l'utiliser

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
