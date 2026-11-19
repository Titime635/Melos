# Melos

Logiciel en Python pour le **NUX Mighty Plug Pro**, qui transforme l'ampli en un écosystème de scène et de studio : loop station synchronisée, changements de preset automatiques, partitions interactives, éditeur de presets, le tout dans un seul poste de travail pensé pour jouer en live et créer.

## Fonctionnalités

- **Dashboard** : agencement libre par docks (glisser, redimensionner, retirer et remettre des modules), mode Édition / Performance séparé, modules adaptatifs qui réduisent leur contenu selon la place disponible, agencement sauvegardé automatiquement. L'onglet **Classique** conserve l'ancienne vue empilée.
- **Presets** : 7 presets colorés, changement en un clic, noms personnalisés, étiquettes de même taille qui passent en numéros quand la place manque.
- **Tuner** : un seul module avec jauge en arc et note détectée en grand, aiguille ♭ ← | → ♯ et affichage des cents. Standard / Eb standard / Drop D plus 23 accordages six cordes. Rangée de cordes toujours visible (clic sur une corde pour le mode manuel, aucune sélectionnée = automatique). La note passe au vert, avec un carillon optionnel, une fois accordée. Fréquence de référence, calibration (zéro, échelle, zéro par note) et transposition dans la fenêtre d'engrenage du module.
- **Batterie d'accompagnement et EQ** : 75 styles répartis en 11 catégories (onglets + favoris, icônes vectorielles), volume, graves / médiums / aigus.
- **Tempo** : BPM, signature (4/4, 6/8, 12/8, 3/4 ou personnalisée), click, pastilles de temps ; partagé par la loop station et la batterie.
- **Loop station** : boucles multipistes (base + pistes d'overdub supprimables indépendamment), quantification (Rec / Overdub / Stop attendent la mesure suivante, en suivant la batterie quand elle tourne), longueur automatique (arrêt après N mesures), décompte audio d'une mesure complète (attend la mesure suivante si une mesure est en cours), compensation de latence, volume, nombre de répétitions, limite de passes d'overdub.
- **Setlist** : séquences nommées par morceau, composées d'étapes de presets (avec label : « Couplet », « Refrain », « Solo »…), modes Play / Edit, vue de l'étape courante et des deux suivantes, navigation circulaire, interrupteur pour suspendre le contrôle de l'ampli sans perdre sa place.
- **Annuler / rétablir** : Ctrl+Z, Ctrl+Y / Ctrl+Maj+Z, **par page**. Sur le Dashboard, annule les réglages de modules et les changements d'agencement ; sur la page Raccourcis, les changements de raccourcis ; sur la page Partition, les marqueurs et la zone de boucle.
- **Partition** : recherche d'un morceau par son nom (ou collage d'un lien Songsterr), tablature qui défile en suivant la mesure courante, deux sources sonores, marque-pages, presets placés sur la partition, édition. Voir [Onglet Partition](#onglet-partition).
- **Éditeur de presets** : voir [Onglet Éditeur](#onglet-éditeur).
- **Page Réglages** : tout ce qui n'est pas déjà dans les réglages propres à un module :
  - audio du looper : entrée, sortie, bouton d'actualisation, **API audio** (WASAPI / MME / …), mode exclusif WASAPI, taille du tampon et latence réellement annoncée par PortAudio ;
  - port MIDI : automatique (trouve le Mighty) ou choix manuel ;
  - thème : clair, sombre ou « suit Windows » ;
  - mode des raccourcis, avec un lien vers la page Raccourcis ;
  - ouverture du dossier des réglages, export / import de tous les réglages, réinitialisation (agencement du Dashboard, noms des presets, ou tout) ;
  - rapport de diagnostic à copier (versions, ports MIDI, périphériques audio) et fichier journal.
- **Réglages persistants** : tout survit à un redémarrage et est renvoyé à l'appareil au lancement.

## Onglet Éditeur

Remplace MightyEditor (l'application `.exe` d'origine) par un éditeur intégré. Le principe : on **édite les presets de la bibliothèque** (la source de travail sur le PC), puis on décide où et quand les envoyer sur le Mighty.

- **Bibliothèque de presets** (à gauche) : presets nommés, étiquettes libres, recherche, filtre « Sur le Mighty / Hors Mighty ». Un fichier JSON par preset, écriture atomique.
- **7 emplacements du Mighty** : miroir de l'ampli. Un clic fait jouer l'emplacement par l'ampli. Chaque carte dit où en est son contenu par rapport à la bibliothèque : *joué*, *preset édité*, *à jour*, *à renvoyer*, *modifié sur l'ampli*, *hors bibliothèque*, *non lu*.
- **Chaîne d'effets** : les 9 blocs (COMP, EFX, AMP, EQ, GATE, MOD, DLY, RVB, IR), activables un à un et **réordonnables par glisser-déposer** (ou « Plus tôt / Plus tard »), plus le volume du preset.
- **Réglages d'un bloc** : choix du modèle et de chaque paramètre, d'après le catalogue complet de l'ampli (`editor/catalog_data.json`).
- **Écouter** : le preset édité part en direct dans le tampon d'édition de l'ampli, **sans rien écrire en flash** ; l'écoute s'arrête quand l'ampli change de preset.
- **Envoyer vers…** : écrit le preset dans un emplacement. Une fenêtre « Actuellement → Sera remplacé par » montre les deux chaînes d'effets en miniatures, avec les blocs qui changent soulignés. L'ancien contenu est sauvegardé automatiquement et l'association emplacement ↔ preset est mémorisée.
- **Historique** : chaque preset garde ses versions (la version d'origine est conservée) ; on peut comparer deux versions (liste des réglages qui changent) et revenir en arrière.
- **Sauvegardes automatiques** de l'ampli avant tout écrasement : aperçu, restauration, ou import dans la bibliothèque.
- **Import `.mppropatch`** (fichiers de MightyEditor) en lecture. L'**export** n'est pas encore possible : il demande les réponses impulsionnelles d'usine des baffles, à extraire de MightyEditor.exe.
- **Détection des modifications hors Melos** : au démarrage, l'ampli est relu et l'empreinte de chaque emplacement est comparée à ce que Melos y avait écrit.

Toute la conversation avec l'ampli passe par **une seule file, dans un thread dédié** : jamais deux échanges simultanés, et l'ordre des actions de l'utilisateur est respecté. Le protocole (SysEx, CC, format des 128 octets d'un preset) est documenté dans [`docs/editor_protocol.md`](docs/editor_protocol.md).

## Pile technique

- Python 3.12 (requis : `python-rtmidi` n'a pas de wheel PyPI au-delà de 3.12)
- PySide6 + PySide6-Fluent-Widgets (interface)
- `mido` / `python-rtmidi` (MIDI)
- `sounddevice` + `soundfile` (audio de la loop station)
- `keyboard` (raccourcis clavier globaux)
- QtWebEngine (fourni avec PySide6) qui héberge [alphaTab](https://alphatab.net) pour l'affichage de la partition et la synthèse MIDI
- `python-mpv` + `mpv-2.dll` (libmpv) pour l'audio original, avec `yt-dlp` pour résoudre le flux

## Démarrage

```bash
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe tools\setup_deps.py
.venv\Scripts\python.exe main.py
```

`tools\setup_deps.py` est l'étape supplémentaire après un clone ou un pull sur un nouvel ordinateur : il télécharge les gros fichiers qui ne sont **pas dans git** (voir [Fichiers hors git](#fichiers-hors-git)). Il ne récupère que ce qui manque (`--force` retélécharge tout), et `main.py` affiche un avertissement au démarrage si quelque chose est absent.

> Sous Windows, appelle directement `.venv\Scripts\python.exe` plutôt que d'activer le venv : la politique d'exécution de PowerShell bloque le script d'activation sur certaines machines.

Les tests sont de simples scripts Python (pas de pytest), lancés sans écran :

```bash
set QT_QPA_PLATFORM=offscreen
.venv\Scripts\python.exe tests\test_audio.py
```

Ils utilisent un faux clavier, un faux audio et un **faux Mighty** qui reproduit ce qui a été mesuré sur le vrai ampli : aucun matériel n'est nécessaire. Ils couvrent l'audio, la connexion, la quantification, les raccourcis, l'annulation, la setlist, le tuner, les onglets Partition et Éditeur (modèle, service et interface) et la bibliothèque de morceaux.

## Structure du projet

```
melos/
├── main.py                  # point d'entrée : relie MIDI / état / UI, renvoie les réglages restaurés à l'appareil
├── settings.py              # fichier de réglages JSON unique (app_settings.json)
├── paths.py                 # emplacements des fichiers de données et de journal
├── diagnostics.py           # rapport de diagnostic (page Réglages)
├── docs/
│   ├── protocol_notes.md    # protocole MIDI/SysEx vérifié empiriquement (contrôle, tuner, batterie)
│   └── editor_protocol.md   # protocole de l'éditeur de presets (lecture/écriture des emplacements)
├── midi/                    # constantes du protocole, listener (QThread), sender, moniteur de connexion,
│                            #   synchronisation d'état, styles de batterie, accordages
├── state/                   # AmpState (source de vérité unique), transport (tempo/quantification), session tuner, piles d'annulation
├── audio/                   # moteur de loop (callback sounddevice), config périphérique/API/tampon, utilitaires PortAudio
├── setlist/                 # séquences et lecture/navigation
├── editor/                  # éditeur de presets (sans dépendance Qt sauf service.py) :
│   │                        #   catalogue des effets, modèle d'un preset (128 octets), bibliothèque, établi,
│   │                        #   banque (miroir des 7 emplacements), liens emplacement ↔ preset, diff, fichiers .mppropatch,
│   │                        #   messages MIDI (wire), dialogue bloquant avec l'ampli (amp_io), service Qt à thread dédié
│   └── catalog_data.json    # modèles et paramètres de chaque bloc d'effet
├── tabs/                    # back end de l'onglet Partition : client + analyseur Songsterr, export alphaTex, paroles,
│   │                        #   synchro vidéo, mixeur de pistes, lecteur mpv (processus séparé), serveur web local,
│   │                        #   bibliothèque de morceaux, modifications de la partition (« Ma version »), outils d'édition
│   ├── web/tab_view.html    # la page de partition (alphaTab) : mise en page, curseur, synthé MIDI, mixeur, pont JS <-> Python
│   └── vendor/              # téléchargé, hors git : alphaTab, police Bravura, soundfonts (.sf2)
├── shortcuts/               # raccourcis clavier : catalogue d'actions, gestionnaire de touches, routeur d'actions
├── ui/                      # modules Fluent-widgets, Dashboard (docks), pages Réglages, Raccourcis, Partition et Éditeur,
│                            #   fenêtres flottantes (Morceaux, Marque-pages, Presets), palette d'édition de partition
├── tools/                   # setup_deps.py et scripts fetch_*.py, sonde de presets, vérifs codec/mpv, sonde Songsterr
└── tests/                   # scripts de test sans écran (faux audio / MIDI / clavier / Mighty)
```

## Feuille de route

- **V1 — Socle** ✅ presets, setlist, batterie, loop station, persistance
- **V2 — Ergonomie et fiabilité** ✅ dashboard, raccourcis clavier, quantification looper/batterie et longueur automatique du looper, état de connexion en direct, refonte des modules, annuler/rétablir par page, page Réglages
- **V3 — Partition et édition des presets** ✅
  - Tablature Songsterr synchronisée avec l'enregistrement original
  - Solo / mute des instruments
  - Paroles
  - Synthèse MIDI de la partition (choix de soundfont, variantes d'instruments)
  - Changements de preset placés sur la partition et envoyés à l'ampli quand la lecture atteint la mesure
  - **Éditeur de presets** reconstruit dans l'appli (V3.5) : bibliothèque, emplacements, chaîne d'effets, écoute, envoi, historique, sauvegardes
- **V4 — Matériel et audio pro** :
  - Pédalier Arduino
  - Enregistrement brut + ré-amplifié (re-amping)
  - Partitions avancées : déjà en place — boucle, vitesse, marque-pages, édition des notes, durées et tempo (« Ma version »), export MIDI ; reste la transposition, les commentaires sur un passage et la gestion avancée des pistes audio
  - « Mode musique » dédié, avec la frise temporelle du morceau
- **V5 — IA** : orchestration via JARVIS, auto-configuration des réglages de l'ampli

## Onglet Partition

Usage personnel : les tablatures appartiennent à Songsterr et à leurs auteurs ; elles sont mises en cache en local (`tabs_cache/`) et jamais redistribuées. Les points d'accès de Songsterr ne sont pas documentés et peuvent changer (`tools/songsterr_probe.py` les sonde de nouveau). Aucun audio n'est téléchargé ni stocké.

- **Recherche** : tape le nom d'un morceau dans le champ (une liste de résultats s'ouvre dessous, souris ou flèches + Entrée) ou colle un lien Songsterr. Le bouton ↻ ignore le cache et redemande le morceau à Songsterr.
- **Morceaux** : fenêtre flottante avec les morceaux récents et les favoris (★), avec recherche. Ouvrir un morceau le remet en tête de l'historique et retrouve la piste et la vidéo choisies la dernière fois ; l'historique est borné, les favoris ne sont jamais éliminés.
- **Partition** : rendue par alphaTab dans QtWebEngine en deux passes (largeurs naturelles des mesures, puis ajustement à la fenêtre) ; un instrument à la fois, changé depuis la liste des pistes sans interrompre le son. La mesure courante suit la musique ; les paroles sont placées sous les notes de toutes les pistes, alignées sur la ligne de chant. Zoom (Ctrl + / − / 0).
- **Deux sources sonores, un seul interrupteur (Original / Synthèse)** ; la position et l'état de lecture sont conservés au changement.
  - *Original* : l'enregistrement réel, lu par mpv en audio seul dans un processus séparé (barre de commandes propre : lecture, position, vitesse 0,25×–1,5×, volume). Songsterr publie plusieurs vidéos synchronisées sur les mêmes mesures (mix complet, instruments isolés, backing track) : les boutons **solo / mute** de la liste des pistes choisissent la vidéo correspondante et ne sont actifs que pour les combinaisons qui existent. L'engrenage de la liste des pistes ouvre la **version audio** et l'**association des pistes**, qui permet de relier à la main une piste audio à un instrument (mémorisé par morceau).
  - *Synthèse* : toute la partition jouée par le synthétiseur d'alphaTab (tous les instruments, pas seulement celui affiché). **Solo / mute / volume par instrument** (mémorisés par morceau), métronome, décompte, boucle (glisse sur des mesures pour choisir une zone, sinon tout le morceau), vitesse, clic sur la partition pour se déplacer, et **export MIDI**. Un **menu de soundfonts** apparaît quand plusieurs banques `.sf2` sont installées ; **GeneralUser GS** est la valeur par défaut, Sonivox le secours léger.
  - *Variantes d'instruments* : chaque piste utilise le programme General MIDI du premier son Songsterr (saturation, overdrive, clean… sont des programmes différents), et les changements de son en cours de morceau (`trackSoundAutomations`) sont appliqués au bon temps. Accents et notes fantômes de la batterie conservés.
- **Marque-pages** : fenêtre flottante par morceau. Ctrl+B pose / retire un marque-page à la mesure courante, Ctrl+← / → saute au précédent / suivant ; un clic sur une ligne saute à la mesure ; renommage et suppression.
- **Presets sur la partition** : fenêtre flottante « Presets » avec deux pages.
  - *Sur ce morceau* : la liste des changements (mesure, preset, état) ; un clic saute à la mesure.
  - *Ajouter* : les presets de la bibliothèque de l'Éditeur, avec filtre ; on clique un preset (il se place à la mesure visée) ou on le **glisse sur la partition**. Un preset déjà chargé dans l'ampli porte le numéro de son emplacement ; un preset « non chargé » se pose quand même mais n'enverra rien tant qu'il n'a pas été envoyé depuis l'Éditeur.
  - À la lecture, quand la partition atteint une mesure marquée, le changement de preset est envoyé à l'ampli.
- **Édition (« Ma version »)** : le bouton crayon ouvre une palette d'outils équivalente à celle de Songsterr, rangée en onglets (Temps, Notes, Mesure, Édition), avec une recherche. Les boutons sont grisés quand ils ne s'appliquent pas à la sélection et allumés quand l'effet est déjà posé. On peut changer des notes, des durées, des effets, le tempo… **L'original de Songsterr n'est jamais touché** : « Ma version » = l'original + une liste de changements rangés dans la bibliothèque. Les changements sont à la mesure ou au tempo, et le nombre de mesures ne change jamais, donc les points de synchro de la vidéo restent valables ; défaire un changement revient à retirer son entrée.

## Fichiers hors git

Trop gros ou reproductibles, ils sont dans `.gitignore` et installés par `tools\setup_deps.py` (ou par chaque script seul) :

| Fichier | Taille | Script | Sert à |
|---|---|---|---|
| `mpv-2.dll` (racine du dépôt) | ~115 Mo | `tools\fetch_libmpv.py` | audio original (libmpv, Windows 64 bits, builds shinchiro) |
| `tabs/vendor/alphatab/` (alphaTab 1.8.4, police Bravura, soundfont Sonivox) | ~5 Mo | `tools\fetch_alphatab.py` | rendu de la partition et synthétiseur |
| `tabs/vendor/alphatab/soundfont/GeneralUser-GS.sf2` | ~32 Mo | `tools\fetch_soundfonts.py` | meilleurs sons de synthèse (facultatif) |

Autres fichiers locaux également ignorés : `app_settings.json`, `setlists.json`, `tabs_cache/`, `web_profile/` (profil QtWebEngine), `preset_library/` (bibliothèque de presets de l'Éditeur), `preset_backups/` (sauvegardes de l'ampli), `preset_slot_links.json` (associations emplacement ↔ preset), `probe_out/`, `probe_presets_out/`, `melos_lyrics.txt` et les fichiers `*.log`. Pour ajouter une autre banque `.sf2`, dépose-la dans `tabs/vendor/alphatab/soundfont/` : elle apparaît dans le menu des soundfonts.

## Composants tiers

[alphaTab](https://alphatab.net) (MPL-2.0), police Bravura (SIL OFL), soundfont Sonivox fournie avec alphaTab, [GeneralUser GS](https://github.com/mrbumpy409/GeneralUser-GS) de S. Christian Collins (sa propre licence d'utilisation libre), [mpv](https://mpv.io) / libmpv, données Songsterr pour un usage personnel. Le catalogue des effets de l'Éditeur provient de MightyEditor ; l'agencement des octets d'un preset et les numéros de CC viennent de Mightier Amp et ont été vérifiés sur l'ampli.

## Gestion de la connexion

- L'appli démarre avec ou sans le Mighty branché. Un indicateur de la barre de navigation montre toujours l'état de la connexion, et un bandeau apparaît tant qu'il est débranché.
- Les modules restent modifiables hors connexion ; l'état de l'appli est renvoyé à l'ampli à la (re)connexion, exactement comme au lancement.
- Le port MIDI est trouvé par mot-clé (« NUX NMP-03 ») par défaut ; la page Réglages permet d'imposer une entrée / sortie précise (sans repli silencieux si le port choisi est absent).
- La loop station suit l'interface audio USB de l'ampli : flux arrêté à la déconnexion (prise en cours annulée, pistes existantes conservées), relancé à la reconnexion.
- L'Éditeur relit l'ampli à la connexion et signale tout emplacement modifié en dehors de Melos.

## Latence audio

Le flux demande la latence **basse** du périphérique (celle de PortAudio par défaut est la « haute », 100 ms et plus par sens avec MME). Sous Windows, **WASAPI** (sélectionné automatiquement quand il est disponible) est bien plus rapide que MME ; le mode exclusif WASAPI descend encore plus bas mais prive les autres applications de la carte son. La page Réglages affiche la latence annoncée par PortAudio pour le flux ouvert. La « compensation de latence » du looper ne décale que le contenu *enregistré* des prises : elle ne bouge jamais le click, l'affichage ni la batterie.

## Raccourcis clavier

- Trois modes : désactivés, fenêtre active seulement, ou global (fonctionne quand une autre fenêtre a le focus), modifiables depuis la barre de navigation et la page **Raccourcis**. **Aucune touche par défaut** : tu les choisis sur cette page (Échap annule une capture ; une touche déjà utilisée par une autre action est refusée).
- Actions : presets 1–7, suivant / précédent, loop station (une touche cyclique enregistrer → lire → overdub **et** des touches séparées : enregistrer, overdub, lecture/arrêt, effacer), plus **batterie on/off** et **métronome on/off**. « Effacer » ne se déclenche qu'en **maintenant la touche ~1 s**.
- Suivant / précédent suivent la setlist quand elle est active (interrupteur sur ON + une séquence avec des étapes), sinon parcourent les presets (en boucle).
- Les raccourcis pilotent la vue affichée (Dashboard et Classique ont chacun leur loop station et leur setlist) ; sur la page Raccourcis, ils continuent de piloter la dernière vue visitée.
- Une simple lettre / chiffre / Espace / Entrée seule se déclenche partout tant que les raccourcis sont actifs : la page le signale ; préfère les touches F ou une combinaison Ctrl / Alt.

## Particularités connues du protocole

- Les noms de ports MIDI ne sont pas stables sous Windows (`NUX NMP-03 0`, `2- NUX NMP-03`…) : les ports sont trouvés par mot-clé, jamais par nom exact (sauf s'ils sont imposés à la main dans les Réglages).
- Les presets n'envoient aucun écho de confirmation pour les commandes venant de l'hôte : l'UI se met à jour de façon optimiste au lieu d'attendre l'appareil.
- Tuner : le CC 12 est la classe de hauteur comptée depuis le La (0 = La, 5 = Ré, 7 = Mi, 10 = Sol, 2 = Si), sans octave ; le CC 72 ≈ 50 quand c'est accordé (cents, avec un petit décalage par note sur certaines notes, ex. Si) ; le CC 71 vaut toujours 0 ; le CC 11 reflète la détection du signal et non l'état d'activation : l'interrupteur on/off est donc piloté par un drapeau local.
- Éditeur : changer de preset **efface les modifications non enregistrées** du tampon d'édition de l'ampli, et les modifications par CC n'agissent que sur le preset courant. L'appli garde donc une copie de travail et la renvoie. Les octets du tempo / drapeaux du delay ne sont pas modifiables par CC : ils sont conservés mais pas poussés.
- Le Plug Pro n'a pas de looper matériel : le bouclage est entièrement logiciel (`sounddevice`).

Voir `docs/protocol_notes.md` et `docs/editor_protocol.md` pour la référence MIDI/SysEx complète, vérifiée empiriquement.

## Licence

MIT, voir [`LICENSE`](LICENSE).