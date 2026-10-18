# 01 - État des lieux

Faits vérifiés dans le code le 2026-10-11 (outils mesh-mcp et lecture directe), puis revérifiés en partie le 2026-10-18 : les écarts constatés depuis (suppression de compte, médias de `ms-post`) sont corrigés dans les sections concernées et listés dans [13](13-decisions-v1.md). Chemins relatifs à la racine `meta`. Ce qui n'a **pas** pu être vérifié est dit explicitement.

## 1. Le graphe social (`ms-social`, Neo4j)

| Élément | Réalité | Source |
| :--- | :--- | :--- |
| Nœuds | `SocialUser {userId}` et `SocialEvent {eventId}` : **un seul champ chacun, l'identifiant** | `npm-packages/packages/domain-social/src/entities/social-user.entity.ts`, `social-event.entity.ts` |
| Relations d'événement | `CREATED`, `PARTICIPATE`, `WISH_TO_PARTICIPATE` | `.../repositories/neo4j-participation.repository.ts` |
| Relations entre utilisateurs | `FOLLOW` (un « ami » = suivi mutuel dans les requêtes), `BLOCK` | même fichier, requête `getRecommendedEventIds` |
| Reco structurelle | `getRecommendedEventIds(userId, filters, pagination)` : exclusions (créés, participés, souhaités, créateurs bloqués dans les deux sens) et restriction aux événements touchés par des amis (`onlyParticipatedByFriends`, `onlyWishedByFriends`, `onlyCreatedByFriends`) | `neo4j-participation.repository.ts` |
| Exposition | `ParticipationQueryService.GetRecommendedEventIds`, contrôleur `participation.query.controller.ts:142`. **Cette RPC utilise l'identité du token (`@CurrentUser`), pas un `userId` fourni** | `proto-registry/proto/volontariapp/social/social.services.proto:96` |
| RPC « admin » | `AdminGetUserEvent`, `AdminGetUserParticipateEvent`, `AdminGetUserWishEvent` reçoivent un `userId` explicite dans le corps | `ms-social/src/modules/participation/dto/participation.query.dto.ts:86` |
| Pas d'équivalent admin pour la reco | **`AdminGetRecommendedEventIds` n'existe pas** | `analyze_grpc GetRecommendedEventIds` : un seul handler |
| Consommateur actuel | `GET /events` de la gateway, seulement si un filtre social est passé, avec `pagination: { page: 1, limit: 1000 }` | `api-gateway/src/modules/event/controllers/queries/event/event.query-controller.ts:66` |

Limites du graphe pour notre besoin :

- Aucun texte, catégorie ou tag dans Neo4j. **Le goût d'un utilisateur se déduit des identifiants d'événements qu'il a touchés ; leur contenu est dans `ms-event`.**
- Les relations n'ont pas d'horodatage et les requêtes n'ont pas de tri : impossible d'extraire « les 10 dernières participations ».

## 2. Les événements (`ms-event`, PostgreSQL)

`EventEntity` (`npm-packages/packages/domain-event/src/entities/event.entity.ts`) : `name`, `description`, `type` (`EVENT_TYPE_SOCIAL` ou `EVENT_TYPE_ECOLOGY`, enum de `proto-registry/proto/volontariapp/event/event.proto`), `state`, `startAt`, `endAt`, `location`, `localisationName`, `awardedImpactScore`, `maxParticipants`, `currentParticipants`, `organizerId`, `tags`, `requirements`.

Le payload de `event.created` ne contient que `eventId`, `userId`, `localisationName`, `coverFileId` (`IEventCreatedPayload`, `npm-packages/packages/messaging/src/events/event/payloads.ts`). **Le texte d'un événement doit donc être lu par gRPC dans `ms-event`.**

La recherche par identifiants existe : la gateway positionne `query.ids` avant d'appeler `searchEvents` (`event.query-controller.ts`, après la ligne 103). Vérifié par la revue :

- `SearchEventsQuery` (`proto-registry/proto/volontariapp/event/event.query.proto:13-26`) supporte `statuses`, `start_date_from`, `only_available` et une pagination.
- `only_available` signifie seulement `state = PUBLISHED` (repository) : **aucun filtre de capacité** n'existe.
- La pagination par défaut du repository est 10 (`limit = params.limit > 0 ? params.limit : 10`) et le tri par défaut est `createdAt DESC` (ou la distance) : une recherche par identifiants sans pagination explicite est tronquée à 10.
- La RPC `GetEventsByIds` (`event.services.proto:19`) fait un `findById` par identifiant (N+1, erreurs avalées, aucun filtre d'état).

## 3. Les utilisateurs (`ms-user`)

`UserEntity` : `pseudo`, `email`, `bio` (optionnel), `role`, `totalImpactScore`, `badges`. **Aucun champ de centres d'intérêt.** Le goût est entièrement déduit de l'historique (participations, souhaits).

## 4. Signaux asynchrones disponibles

Vérifié avec `analyze_impact` :

| Flux | Producteur | Consommateurs actuels | Utilisable |
| :--- | :--- | :--- | :--- |
| `Streams.SOCIAL_USER` (`social:user`) | trigger SQL de `domain-user` : `target_services = ARRAY['social:user']` (`database/triggers/users.trigger.sql:27`) | `post-processor-social` (`users/options/user-created.options.ts:10`) | **Oui, c'est le flux à consommer pour l'inscription** |
| `Streams.USER_CREATED` (`user:created`) | aucun producteur applicatif trouvé (le mesh mélange les deux noms, non confirmé à 100 %) | `ws-service`, `nativapp` | Non, à ne pas utiliser |
| `Streams.EVENT_CREATED` | `domain-event/.../postgres-event.repository.ts:118` | `post-processor-event`, `post-processor-social`, `ws-service` | Oui |
| `Streams.EVENT_SOCIAL_WISHED` / `UNWISHED` | `domain-social/.../participation.service.ts:246` et `:295` | `post-processor-user` (badges) | Oui |
| `Streams.EVENT_FINISHED` | `postgres-event.repository.ts:314` | `post-processor-user` (badges) | Oui |
| `Streams.SOCIAL_PARTICIPATIONS` | **aucun** | aucun | Non |
| `Streams.SOCIAL_RELATIONS` | **aucun** | aucun | Non |
| `Streams.EVENT_SUCCESSFULLY_CREATED` | **aucun** | `post-processor-event`, `post-processor-user` | Non |
| `Streams.WS_JOBS_OUTBOX_SUCCESS` | `packages/post-processors/src/common/job-outbox-success.post-processor.ts:105` | `ws-service` (`ws-job-outbox-success.options.ts:11`) | Oui (notification de fin de job) |
| `Streams.WS_JOBS_OUTBOX_FAILURE` | `job-outbox-failed.post-processor.ts:118` | `ws-service` | Voir le bug connu ci-dessous |

Conséquence : `participateEvent`, `leaveEvent`, `followUser` et `blockUser` de `domain-social` **n'émettent aucun événement aujourd'hui** (seuls `wishEvent` et `unwishEvent` le font). Les déclencheurs « participation » et « follow » sont une évolution V2 qui touche `npm-packages` (règle du STOP).

Deux précisions de la revue :

- L'émission des événements de souhait **n'est pas atomique** : `wishEvent` écrit dans Neo4j puis insère dans `event_queue` (deux magasins), et l'échec de l'insertion est avalé par un `logger.warn` (`participation.service.ts:246-265`). Un événement de souhait peut être perdu silencieusement.
- `user:deleted` a désormais un producteur (corrigé le 2026-10-18) : `PostgresUserRepository.requestDeletionWithUserDeleted` (`domain-user/src/repositories/postgres-user.repository.ts:90-111`) passe l'utilisateur en `PENDING_DELETION` et écrit `user.deleted` dans `event_queue` vers `USER_DELETED`, `SOCIAL_USER`, `USER_DELETED_POST`, `USER_DELETED_EVENT` et `USER_DELETED_STORAGE`. Chaque domaine a son propre stream ; `finalizeDeletion` ne supprime la ligne qu'après le succès du gather côté `ws-service` (skill `volontariapp-user-account-deletion`). `ms-ranking` doit donc avoir son stream `user:deleted:ranking` et figurer dans les `targetServices` (modification de `domain-user`, soumise au STOP).

## 5. Le circuit de jobs et le 206

- `withFallback` (`ms-event/src/modules/event/controllers/commands/base.command.controller.ts`) : si l'opération échoue sur une erreur autre que 400, 404, 409, il écrit un job de repli dans `jobs_outbox` (queue `FALLBACK_*`), puis lance `FALLBACK_ACTIVATED(jobType, message)` de `@volontariapp/errors-nest`. **Le client reçoit un 206 sans données et attend le résultat par WebSocket** (skill `volontariapp-api-gateway`, ligne 99).
- Le trigger SQL `notify_job_audit_status_change` déduit le nom du stream du champ `emitter` : `replace(NEW.emitter, 'ms-', '')`. Un émetteur `ms-ranking` produira donc `ranking:job:outbox:success` et `ranking:job:outbox:failure`, **à déclarer dans l'enum `Streams`** (`npm-packages/packages/shared/src/enums/streams.enum.ts`).
- `BaseWorker` saute un job déjà `COMPLETED` : il consulte d'abord une clé Redis `job:completed:<id>` (TTL 24 h) puis `job_audit` (`workers/src/core/base.worker.ts:77-132`), et rejoue un job resté `PROCESSING`. Il écrit `FAILED` dans `job_audit` à **chaque tentative** (`base.worker.ts:211-232`, 3 tentatives par défaut).
- L'outbox (`database/src/outbox/consumers/outbox.consumer.ts`) fait passer `PENDING` à `PROCESSING` puis à `COMPLETED` après le push BullMQ, ou à `FAILED` si le push échoue. Il ne relit que `PENDING` : **un job `FAILED` n'est jamais repoussé**.
- `JobsOutboxEntity.createJob` génère un `randomUUID()` sans clé d'idempotence, et le `jobId` BullMQ vaut cet identifiant : aucune déduplication native.
- La notification WebSocket de fin de job n'est émise que s'il existe un mapping `JOB_TO_EVENT_MAPPING` pour le type de job (`messaging/src/websockets/events/mapping.ts`, aujourd'hui uniquement des `FALLBACK_*`) et si `originalPayload.userId` est présent côté `ws-service`.
- **Bug connu (C3, skill job-flow)** : le trigger émet `...:job:outbox:failure` mais `JobOutboxFailedPostProcessor` n'accepte que `...:failed`. Un job en échec ne remonte jamais jusqu'au client.
- Les workers existants utilisent une `IJobHandler` locale à chaque worker. `worker-social` n'a qu'un handler, `FollowUserHandler`, qui ne fait rien (`follow-user.handler.ts`).

## 6. Appels de service à service avec une identité système

`post-processors-runner/post-processor-user/src/core/clients/social-interaction.client.ts:74-87` :

```typescript
const token = await this.jwtService.signInternal({ id: 'pp-user', role: UserRoles.ADMIN });
// mis en cache 4 minutes, puis posé en métadonnée gRPC INTERNAL_TOKEN_METADATA_KEY
```

Et il appelle des RPC `adminGet*` avec un `userId` explicite. **C'est le patron à suivre pour `worker-ranking`.** Contrepartie de sécurité : le service détient un jeton de rôle `ADMIN` (voir [08](08-tests-observabilite-securite.md)).

`GrpcInternalGuard` (`npm-packages/packages/auth/src/guards/grpc-internal.guard.ts`) lit le jeton dans la métadonnée, le vérifie avec `jwtService.verifyInternal`, et pose `user` dans le contexte.

## 7. Structure d'un domaine complet

Chaque domaine est découpé en déployables distincts (`AGENT.md` section 1, répertoires vérifiés) :

| Rôle | Emplacement existant pour `social` | Contenu |
| :--- | :--- | :--- |
| Microservice gRPC | `ms-social/` | `src/{config,grpc,common,providers,modules,migrations}`, `config/*.json`, `Dockerfile` |
| Démon outbox | `outbox-runners/outbox-social/` | `src/{config,providers,repositories,runners}`, `Dockerfile` |
| Worker de jobs | `workers-runners/worker-social/` | `src/{config,providers,workers/handlers}`, `Dockerfile` |
| Consommateurs de flux | `post-processors-runner/post-processor-social/` | `src/{post-processors,providers,infrastructure,domain}` |
| Bibliothèque de domaine | `npm-packages/packages/domain-social/` | entités, modèles, repositories, services, migrations de test |
| Contrats gRPC | `proto-registry/proto/volontariapp/social/` | `social.{proto,command,query,responses,services}.proto` |
| Manifestes | `deploy/apps/base/ms-social/` | `deployment{,-outbox,-post-processor,-worker}.yaml`, `service.yaml`, `kustomization.yaml` ; `deploy/infrastructure/databases/ms-social/` |

## 8. Ce qui manque pour le projet

1. Tout le domaine `ranking` (ligne 7 ci-dessus : six emplacements à créer).
2. Les contrats de jobs et l'enum de streams.
3. La RPC `AdminGetRecommendedEventIds` dans `ms-social`.
4. Un adaptateur Jev (API documentée, voir [05](05-scoring-et-jev.md)).
5. La route gateway et le comportement client sur 206.
