# Checklist de test manuel pour la détection de connexion

## Scénarios à tester

### 1. État idle (aucune activité)
- [ ] Lancer l'app avec le Mighty débranché → Vérifier que l'indicateur de connexion est rouge et que la bannière d'avertissement apparaît
- [ ] Brancher le Mighty → Vérifier que l'indicateur devient vert, que la bannière d'avertissement disparaît, et qu'une bannière "Connecté" apparaît brièvement (2s)
- [ ] Débrancher le Mighty → Vérifier que l'indicateur devient rouge et que la bannière d'avertissement réapparaît
- [ ] Re-brancher le Mighty → Vérifier la reconnexion comme ci-dessus

### 2. Tuner actif
- [ ] Activer le tuner via l'interface
- [ ] Débrancher le Mighty → Vérifier que le tuner reste actif dans l'UI (pas de réinitialisation) et que l'indicateur de connexion devient rouge + bannière d'avertissement
- [ ] Re-brancher le Mighty → Vérifier la reconnexion et que le tuner reste actif
- [ ] Désactiver le tuner → Vérifier que l'état est correctement conservé

### 3. Batterie active
- [ ] Activer la batterie via l'interface
- [ ] Jouer quelques motifs pour vérifier qu'ils fonctionnent (quand connecté)
- [ ] Débrancher le Mighty → Vérifier que la batterie reste activée dans l'UI et que l'indicateur de connexion devient rouge + bannière d'avertissement
- [ ] Re-brancher le Mighty → Vérifier la reconnexion et que la batterie reste active
- [ ] Désactiver la batterie → Vérifier que l'état est correctement conservé

### 4. Loop en enregistrement
- [ ] Démarrer un enregistrement en boucle
- [ ] Pendant l'enregistrement, débrancher le Mighty → Vérifier que l'enregistrement continue (puisque c'est 100% logiciel) et que l'indicateur de connexion devient rouge + bannière d'avertissement
- [ ] Re-brancher le Mighty → Vérifier la reconnexion
- [ ] Arrêter l'enregistrement et vérifier que la boucle est correctement capturée

### 5. Lancement à froid sans appareil
- [ ] Quitter l'application
- [ ] Débrancher le Mighty
- [ ] Lancer l'application → Vérifier que l'indicateur de connexion est rouge et que la bannière d'avertissement apparaît (pas de flash "déconnecté")
- [ ] Brancher le Mighty → Vérifier la reconnexion comme ci-dessus
- [ ] Effectuer quelques opérations (changer preset, activer tuner, etc.) pour vérifier que l'UI reste fonctionnelle

### 6. Vérifications spécifiques
- [ ] Aucun crash ou exception MIDI ne doit se produire en cas de déconnexion
- [ ] Tous les paramètres doivent être conservés lors des déconnexions/reconnexions
- [ ] L'indicateur de connexion permanent doit toujours être visible (vert quand connecté, rouge quand déconnecté)
- [ ] La bannière d'avertissement doit être persistante tant que déconnecté
- [ ] La bannière "Connecté" doit apparaître brièvement (2s) après chaque reconnexion
- [ ] Au lancement avec appareil branché : pas de flash "déconnecté", l'indicateur doit être vert immédiatement
- [ ] Le délai de ~300-500ms avant de pousser l'état vers le device doit être respecté (vérifiable expérimentalement)

### 7. Test de la boucle audio (optionnel, si implémenté)
- [ ] Démarrer la lecture ou l'enregistrement en boucle
- [ ] Débrancher le Mighty (qui est aussi l'interface audio) → Vérifier que la boucle audio continue si possible, ou s'arrête proprement
- [ ] Re-brancher le Mighty → Vérifier que l'audio se rétablit automatiquement si les mêmes devices sont disponibles