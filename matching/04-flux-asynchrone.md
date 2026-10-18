# 04 - Flux asynchrone

Ce document suit le cycle standard de la plateforme (voir [C3](../C3-Async-Patterns-And-Flows.md) et la skill `volontariapp-implement-async-job-flow`) : post-processor, outbox, queue BullMQ, worker, `job_audit`, puis événement de fin. **Aucun appel Redis direct** pour créer un job : toujours une ligne `jobs_outbox` via `JobsOutboxEntity.createJob` et `JobsOutboxRepository`, avec `emitter: 'ms-ranking'` partout.

## 1. Événements en amont, job au milieu, événement en aval

| Rôle | Mécanisme | Raison |
| :--- | :--- | :--- |
| Déclencheur | **Événement** de flux (1:N) | plusieurs services peuvent s'y abonner |
| Calcul | **Job** (1:1) | réessais BullMQ, audit, contrôle de la concurrence |
| Fin du calcul | **Événement** (`ranking:job:outbox:success`, puis `ws:jobs-outbox-success` si un mapping existe, section 9) | le client peut réagir |

Un calcul n'est jamais fait dans un post-processor : un appel externe lent bloquerait le lot du flux.

## 2. Déclencheurs

| Déclencheur | Flux réellement consommé | Utilisateurs | `reason` | File | Phase |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Inscription | **`Streams.SOCIAL_USER`** (`social:user`), filtré sur le type `user.created` | l'utilisateur | `USER_CREATED` | fond | V1 |
| Souhait ajouté/retiré | `Streams.EVENT_SOCIAL_WISHED`, `EVENT_SOCIAL_UNWISHED` | l'utilisateur | `WISH_CHANGED` | fond | V1 |
| Nouvel événement | `Streams.EVENT_CREATED` | utilisateurs actifs (fan-out) | `EVENT_CREATED` | fond | V1 |
| Événement terminé | `Streams.EVENT_FINISHED` | participants | `EVENT_FINISHED` | fond | V1 |
| Lecture sans liste | `GetRankingEvents` | l'utilisateur | `ON_DEMAND` | **fallback** | V1 |
| Liste périmée (âge ou version) | `GetRankingEvents` | l'utilisateur | `STALE_REFRESH` | fond | V1 |
| Demande manuelle | `RequestRankingRefresh` | l'utilisateur | `MANUAL` | **fallback** | V1 |
| Suppression de compte | `user:deleted:ranking` (à créer, [03](03-modele-de-donnees.md) section 5) | l'utilisateur supprimé | n/a | purge directe, sans job de calcul | V1 |
| Post lié à un événement créé ou supprimé | `POST_CREATED` (payload avec `eventId`), `POST_DELETED` | n/a | n/a | écriture ou suppression dans `ranking_event_mention` (pas de calcul) | V1 |
| Participation, départ, follow, block | aucun flux aujourd'hui | l'utilisateur | `PARTICIPATION_CHANGED`, `RELATION_CHANGED` | fond | V2 |

Correction apportée par la revue : **l'inscription ne passe pas par `Streams.USER_CREATED`**. Le trigger SQL de `domain-user` écrit `target_services = ARRAY['social:user']` (`domain-user/src/database/triggers/users.trigger.sql:27`) et `post-processor-social` consomme `Streams.SOCIAL_USER` (`post-processors/users/options/user-created.options.ts:10`). `Streams.USER_CREATED` (`user:created`) est écouté par `ws-service` mais aucun producteur applicatif n'a été trouvé. `post-processor-ranking` consomme donc `social:user` avec **son propre groupe de consommateurs**.

**Les événements de souhait peuvent être perdus.** `wishEvent` écrit d'abord dans Neo4j puis insère dans `event_queue` (deux magasins, donc non atomique), et l'échec de l'insertion est avalé par un `logger.warn` (`domain-social/src/services/participation.service.ts:246-265`). Conséquence de conception : le rafraîchissement `STALE_REFRESH` n'est pas une option mais **le filet de sécurité** qui borne l'âge maximal d'une liste.

**V2** (participation, follow) demande que `domain-social` émette un événement dans `event_queue` pour `participateEvent`, `leaveEvent`, `followUser`, `unfollowUser`, `blockUser` : modification de `npm-packages` soumise au STOP. La V1 s'en passe.

`EVENT_CREATED` peut être suivi d'une compensation de saga (voir C3) : un ID d'événement annulé peut entrer dans une liste, sans conséquence puisque la gateway n'affiche que ce que `ms-event` renvoie.

## 3. Contrats de jobs (`npm-packages/packages/messaging`)

Fichiers `src/jobs/ranking/{payloads,queue}.ts`, enregistrés dans `src/jobs/index.ts` (`JobRegistry`, `JobMessagingType`) sur le modèle de `src/jobs/social/`.

```typescript
export enum RankingJobType {
  COMPUTE_USER_RANKING = 'ranking.compute_user_ranking',
  FANOUT_RANKING = 'ranking.fanout',
}

export type RankingComputeReason =
  | 'USER_CREATED' | 'WISH_CHANGED' | 'EVENT_CREATED' | 'EVENT_FINISHED'
  | 'ON_DEMAND' | 'STALE_REFRESH' | 'MANUAL';

export interface IComputeUserRankingPayload {
  userId: string;
  reason: RankingComputeReason;
  requestedAt: string; // ISO 8601, sert a la coalescence (section 6)
}

export interface IFanoutRankingPayload {
  trigger: 'EVENT_CREATED' | 'EVENT_FINISHED' | 'POST_CREATED';
  eventId?: string;   // declencheurs d'evenement
  postId?: string;    // POST_CREATED
  authorId?: string;  // POST_CREATED
  requestedAt: string;
}

export enum RankingQueue {
  RANKING = 'ranking-queue',                   // fond (evenements)
  FEED = 'ranking-feed-queue',                  // fond (posts), voir 11
  FALLBACK_RANKING = 'fallback-ranking-queue', // ON_DEMAND et MANUAL, tous types de liste
}
```

Le type `COMPUTE_USER_FEED` et le feed de posts sont décrits en [11](11-feed-conception.md). Le champ du fan-out s'appelle `trigger` (et non `kind`) pour ne pas être confondu avec `list_kind`.

Deux files : un calcul `ON_DEMAND` correspond à un utilisateur qui attend un écran ; il ne doit pas attendre derrière un fan-out.

**Ce nommage rompt une convention existante** : les jobs en file `FALLBACK_*` sont aujourd'hui de type `FALLBACK_*` et mappés sur des événements WebSocket du même nom (`JOB_TO_EVENT_MAPPING`). Ici le type `ranking.compute_user_ranking` circule dans les deux files. C'est un choix assumé (un seul handler, une seule logique), à consigner.

Streams à ajouter (`npm-packages/packages/shared/src/enums/streams.enum.ts`) : `RankingStream.RANKING_JOB_OUTBOX_SUCCESS = 'ranking:job:outbox:success'` et `..._FAILURE`, à inclure dans `Streams` et dans le type union.

## 4. Émission des jobs : `post-processor-ranking`

Basé sur `BatchPostProcessor` (`post-processors/src/core/processors/batch.post-processor.ts`), qui fournit déjà un **verrou d'idempotence Redis par `(groupName, messageId)`** (`idempotencyTtlSeconds`), des réessais et une DLQ. Un lot qui échoue est rejoué en entier : `processEvents` doit donc être idempotent par élément.

| Post-processor | Flux | Action |
| :--- | :--- | :--- |
| `UserCreatedRankingPostProcessor` | `SOCIAL_USER` (type `user.created`) | demande de calcul `USER_CREATED` |
| `EventWishChangedRankingPostProcessor` | `EVENT_SOCIAL_WISHED`, `UNWISHED` | demande de calcul `WISH_CHANGED` |
| `EventCreatedRankingPostProcessor` | `EVENT_CREATED` | job `FANOUT_RANKING` |
| `EventFinishedRankingPostProcessor` | `EVENT_FINISHED` | job `FANOUT_RANKING` |
| **`JobOutboxSuccessPostProcessor`** (commun) | `RANKING_JOB_OUTBOX_SUCCESS` | supprime la ligne `jobs_outbox` et émet le feedback WebSocket |
| **`JobOutboxFailedPostProcessor`** (commun) | `RANKING_JOB_OUTBOX_FAILURE` | voir section 10 (défectueux) |

**Les deux post-processors communs sont obligatoires** : `post-processor-social` les enregistre (`post-processors.module.ts` lignes 9-10 et 48-80, options dans `options/job-outbox-success-options.ts` avec le stream `SOCIAL_JOB_OUTBOX_SUCCESS`). Sans eux dans `post-processor-ranking`, le stream `ranking:job:outbox:success` n'est jamais consommé : les lignes `jobs_outbox` ne sont jamais supprimées et aucune notification n'est émise.

Une **demande de calcul** est écrite par la procédure de [03](03-modele-de-donnees.md) section 2 (`ranking_request` + ligne `jobs_outbox`, une seule transaction), avec `scheduled_at` :

- `USER_CREATED`, `WISH_CHANGED`, `STALE_REFRESH`, `POST_PUBLISHED`, `EVENT_CREATED`, `EVENT_FINISHED` (jobs issus d'un fan-out) : `scheduled_at = now + RANKING_DEBOUNCE_SECONDS` (30 s). Le délai laisse arriver les demandes suivantes qui seront coalescées (section 6).
- `ON_DEMAND`, `MANUAL` : `scheduled_at = now`.
- `requestedAt` du job = la valeur `requested_at` **retournée par l'`INSERT` sur `ranking_request`** (horloge de la base `ms-ranking`), et non l'horloge du processus qui écrit le job ([03](03-modele-de-donnees.md)).

Le post-processor valide le payload et ignore un message mal formé sans lever d'exception.

## 5. Handler `ComputeUserRankingHandler` : ordre normatif

Emplacement : `workers-runners/worker-ranking/src/workers/handlers/compute-user-ranking.handler.ts`. Il retourne `{ originalPayload: job.data.payload }`. Le patron de retour à copier est celui de `worker-event` (`IJobHandler` qui retourne `{ originalPayload }`), pas celui de `worker-social` dont l'interface retourne `Promise<void>`.

**Étape 0 : coalescence (sans verrou).**
Lire `ranking_run`. Si `ranking_run.started_at >= job.requestedAt` **et** `formula_version` est la version courante : une liste calculée à partir d'un état postérieur à cette demande existe déjà. Terminer le job sans rien faire. (Voir section 6 pour la justification.)

**Étape 1 : mesure.** `startedAt = now()`.

**Étape 2 : jeton interne.** `jwtService.signInternal({ id: 'worker-ranking', role: UserRoles.ADMIN })`, avec cache applicatif de 4 minutes (patron de `social-interaction.client.ts:77-82`).

**Étape 3 : historique.** `AdminGetUserParticipateEvent` et `AdminGetUserWishEvent` pour le `userId` (au plus `RANKING_HISTORY_SIZE` = 20 identifiants chacun, pour le résumé de goût). Pour les **exclusions**, lire aussi `AdminGetUserEvent` (créés) et les listes participées/souhaitées complètes (pagination par 50, plafond `RANKING_EXCLUDE_LIMIT` = 500), ainsi que les `PASS` de moins de `RANKING_PASS_COOLDOWN_DAYS` (30) dans `ranking_event_feedback` : ces événements sont retirés des candidats.

**Étape 4 : candidats depuis `ms-event` (source de vérité).**
Correction majeure de la revue : la requête Neo4j `getRecommendedEventIds` ne convient pas à la génération de candidats. Sans filtre « amis », c'est `MATCH (e:SocialEvent) ... WITH DISTINCT e RETURN e.eventId SKIP $skip LIMIT $limit` (`neo4j-participation.repository.ts`, plage 213-289) : **pas de `ORDER BY`**, le nœud ne porte que `eventId` (donc aucun filtre de date ni d'état), et la pagination `SKIP/LIMIT` sans tri est instable. Cent identifiants arbitraires deviendraient vite des événements terminés ou supprimés.

Les candidats viennent donc de `ms-event.searchEvents` avec des paramètres qui **existent** dans `SearchEventsQuery` (`proto-registry/proto/volontariapp/event/event.query.proto:13-26`) : `statuses = [PUBLISHED]`, `start_date_from = now`, `pagination.limit = RANKING_CANDIDATE_LIMIT` explicite (la valeur par défaut du repository est 10, `domain-event/src/repositories/postgres-event.repository.ts`), tri par défaut `createdAt DESC`. On obtient aussi le texte (`name`, `description`, `type`, `tags`, `startAt`, `organizerId`) dans le même appel. Les événements de l'historique sont lus avec le même appel (par `ids`, pagination explicite).

Mise en garde vérifiée : `only_available` signifie seulement `state = PUBLISHED` côté repository, **pas** « places restantes ». Aucun filtre de capacité n'existe. Le filtre « complet » se fait donc sur `currentParticipants >= maxParticipants` après lecture, côté worker (pour éviter de remplir la liste d'événements complets) et à nouveau côté gateway. La RPC `GetEventsByIds` existe (`event.services.proto:19`) mais fait un `findById` par identifiant (N+1, erreurs avalées, aucun filtre d'état) : à éviter pour le lot du worker.

**Étape 5 : signal du graphe.** Un appel à `AdminGetRecommendedEventIds` (nouvelle RPC) avec `excludeCreatedByMe`, `excludeBlockedUsers`, `excludeParticipatedByMe`, `excludeWishedByMe` à `true` et une pagination large (1000, comme `listEvents` dans la gateway) renvoie l'ensemble des événements **autorisés** par le graphe. Les candidats de l'étape 4 sont intersectés avec cet ensemble (ce qui applique les blocages dans les deux sens). Un second appel avec `onlyParticipatedByFriends`, `onlyWishedByFriends`, `onlyCreatedByFriends` à `true` renvoie l'ensemble « touché par au moins un ami ».

Le signal « amis » est donc **booléen** (touché ou non par un ami), pas un compte : la requête ne renvoie que des identifiants dédupliqués (`WITH DISTINCT e RETURN e.eventId`) et combine les trois relations par union. Un vrai compte d'amis demanderait une nouvelle requête Cypher qui retourne `(eventId, friendCount)` et un message proto adapté ; c'est une évolution possible (voir [09](09-plan-de-livraison.md)).

**Étape 6 : score structurel** ([05](05-scoring-et-jev.md)). La position de l'utilisateur est lue dans `ranking_user_location` (repli : zone d'origine déduite de l'historique) ; les entrées de popularité sont lues dans les tables locales de [03](03-modele-de-donnees.md) section 2 bis. Les codes d'explication (`reasons`) sont calculés ici ([13](13-decisions-v1.md) section 6).

**Étape 7 : score sémantique.** Une requête Jev. Toute erreur Jev tolérable donne le repli structurel (section 8).

**Étape 8 : écriture** : transaction courte avec verrou consultatif, anti-écrasement et suppression de `ranking_request` ([03](03-modele-de-donnees.md) section 3).

**Étape 9 :** retourner `{ originalPayload }`.

## 6. Coalescence : sauter seulement quand une liste plus récente existe

Un anti-rebond fondé sur le temps (« sauter si le calcul date de moins de 30 s ») est incorrect : le job sauté est `COMPLETED`, le recalcul nécessaire n'a jamais lieu et la liste reste sans le nouvel élément. La règle retenue est :

> Un job de calcul est sauté **si et seulement si** un calcul commencé **après** sa demande a déjà écrit une liste (`ranking_run.started_at >= job.requestedAt`).

Rafale de trois souhaits à `t0`, `t0+5`, `t0+9` : trois jobs planifiés à `t0+30`, `t0+35`, `t0+39`. Le premier démarre à `t0+30` (`started_at` postérieur aux trois `requestedAt`), écrit la liste ; les deux autres voient `started_at >= requestedAt` et sautent. Un souhait à `t0+31`, arrivé **après** le début du calcul, a `requestedAt > started_at` : son job calcule à nouveau. Aucune demande n'est perdue, et aucun calcul n'est répété sans nécessité.

`MANUAL` et `ON_DEMAND` suivent la même règle : leur `requestedAt` est la date de la demande, donc ils ne sautent que si une liste plus récente existe déjà.

## 7. Handler `FanoutRankingHandler`

- `EVENT_CREATED` : lire les utilisateurs actifs par **curseur** (`ranking_run` avec `list_kind = 'EVENT'`, fenêtre `RANKING_ACTIVE_DAYS`, plafond `RANKING_MAX_FANOUT` trié par activité décroissante) et, dans une seule transaction, écrire une demande de calcul par utilisateur (`scheduled_at = now + 30 s`).
- `EVENT_FINISHED` : lire les participants via `GetEventParticipants` (paginé par 50, **sans plafond** : leur historique a changé).
- `POST_CREATED` : voir [11](11-feed-conception.md) section 7 (abonnés paginés par 50, intersectés avec les utilisateurs actifs de `list_kind = 'POST'`, dédupliqués, plafonnés ; `emitterId` du job de fan-out = `postId`).

Dans tous les cas l'`emitterId` du job de fan-out est l'identifiant de l'objet déclencheur (`eventId` ou `postId`), et l'`emitter` vaut `'ms-ranking'`.

Amplification connue : 10 événements créés en une minute produisent jusqu'à 10 demandes par utilisateur actif ; la coalescence (section 6) les réduit à un ou deux calculs par utilisateur. Les utilisateurs actifs au-delà du plafond ne sont pas recalculés après un événement et ne le verront qu'au `STALE_REFRESH` : limite assumée à ce volume.

## 8. Erreurs et reprises

| Cas | Comportement |
| :--- | :--- |
| Job rejoué après un job `COMPLETED` | `BaseWorker` saute : il consulte d'abord une clé Redis `job:completed:<id>` (TTL 24 h), puis la base (`base.worker.ts:77-132`). Si Redis est vide et l'audit absent, le job est rejoué : sans danger ici |
| Job interrompu en `PROCESSING` | rejoué ; le calcul est rejouable |
| Doublon d'événement de flux | masqué par le verrou d'idempotence de `BatchPostProcessor`, puis par la coalescence |
| Erreur `ms-social` ou `ms-event` | le job échoue, BullMQ réessaie (3 tentatives par défaut), l'ancienne liste reste servie |
| Jev `429`, `529` | 2 réessais avec attente exponentielle, puis repli structurel |
| Jev `401` | repli structurel, journal `error`, alerte |
| Jev `422` | **dégrader par sous-lot** : diviser les questions en deux et réessayer récursivement (une seule question invalide ne doit pas faire perdre les 29 autres), puis repli structurel pour les questions isolées en erreur |
| Deux calculs simultanés du même utilisateur | le dernier à committer ne peut pas écraser un calcul plus récent (anti-écrasement par `started_at`) |

`RANKING_WORKER_CONCURRENCY` : le champ existe dans `workers/src/interfaces/worker-app-config.interface.ts:5` mais aucun worker existant ne le règle ; il suppose de passer `{ concurrency }` à `@Processor(...)`. Valeur par défaut BullMQ : 1. Un `@Processor(queue)` est **par classe** : il faut deux classes (`ranking.worker.ts` et `fallback-ranking.worker.ts`, comme `worker-event` avec `event.worker.ts` et `fallback-event.worker.ts`).

## 9. Notification de fin de calcul : le circuit WebSocket n'existe pas encore pour ce domaine

Vérifications de la revue : `JobOutboxSuccessPostProcessor` appelle `getEventForJob(jobType)` et, **sans mapping**, ne produit rien (`packages/post-processors/src/common/job-outbox-success.post-processor.ts`, log debug « No feedback event emitted »). `JOB_TO_EVENT_MAPPING` (`packages/messaging/src/websockets/events/mapping.ts`) ne contient que des types `FALLBACK_*`. Côté `ws-service`, `post-processors/jobs/job-outbox-success.post-processor.ts` ne notifie que si `getWsEventForEvent(event.type)` existe **et** si `originalPayload.userId` est présent.

Il faut donc, dans `npm-packages/messaging` (inclus dans le second STOP) :

1. une valeur `EventEventMessagingType` (par exemple `RANKING_READY`) ;
2. son entrée dans `JOB_TO_EVENT_MAPPING` pour `ranking.compute_user_ranking` ;
3. son entrée dans `EVENT_EVENT_TO_WS_EVENT_MAPPING` ;
4. une valeur `EventWebsocketMessagingType` ;
5. le handler correspondant dans `nativapp`.

Le mapping est **par type de job**, pas par `reason`. Conséquences : (a) chaque calcul réussi notifie le client, y compris ceux sautés par la coalescence (ils finissent `COMPLETED`) ; (b) le handler client doit être idempotent (simple invalidation de requête) et regrouper les invalidations rapprochées ; (c) `FANOUT_RANKING` n'a pas de mapping ou pas de `userId`, donc aucune notification, ce qui est voulu.

## 10. Chemin d'échec : deux défauts, pas un

Le dossier ne mentionnait que le décalage de nom. La revue en identifie deux :

1. `JobOutboxFailedPostProcessor` n'accepte que `:job:outbox:failed` alors que le trigger émet `:job:outbox:failure` (`ms-social/src/migrations/common/1781300000000-FixJobAuditTriggerTargetServices.ts`).
2. Même avec le nom corrigé, il fait `UPDATE ... WHERE status = PENDING`, or la ligne est `COMPLETED` dès le push BullMQ (`outbox.consumer.ts`, `processItems`) : il ne matche jamais.

De plus, `BaseWorker` écrit `FAILED` dans `job_audit` à **chaque tentative** (`base.worker.ts:211-232`, 3 tentatives par défaut), donc le trigger émet un événement `failure` pour des échecs qui seront rattrapés. Si le bug était corrigé, le client recevrait un échec pour un job qui finit en succès.

Conséquence pour nous : aucune notification d'échec n'atteindra le client, d'où le délai d'attente côté application ([06](06-lecture-et-206.md)), et un échec n'est observable que par `job_audit` (alerte, [08](08-tests-observabilite-securite.md)).

## 11. Configuration

| Clé | Défaut | Rôle |
| :--- | :--- | :--- |
| `RANKING_LIST_SIZE` | 100 | lignes conservées par utilisateur |
| `RANKING_CANDIDATE_LIMIT` | 150 | candidats lus dans `ms-event` |
| `RANKING_HISTORY_SIZE` | 20 | événements d'historique pour le résumé de goût |
| `RANKING_EXCLUDE_LIMIT` | 500 | identifiants d'exclusion lus |
| `RANKING_JEV_CANDIDATES` | 30 | candidats envoyés à Jev |
| `RANKING_DEBOUNCE_SECONDS` | 30 | délai de planification des demandes de fond |
| `RANKING_REQUEST_TTL_SECONDS` | 120 | durée avant qu'une demande sans résultat soit réémise |
| `RANKING_STALE_AFTER_HOURS` | 24 | âge déclenchant `STALE_REFRESH` |
| `RANKING_ACTIVE_DAYS` | 30 | fenêtre des utilisateurs actifs |
| `RANKING_MAX_FANOUT` | 1000 | plafond d'un fan-out `EVENT_CREATED` |
| `RANKING_WORKER_CONCURRENCY` | 5 | concurrence BullMQ (à câbler dans `@Processor`) |
| `RANKING_PASS_COOLDOWN_DAYS` / `RANKING_MAX_DISTANCE_KM` / `RANKING_BUZZ_WINDOW_DAYS` / `RANKING_LOCATION_REFRESH_KM` | 30 / 100 / 14 / 10 | exclusion après un `PASS`, rayon maximal, fenêtre des mentions, seuil de déplacement déclenchant un recalcul |
| `RANKING_FEED_LIST_SIZE` / `_AUTHORS` / `_MAX_AGE_DAYS` / `_MAX_FANOUT` / `_MIN_ITEMS` | 100 / 200 / 7 / 200 / 20 | taille de liste, auteurs candidats, âge maximal, plafond de fan-out, minimum avant complément |
| `RANKING_FEED_STALE_AFTER_HOURS` | 2 | âge déclenchant `STALE_REFRESH` pour les posts (distinct de `RANKING_STALE_AFTER_HOURS` = 24 pour les événements) |
| `RANKING_FEED_LIKES_LIMIT` / `_LOG_RETENTION_DAYS` | 200 / 90 | likes réconciliés par calcul, rétention du journal |
| `RANKING_FEED_RECOMPUTE_ON_SIGNAL` | `false` | recalcul sur like ou commentaire (délai de 5 min si activé) |
| `RANKING_FEED_JEV_ENABLED` | `false` | composante sémantique du feed |
| `RANKING_REFRESH_BUCKET_CAPACITY` / `RANKING_REFRESH_WINDOW_SECONDS` | 5 / 60 | seau à jetons des rafraîchissements ([13](13-decisions-v1.md) section 3 bis) |
| `RANKING_LOCATION_KEY` | aucun | clé de 32 octets aléatoires pour chiffrer la position (secret scellé) |
| `TYPESAFE_API_KEY` | aucun | clé API Jev (SealedSecret) |
| `JEV_TIMEOUT_MS` | 10000 | délai d'une requête Jev (à valider par la mesure) |

Le worker doit aussi disposer de la **clé privée de signature interne** : `auth.internalPrivateKeyPath` dans `config/default.config.json` et un dossier `certs/` (voir `workers-runners/worker-social/`), à fournir par SealedSecret ou volume en déploiement.

## 12. Observabilité du flux

Journaux via `@volontariapp/logger` : `userId`, `reason`, comptes de candidats, durées par étape, `source`, issue de Jev. Jamais de texte d'événement ni de résumé de goût. Diagnostic d'un job bloqué : skill `volontariapp-trace-async-flow`.
