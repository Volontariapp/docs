# 06 - Risques et vérifications

## 1. Vérifications

Relecture du 2026-11-07 : huit points réglés par lecture, deux restent à essayer (V3, V4 en partie). Mise à jour après livraison (2026-11-07) : V4 fait au curl, appareil à faire ; V3 à faire après déploiement.

| # | Point | Résultat | Conséquence |
| :--- | :--- | :--- | :--- |
| V1 | Que devient un événement si le **géocodage échoue** ? | **Réglé par lecture.** `location` est nullable (`domain-event/src/models/event.model.ts:38-44`) ; le géocodage est asynchrone dans `worker-event` (`app.module.ts:92-95`) ; un échec passe la saga en `FAILED`. **Inférence** : invisible par `ST_DWithin`, y compris juste après la création | Le seed attend le géocodage ; un événement sans coordonnées est hors du direct (accepté) |
| V2 | Le **formulaire de création** accepte-t-il un début maintenant ou dans le passé ? | **Réglé.** Oui à partir d'aujourd'hui 00:00 (`nativapp/src/api/event/event.schema.ts:26-35`) ; le back exige seulement début avant fin (`event.service.ts:81`) | Le seed n'est pas la seule source de démonstration |
| V3 | Les messages **entrants** traversent-ils le proxy de la gateway ? | **À faire après déploiement** (essai requis). À la lecture, le proxy fait l'upgrade puis tunnelise (`ws-proxy.middleware.ts:93-144`) ; `ws-service` #54 et `api-gateway` #111 sont fusionnées mais pas déployées | À essayer avant LE-11a : `socket.io-client` par la gateway, émission, observation côté `ws-service`. Si non, modifier le proxy |
| V4 | OSRM piéton : `table`, `geometries=geojson`, `User-Agent` | **Curl fait, appareil à faire.** `table` et `route` en GeoJSON fonctionnent (curl, [01](01-etat-des-lieux.md) section 8). Envoi du `User-Agent` par React Native **non testé** sur appareil (écran livré par nativapp #112) | À tester sur appareil. Sans `User-Agent` : risque de blocage par l'hôte |
| V5 | `@volontariapp/logger` masque-t-il `latitude` et `longitude` ? | **Réglé : non** (`logger/src/masking.ts:4-22`) | `masking.keys` dans `ws-service/src/main.ts` (LE-08a) ; jamais de coordonnée interpolée |
| V6 | Contrôleur HTTP dans `ws-service`, sortie vers Redis | **Réglé.** Aucun contrôleur, serveur Express présent (`main.ts`) ; sortie Redis autorisée (`ws-service.yaml:66-81`) | Ajouter un contrôleur (LE-08a) ; aucun lot `deploy` |
| V7 | Sérialisation de `statuses` et `area` dans `GET /events` | **Réglé par précédent** : Explore envoie déjà ces paramètres par `params` axios (`explore-search.utils.ts:26-37`), la gateway convertit les statuts (`search-events.request.dto.ts:50-56`) | Même chemin ; non testé de bout en bout avec les nouveaux paramètres |
| V8 | La gateway conserve-t-elle l'ordre de `ms-event` ? | **Réglé : oui** (`search-events.response.dto.ts:16`, enrichissement en place) | Le client retrie quand même par temps de marche |
| V9 | Le `ValidationPipe` rejette-t-il un paramètre inconnu ? | **Réglé : non** (`{ transform: true }` sans `whitelist`, `api-gateway/src/main.ts:71`) : paramètre ignoré | LE-10 peut être fusionnée avant le déploiement de LE-07 |
| V10 | Texte de la permission de localisation | **Réglé** : `nativapp/app.json:37-40` (pas `app.config.js`), ne parle que des événements à proximité ; `locationAlwaysAndWhenInUsePermission` déclarée sans usage | Réécrire dans LE-11a ; vérifier si `app.config.js` réécrit ces clés |
| V11 | Restent non vérifiés | Un `UPDATE` SQL d'état hors migrations ; index sur `end_at` ; `system-seed.service.ts` ; mock `react-native-maps` dans `jest.setup.js` ; codes d'erreur disponibles dans `errors-nest` ; client HTTP de la gateway | Chacun est à lire au début du lot concerné |

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
| R2 | Événement complet non détecté : l'échec du comptage de participants est silencieux (valeur de `ms-event`, probablement 0) | Moyenne | Accepté pour la démo ; le serveur ne bloque pas non plus la participation ; LE-12 en option. Capacité 0 : sans limite (D19) |
| R3 | OSRM public indisponible ou limité (1 requête par seconde, aucune garantie) | Moyenne | File d'attente, cache de 60 s, repli à vol d'oiseau marqué "estimé" |
| R4 | Suivi d'une personne par un tiers (partage de position) | **Élevée** | ADR-6 : organisateur seul, désactivé par défaut, arrondi 100 m, TTL, arrêt à l'arrivée, aucun historique |
| R5 | Fuite de coordonnées dans les journaux | Élevée | Règle d'équipe, V5, test ou relecture dans LE-08 et LE-09 |
| R6 | `nativapp` envoie `endAtFrom` avant le déploiement du back | Nulle | La gateway ignore le paramètre (V9) ; le filtre client reste |
| R7 | Deux bumps concurrents de `@volontariapp/contracts` (PR A automatique et PR B manuelle) | Moyenne | A d'abord, B rebasée sur A ; `changeset version` après le rebase seulement |
| R8 | Le verrou STOP bloque tous les sous-agents d'une session qui a édité `proto-registry` ou `npm-packages` (vérifié : ils partagent son `session_id`) | Élevée si ignoré | LE-01 et LE-05 dans des processus `claude -p` séparés (D21) ; `release` lève toutes les sessions |
| R13 | Endpoint interne de `ws-service` appelé avec un jeton interne quelconque (21 sources autorisées par le réseau) | Élevée | Jeton lié à `userId`, chemin hors `/socket.io`, plafond revérifié (D18) |
| R14 | Arrivée jamais détectée à cause de l'arrondi | Moyenne | Arrivée côté client sur la position brute, repli serveur à 150 m (D17) |
| R15 | Partage qui survit à l'expiration du jeton d'accès, à un blocage ou à une suppression de compte | Faible | Borné par le TTL de l'autorisation ; limite connue |
| R16 | Point fantôme chez l'organisateur (app du participant tuée) | Faible | Purge côté client après 120 s ([03](03-nativapp.md) section 8) |
| R17 | Démo périmée : les événements seedés finissent 3 h après le seed | Moyenne | Relancer le seed avant chaque démo ; durée configurable |
| R18 | Copies multiples de `@volontariapp/database` après un bump de `domain-*` : TypeORM échoue (`No metadata for EventQueueModel`, `No mapping registered from JobsOutboxEntity`) et toute écriture renvoie 500 (rencontré sur `ms-event` #91) | Élevée | Vérifier `yarn.lock` (une seule copie de `database`) ; aligner `database`, `shared` et `outbox` sur les versions du domaine ; lire l'artefact `e2e-diagnostics` de la CI (journaux des services) |
| R9 | `isEventLive` compte un événement `IN_PROGRESS` dont la fin est dépassée (organisateur qui oublie de terminer) | Faible | Garde `endAt > maintenant` dans la règle de sélection |
| R10 | Un événement démarré par l'organisateur **avant** son heure de début est écarté par `startDateTo = maintenant` | Faible | Limite connue, acceptée |
| R11 | Un événement sans date de fin paraît finir maintenant (`formatTimestamp`) | Faible | Écarté du direct : acceptable pour la démo |
| R12 | Position rafraîchie seulement toutes les 30 s : le point de l'organisateur peut être périmé | Faible | Horodatage affiché ; l'arrêt à l'arrivée évite les points fantômes |

## 3. Plan de test

| Niveau | Quoi | Où |
| :--- | :--- | :--- |
| Unitaire | Règle de sélection, service de trajet, hooks, handler `live.position`, contrôles d'autorisation, filtre `endAtFrom` | Chaque dépôt, selon `AGENTS.md` section 3 (mocks et factories séparés) |
| Contrat | `buf lint`, `buf breaking` ; build des paquets avant tout changeset | `proto-registry`, `npm-packages` |
| Intégration | Appel gateway vers `ws-service` avec jeton interne lié ; refus d'un jeton d'un autre utilisateur ; une requête par le proxy vers `/socket.io/../internal/live/grants` n'atteint pas le contrôleur ; message entrant par le proxy (V3) | CI |
| E2E | Parcours complet via la CI | **Jamais en local** : pousser et lire le job `e2e` |
| Manuel | Voir le scénario de démonstration | Simulateur avec position simulée |

## 4. Scénario de démonstration

1. Lancer le seed LE-04 juste avant la démo (profils normal, fin proche, complet : [04](04-contrats-et-backend.md) section 6.1) et attendre le géocodage ; à défaut, créer les événements depuis l'app (V2).
2. Simuler la position du téléphone à proximité (position personnalisée du simulateur).
3. Ouvrir le bouton central, "Rejoindre un direct" : trois cartes triées par temps de marche, le complet en grisé, l'événement qui finit trop tôt absent.
4. Rejoindre le premier : il passe dans "Mon événement" avec le tracé et le temps restant.
5. Rouvrir le bouton central : le libellé est devenu "Mon événement en direct".
6. Couper le réseau vers OSRM : la liste s'affiche avec "estimé".
7. Palier 4 : activer le partage, vérifier chez l'organisateur un point arrondi, puis l'arrêt à l'arrivée (détecté par le téléphone du participant).
