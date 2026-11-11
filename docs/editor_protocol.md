# Éditeur de presets — protocole vérifié sur le Mighty Plug Pro (USB)

Relevés faits avec `tools/probe_presets.py` sur l'ampli (nov. 2026). Les SysEx sont ceux de l'USB-MIDI : un seul
message par réponse, sans l'en-tête `0x80 0x80` du Bluetooth. En-tête `F0 43 58 70`, fin `F7`.

| Action | Envoi | Réponse |
|---|---|---|
| Lire l'emplacement n (mémoire flash) | `0B 02 <n>` | `0B 02 <n>` + 128 octets |
| Lire le preset courant (avec modifs non enregistrées) | `0C 02` | `0C 02 <n courant>` + 128 octets |
| Lire l'ordre des blocs | `0D 02` | `0D 02 <9 blocs>` |
| Changer l'ordre | `0D 01 09 <9 blocs>` | `0D 02 …` (~0,5 s) |
| Enregistrer le preset courant dans n | `75 01 30 <n>` | `B0 7F 01` puis `75 03 30 <n> 00…` (0,25–1 s) |
| Changer de preset | Program Change n (canal 1) | — (le tampon d'édition est rechargé depuis la flash) |

* Les modifications par CC n'agissent que sur le preset courant (tampon d'édition) : `0x0B` ne les voit pas, `0x0C` oui.
  Changer de preset les efface → l'appli garde une copie de travail et la renvoie (`editor/bank.py`).
* Rechargement complet par CC : 69 messages (9 blocs × [sélection + paramètres] + volume + ordre), conforme dès 0 ms de
  pause entre messages (24 ms au total).
* Un preset = 128 octets (identique dans un `.mppropatch`). Octets 0–83 blocs, 84 volume, 85–88 tempo/drapeaux du delay
  (non modifiables par CC : conservés mais non poussés), 89–99 ordre, 100–115 nom interne, 116–127 fin constante.
* Réglages du baffle (IR) : octets 78, 79, 80 (niveau, coupe-bas, coupe-haut) — les octets 75–77 sont conservés tels quels.
* Octet de type d'un bloc : bits 0–5 = modèle (1…), bit 6 (0x40) = bloc désactivé.
