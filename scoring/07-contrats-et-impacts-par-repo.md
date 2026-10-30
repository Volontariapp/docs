# 07 - Contrats et impacts par dépôt

> [!CAUTION]
> Règle du STOP ([AGENTS.md](../../AGENTS.md), section 1). La séquence est stricte : `proto-registry`, puis PR automatique dans `npm-packages`, puis publication CI, puis seulement les services consommateurs. Un hook interdit l'édition des `ms-*`, de la gateway, de `ws-service`, `nativapp` et des runners après une modification amont dans la même session.

Les chemins marqués "exploré" n'ont pas été relus ce jour : à revérifier avec `mesh-mcp` (`analyze_grpc`, `analyze_impact`, `find_dependents`) avant de coder.

## 1. Vague 1 : `proto-registry`

| Changement | Fichier |
| :--- | :--- |
| RPC `SetEventAttendance` (écriture, `ms-social`) | `proto-registry/proto/volontariapp/social/social.services.proto` (exploré) |
| RPC de lecture des présents ordonnés : `GetEventAttendees` avec `registeredAt` | idem |
| Messages `registeredAt` / `checkedInAt` dans la liste des participants (affichage du check-in) | proto social |
| Champ `scoring_version` de l'événement (lecture seule) | `event.proto` |
| `awardedImpactScore` : champ conservé, retiré de la saisie (`CreateEventCommand`), non supprimé du fil | `event.command.proto:17` (exploré) |

Vérifications : `buf lint`, `buf breaking --against '.git#branch=main'`. Pas de renumérotation. Le retrait de la saisie se fait en rendant le champ optionnel côté serveur (ignoré), pas en le supprimant du proto (voir `volontariapp-proto-contract-evolution`).

## 2. Vague 2 : `npm-packages`

| Package | Changement |
| :--- | :--- |
| `messaging` | `IEventFinishedPayload` : ajouter `startAt`, `endAt`, `maxParticipants`, `organizerId`. Optionnels pour tolérer les anciens messages (`messaging/src/events/event/payloads.ts:49-54`, exploré). Payload `user.impact_score_credited` : ajouter `role`, `rank` optionnels. |
| `shared` | Fonction pure `computeEventScoring` et table de paliers `alpha` (lieu proposé, voir [README](README.md)). |
| `domain-social` | `createParticipation` avec `registeredAt`, `setAttendance`, lecture des présents ordonnés (`neo4j-participation.repository.ts:89-98`, lu). |
| `domain-event` | `changeStateWithEventFinished` : payload enrichi (`postgres-event.repository.ts:300-304`, lu). Création sans score saisi. |
| `domain-user` | `ImpactScoreCreditModel` : colonnes `role`, `rank`, `formula_version`, `event_pool`. |
| `contracts`, `contracts-nest` | Régénérés par la CI depuis `proto-registry`. Ne pas éditer. |

Pour chaque package : `yarn build`, `yarn test`, `yarn changeset add`, `yarn changeset version` une fois par branche, puis STOP jusqu'à la publication CI.

## 3. Vague 3 : services

| Dépôt | Changement |
| :--- | :--- |
| `ms-social` | Contrôleur et handler `SetEventAttendance` et lecture des présents (CQRS, voir `volontariapp-grpc-microservice`). Contrôle : l'appelant est l'organisateur. |
| `ms-event` | DTO de création sans score. Marquer `scoring_version`. Vérifier l'application de la capacité à l'inscription (point non vérifié, [01](01-etat-des-lieux.md)). |
| `ms-user` | Migration "Expand" du registre de crédits (`volontariapp-db-migration`) : colonnes nullables, aucun backfill, puis `yarn meta sync-migrations`. |
| `post-processors-runner/post-processor-user` | `ImpactScoreCrediter` : lire les présents, appeler `computeEventScoring`, créditer participants et créateur, brancher l'ancien chemin pour les événements sans `scoring_version`. Mettre à jour `EventFinishedImpactScorePostProcessor` et son client social. |
| `api-gateway` | Route de check-in ; retirer le score du DTO de création ; exposer l'estimation si elle n'est pas calculée côté client (`volontariapp-api-gateway`). |
| `ws-service` | Aucun changement obligatoire. À vérifier avec `analyze_impact` sur `user.impact_score_credited`. |
| `nativapp` | Voir [08](08-impacts-nativapp.md). |
| `deploy` | Aucun a priori : pas de nouveau déployable. |

## 4. Skills et mémoire

Après les changements de code, lancer `python3 .agents/skills/volontariapp-skill-evolution/scripts/evolve.py plan` pour la liste des skills à relire (notamment `volontariapp-implement-async-event-flow`, `volontariapp-grpc-microservice`, `volontariapp-db-migration`).
