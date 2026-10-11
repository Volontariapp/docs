# 01 - État des lieux

Faits vérifiés dans le code le 2026-10-11. Les chemins sont relatifs à la racine `meta`.

## Ce qui existe déjà

### Le graphe `ms-social`

| Élément | Réalité | Source |
| :--- | :--- | :--- |
| Nœuds | `SocialUser {userId}` et `SocialEvent {eventId}` : **un seul champ chacun, l'identifiant** | `npm-packages/packages/domain-social/src/entities/social-user.entity.ts`, `social-event.entity.ts` |
| Relations d'événement | `CREATED`, `PARTICIPATE`, `WISH_TO_PARTICIPATE` | `.../repositories/neo4j-participation.repository.ts` |
| Relations entre utilisateurs | `FOLLOW` (un « ami » = suivi mutuel), `BLOCK` | même fichier, requête de `getRecommendedEventIds` |
| Reco structurelle | `getRecommendedEventIds(userId, filters, pagination)` : exclusions (créés, participés, souhaités par moi, créateurs bloqués) et restrictions aux événements touchés par des amis | `neo4j-participation.repository.ts` |
| Exposition gRPC | `ParticipationQueryService.GetRecommendedEventIds`, contrôleur `participation.query.controller.ts:142` | `proto-registry/proto/volontariapp/social/social.services.proto:96` |
| Consommateur actuel | `GET /events` de l'API Gateway, uniquement si un filtre social est passé, avec `pagination: { page: 1, limit: 1000 }` | `api-gateway/src/modules/event/controllers/queries/event/event.query-controller.ts:66` |

Limites du graphe pour notre besoin :

- Aucun texte, aucune catégorie, aucun tag dans Neo4j : **le goût d'un utilisateur ne peut pas être lu du graphe, seulement déduit des identifiants d'événements qu'il a touchés**, dont il faut aller chercher le contenu dans `ms-event`.
- Les relations n'ont **pas d'horodatage** et les requêtes n'ont pas de `ORDER BY` : impossible d'extraire « les 10 dernières participations ». Voir les questions ouvertes.

### Les événements (`ms-event`, PostgreSQL)

`EventEntity` (`npm-packages/packages/domain-event/src/entities/event.entity.ts`) porte `name`, `description`, `type` (`EVENT_TYPE_SOCIAL` ou `EVENT_TYPE_ECOLOGY`, enum de `proto-registry/proto/volontariapp/event/event.proto`), `state`, `startAt`, `endAt`, `location`, `localisationName`, `awardedImpactScore`, `maxParticipants`, `currentParticipants`, `organizerId`, ainsi que `tags` et `requirements`.

Le payload de `event.created` ne contient **que** `eventId`, `userId`, `localisationName`, `coverFileId` (`IEventCreatedPayload`, `npm-packages/packages/messaging/src/events/event/payloads.ts`). Le texte d'un événement doit donc être lu via gRPC dans `ms-event`.

### Les utilisateurs (`ms-user`, PostgreSQL)

`UserEntity` : `pseudo`, `email`, `bio` (optionnel), `role`, `totalImpactScore`, `badges`. **Il n'existe aucun champ de centres d'intérêt.** Le profil de goût est donc entièrement déduit de l'historique (participations, souhaits).

### Signaux asynchrones disponibles

Vérifié avec `analyze_impact` :

| Flux | Producteur | Consommateurs | Utilisable comme déclencheur |
| :--- | :--- | :--- | :--- |
| `Streams.USER_CREATED` | triggers SQL de `domain-user` | `post-processor-social` (`user-created.post-processor.ts:28`), `ws-service`, `nativapp` | Oui |
| `Streams.EVENT_CREATED` | `domain-event/src/repositories/postgres-event.repository.ts:71` | `post-processor-event`, `post-processor-social` (`events/event-created.post-processor.ts`), `ws-service` | Oui |
| `Streams.EVENT_SOCIAL_WISHED` / `UNWISHED` | `domain-social/src/services/participation.service.ts:246` (et `:295`) | `post-processor-user` (badges) | Oui |
| `Streams.EVENT_FINISHED` | `postgres-event.repository.ts:139` | `post-processor-user` (badges) | Oui |
| `Streams.SOCIAL_PARTICIPATIONS` | **aucun producteur** | aucun | Non |
| `Streams.SOCIAL_RELATIONS` | **aucun producteur** | aucun | Non |
| `Streams.EVENT_SUCCESSFULLY_CREATED` | **aucun producteur** | `post-processor-event`, `post-processor-user` | Non (ne pas s'y fier) |

Conséquence importante : `participateEvent`, `leaveEvent` et `followUser` de `domain-social` **n'émettent aucun événement aujourd'hui**. Seuls les souhaits (`wish`/`unwish`) en émettent.

### Le circuit de jobs de `ms-social`

- Queue : `SocialQueue.SOCIAL = 'social-queue'`.
- Un seul job : `SocialJobType.FOLLOW_USER = 'social.follow_user'`, dont le handler (`workers-runners/worker-social/src/workers/handlers/follow-user.handler.ts`) **ne fait rien** (log puis `Promise.resolve()`).
- `worker-social` dispose déjà de BullMQ, Redis (`providers/redis.provider.ts`), Neo4j (`Neo4jBridgeModule`) et de tous les services `domain-social` (`app.module.ts`). Il n'a **pas** de client gRPC vers `ms-event`.
- `ms-social` n'a **pas** de dépendance Redis (`package.json`, `src/providers/` ne contient que `database/`).

## Ce qui manque (et que ce dossier propose)

1. Un contrat de job `social.compute_event_matching` et son handler.
2. Des déclencheurs qui émettent ce job.
3. Un client gRPC `worker-social` vers `ms-event` pour lire le texte des événements.
4. Un adaptateur Jev derrière un port du domaine.
5. Un stockage Redis des listes de matching et un accès Redis côté `ms-social`.
6. Une RPC de lecture `GetMatchedEventIds` et une route gateway.
