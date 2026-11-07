# 06 - Risques et vérifications

## 1. À vérifier avant de coder

Ces points n'ont pas été vérifiés le 2026-11-07. Chacun dit comment le vérifier et ce qui change selon le résultat.

| # | Point | Comment vérifier | Impact si le résultat est mauvais |
| :--- | :--- | :--- | :--- |
| V1 | Que devient un événement si le **géocodage échoue** (`location` nul ?) | Lire `event.service.ts` (création) et `geocoding.service.ts` ; créer un événement avec une adresse invalide sur une base de test | Un événement sans coordonnées est absent de la recherche par zone (`ST_DWithin`) : invisible dans le direct |
| V2 | Le **formulaire de création** accepte-t-il un début maintenant ou dans le passé ? | Lire `nativapp/src/screens/event/EventFormScreen.tsx` | S'il refuse, le seed (LE-04) est la seule source de démonstration |
| V3 | Les messages **entrants** traversent-ils le proxy de la gateway ? | Se connecter par la gateway avec `socket.io-client` et émettre un message ; l'observer côté `ws-service` | Si non, le palier 4 demande de modifier le proxy |
| V4 | OSRM piéton : le service `table` et `geometries=geojson` fonctionnent-ils ? Le `User-Agent` est-il envoyé tel quel par React Native ? | Commandes ci-dessous, puis test sur appareil | Sans `table` : un appel `route` par candidat, espacés (plus lent). Sans `User-Agent` : risque de blocage par l'hôte |
| V5 | `@volontariapp/logger` **masque-t-il** `latitude` et `longitude` ? | Lire la skill `volontariapp-logger` et la configuration de masquage | Sinon ajouter ces clés au masquage dans LE-08, ou ne jamais logger les objets de position |
| V6 | `ws-service` expose-t-il déjà un contrôleur HTTP ? La politique réseau autorise-t-elle sa sortie vers Redis ? | Lire `ws-service/src/main.ts` et la fin de `ws-service.yaml` (seules les 60 premières lignes ont été lues) | Sans HTTP : ajouter un module HTTP. Sans sortie Redis : lot `deploy` supplémentaire |
| V7 | Format de sérialisation des `statuses` (tableau) dans la requête `GET /events` | Lire le `@Transform` du DTO (`search-events.request.dto.ts`, autour des lignes 50-56) et un appel existant côté `nativapp` | Erreur 400 ou filtre ignoré |
| V8 | La gateway **conserve-t-elle l'ordre** de distance renvoyé par `ms-event` ? | Lire `SearchEventsResponseDTO.fromResponse` | Aucun : le client retrie à vol d'oiseau |
| V9 | Le `ValidationPipe` de la gateway **rejette-t-il un paramètre inconnu** (`endAtFrom` avant déploiement) ? | Lire sa configuration (`whitelist`, `forbidNonWhitelisted`) | Si oui, LE-10 ne doit pas être fusionnée avant le déploiement de LE-07 (déjà prévu) |
| V10 | Texte de la permission de localisation (iOS) | Lire `nativapp/app.config.js` | Le texte doit mentionner le partage éventuel avec l'organisateur |

Commandes de test OSRM (V4) :

```bash
curl -s -A "volontariapp-demo/0.1" "https://routing.openstreetmap.de/routed-foot/table/v1/foot/2.3522,48.8566;2.3376,48.8606;2.3200,48.8700?sources=0&annotations=duration"
```

```bash
curl -s -A "volontariapp-demo/0.1" "https://routing.openstreetmap.de/routed-foot/route/v1/foot/2.3522,48.8566;2.3376,48.8606?overview=full&geometries=geojson"
```

## 2. Risques

| # | Risque | Gravité | Réponse prévue |
| :--- | :--- | :--- | :--- |
| R1 | Aucun événement en cours dans les données de démo : l'écran paraît cassé | Élevée | LE-04 (seed) ; V2 |
| R2 | Événement complet non détecté : l'échec du comptage de participants est silencieux (valeur de `ms-event`, probablement 0) | Moyenne | Accepté pour la démo ; le serveur ne bloque pas non plus la participation ; LE-12 en option |
| R3 | OSRM public indisponible ou limité (1 requête par seconde, aucune garantie) | Moyenne | File d'attente, cache de 60 s, repli à vol d'oiseau marqué "estimé" |
| R4 | Suivi d'une personne par un tiers (partage de position) | **Élevée** | ADR-6 : organisateur seul, désactivé par défaut, arrondi 100 m, TTL, arrêt à l'arrivée, aucun historique |
| R5 | Fuite de coordonnées dans les journaux | Élevée | Règle d'équipe, V5, test ou relecture dans LE-08 et LE-09 |
| R6 | `nativapp` envoie `endAtFrom` avant le déploiement du back : 400 possible (V9) | Moyenne | LE-10 fusionnée après le déploiement de LE-06 et LE-07 |
| R7 | Deux bumps concurrents de `@volontariapp/contracts` (PR A automatique et PR B manuelle) | Moyenne | A d'abord, B rebasée sur A |
| R8 | Le verrou STOP bloque les sous-agents d'une session qui a édité `proto-registry` ou `npm-packages` | Moyenne | Sessions séparées ([05](05-plan-de-pr-et-lots.md) section 1) |
| R9 | `isEventLive` compte un événement `IN_PROGRESS` dont la fin est dépassée (organisateur qui oublie de terminer) | Faible | Garde `endAt > maintenant` dans la règle de sélection |
| R10 | Un événement démarré par l'organisateur **avant** son heure de début est écarté par `startDateTo = maintenant` | Faible | Limite connue, acceptée |
| R11 | Un événement sans date de fin paraît finir maintenant (`formatTimestamp`) | Faible | Écarté du direct : acceptable pour la démo |
| R12 | Position rafraîchie seulement toutes les 30 s : le point de l'organisateur peut être périmé | Faible | Horodatage affiché ; l'arrêt à l'arrivée évite les points fantômes |

## 3. Plan de test

| Niveau | Quoi | Où |
| :--- | :--- | :--- |
| Unitaire | Règle de sélection, service de trajet, hooks, handler `live.position`, contrôles d'autorisation, filtre `endAtFrom` | Chaque dépôt, selon `AGENTS.md` section 3 (mocks et factories séparés) |
| Contrat | `buf lint`, `buf breaking` ; build des paquets avant tout changeset | `proto-registry`, `npm-packages` |
| Intégration | Appel gateway vers `ws-service` avec jeton interne ; message entrant par le proxy (V3) | CI |
| E2E | Parcours complet via la CI | **Jamais en local** : pousser et lire le job `e2e` |
| Manuel | Voir le scénario de démonstration | Simulateur avec position simulée |

## 4. Scénario de démonstration

1. Préparer au moins deux événements en cours et un complet autour du point simulé (seed LE-04) ; un événement qui finit dans moins de 20 minutes.
2. Simuler la position du téléphone à proximité (position personnalisée du simulateur).
3. Ouvrir le bouton central, "Rejoindre un direct" : trois cartes triées par temps de marche, le complet en grisé, l'événement qui finit trop tôt absent.
4. Rejoindre le premier : il passe dans "Mon événement" avec le tracé et le temps restant.
5. Rouvrir le bouton central : le libellé est devenu "Mon événement en direct".
6. Couper le réseau vers OSRM : la liste s'affiche avec "estimé".
7. Palier 4 : activer le partage, vérifier chez l'organisateur un point arrondi, puis l'arrêt à l'arrivée.
