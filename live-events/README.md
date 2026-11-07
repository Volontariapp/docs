# Rejoindre un événement en direct (`live-events`)

Ce dossier décrit une nouvelle fonction de `nativapp` : depuis le bouton central de l'application, proposer à l'utilisateur de **rejoindre un événement qui est en cours autour de lui**, avec le trajet à pied et le temps de marche, puis (palier ultérieur) partager sa position avec l'organisateur pour ne pas se perdre en chemin.

> [!NOTE]
> **Statut au 2026-11-07 : conception validée par Victor, rien n'est implémenté.** Les décisions sont dans [02](02-decisions.md). Les constats viennent de la lecture du code le 2026-11-07 ; chaque constat porte son chemin (et sa ligne quand elle a été lue). Ce qui n'a pas été vérifié est listé dans [06](06-risques-et-verifications.md). En cas de doute sur ce qui existe, le code et les skills `volontariapp-*` font foi.

> [!WARNING]
> **Deux faits changent la nature du chantier.**
> 1. **Rien ne démarre un événement automatiquement.** `IN_PROGRESS` n'est posé que par l'organisateur (ou un admin) via `changeState`. La règle "en direct" doit donc s'appuyer sur les dates, pas sur l'état seul ([01](01-etat-des-lieux.md) section 4).
> 2. **Les données de démo ne contiennent aucun événement en cours** : le seed crée des événements passés ou à au moins un jour d'ici ([01](01-etat-des-lieux.md) section 7). Le lot LE-04 en ajoute.

## Par où commencer

1. [02 - Décisions](02-decisions.md) : ce qui est décidé, et ce qui reste à trancher avec une valeur par défaut.
2. [05 - Plan de PR et lots](05-plan-de-pr-et-lots.md) : l'ordre des PR, ce qui se fait en parallèle, quel agent prend quel lot.
3. [03](03-nativapp.md) et [04](04-contrats-et-backend.md) : le détail technique d'un lot.

## Principe en cinq lignes

1. Le bouton central (`QuickActionsModal`) gagne une troisième action. Elle ouvre un écran racine `LiveEvent`, commun : "Mon événement en direct" (si l'utilisateur participe à un événement en cours) et "Autour de moi" (propositions).
2. Le client cherche avec la route existante `GET /events` (zone de 2 km, états `PUBLISHED` et `IN_PROGRESS`, fenêtre de dates) puis **filtre côté client** : l'événement est en cours, il reste assez de temps pour y aller et y rester.
3. Le temps de marche vient d'OSRM (hôte piéton `routing.openstreetmap.de/routed-foot`), directement depuis l'app. Le tracé s'affiche dans l'app avec `react-native-maps`.
4. Rejoindre utilise la route existante `POST /social/events/:eventId/participate`. Un événement complet est proposé en grisé, non joignable.
5. Le partage de position (palier 4) est **séparé, optionnel, désactivé par défaut**, visible de l'organisateur seul, arrondi à environ 100 m, jamais conservé en base.

## Paliers

| Palier | Contenu | Dépôts touchés | Contrat à changer |
| :--- | :--- | :--- | :--- |
| P1 | Bouton, recherche, liste de 3 plus les complets en grisé, participation | `nativapp`, `api-gateway` (seed de démo) | Aucun |
| P2 | Trajet à pied, temps de marche, écran commun "Événement en direct" | `nativapp` | Aucun |
| P3 | Filtre serveur `endAtFrom` (supprime la troncature de la recherche) | `proto-registry`, `npm-packages`, `ms-event`, `api-gateway`, `nativapp` | Un champ proto |
| P4 | Partage de position vers l'organisateur (version réduite) | `npm-packages` (`messaging`), `ws-service`, `api-gateway`, `nativapp` | Types WebSocket, pas de proto |
| P5 | Hors périmètre : rappel de fin, démarrer un direct, capacité côté serveur, audience "amis" | à décider | à décider |

**La démo P1 + P2 ne demande aucun changement de contrat ni de service** : elle est utilisable après les lots LE-02, LE-03 et LE-04.

## Navigation

| Fichier | Contenu |
| :--- | :--- |
| [01 - État des lieux](01-etat-des-lieux.md) | Ce qui existe, avec preuves (chemins, lignes, mesures) |
| [02 - Décisions](02-decisions.md) | Décisions validées le 2026-11-07, décisions ouvertes avec valeur par défaut |
| [03 - nativapp](03-nativapp.md) | Fichiers, types, constantes, requête, règle de sélection, écrans, tests |
| [04 - Contrats et back-end](04-contrats-et-backend.md) | Champ proto, contrats npm, gateway, ws-service, Redis, réseau, vie privée |
| [05 - Plan de PR et lots](05-plan-de-pr-et-lots.md) | Ordre des PR, vagues parallèles, lots LE-01 à LE-13, consignes aux sous-agents |
| [06 - Risques et vérifications](06-risques-et-verifications.md) | Ce qui n'est pas vérifié, risques, plan de test |

## Décisions d'architecture (ADR synthétiques)

| # | Décision | Alternative écartée | Raison principale |
| :--- | :--- | :--- | :--- |
| ADR-1 | Filtrer "en direct" sur les dates côté client (`isEventLive` existant plus `fin > maintenant`) | Filtrer sur `IN_PROGRESS` seul | Aucun job ne démarre un événement ([01](01-etat-des-lieux.md) section 4) |
| ADR-2 | Trajet par OSRM piéton appelé depuis l'app | OpenRouteService, lien profond vers Plans ou Google Maps | Sans clé ni secret, tracé dans l'app, front non déployé (démo). `router.project-osrm.org` ignore le profil piéton |
| ADR-3 | Un seul cycle de contrats : 1 PR `proto-registry`, 2 PR `npm-packages` (une automatique, une manuelle) | Un cycle par fonction | Chaque cycle impose le STOP, la publication et le déverrouillage |
| ADR-4 | Autorisation du partage écrite dans Redis par `ws-service`, sur appel interne de la gateway | La gateway écrit Redis directement (option B initiale) | La `NetworkPolicy` de la gateway n'autorise pas Redis en production ([04](04-contrats-et-backend.md) section 9) |
| ADR-5 | Audience du partage : l'organisateur seul, via la room utilisateur existante | Rooms par événement dès la V1 | Une seule personne reçoit : `notifyUser` suffit. Les rooms par événement servent quand l'audience s'élargit (P5) |
| ADR-6 | Pas de partage de position entre inconnus | Carte publique des participants | Risque de suivi d'une personne ; donnée personnelle (`AGENTS.md` section 6) |
