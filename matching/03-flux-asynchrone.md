# 03 - Flux asynchrone

Ce document suit le cycle standard de la plateforme (voir [C3](../C3-Async-Patterns-And-Flows.md) et la skill `volontariapp-implement-async-job-flow`) : post-processor, outbox, queue BullMQ, worker, `job_audit`. Aucun appel Redis direct pour créer le job.

## 1. Déclencheurs

Un événement du monde réel invalide la liste d'un ou plusieurs utilisateurs.

| Déclencheur | Flux | Utilisateurs à recalculer | Phase |
| :--- | :--- | :--- | :--- |
| Un utilisateur s'inscrit | `Streams.USER_CREATED` | l'utilisateur (liste initiale, souvent structurelle car historique vide) | V1 |
| Un utilisateur souhaite ou retire un souhait | `Streams.EVENT_SOCIAL_WISHED` / `EVENT_SOCIAL_UNWISHED` | l'utilisateur | V1 |
| Un nouvel événement est créé | `Streams.EVENT_CREATED` | utilisateurs de `matching:active` (fan-out plafonné) | V1 |
| Un événement se termine | `Streams.EVENT_FINISHED` | participants de l'événement (leur historique vient de changer) | V1 |
| Un utilisateur participe ou quitte un événement | aucun flux aujourd'hui | l'utilisateur | V2 (voir ci-dessous) |
| Un utilisateur suit ou bloque quelqu'un | aucun flux aujourd'hui | l'utilisateur | V2 |
| Demande manuelle | RPC `RequestMatchingRefresh` | l'utilisateur | V1 (utile pour la démo) |

**V2** suppose que `domain-social` (`ParticipationService.participateEvent`, `leaveEvent`, `RelationshipService.followUser`, `blockUser`) émette un événement dans `event_queue`, comme le fait déjà `wishEvent` (`participation.service.ts:246`). C'est une modification de `npm-packages` donc soumise à la règle du STOP. La V1 s'en passe : un utilisateur qui participe sans souhaiter verra sa liste se rafraîchir au prochain déclencheur ou à l'expiration de 24 h.

Note sur `EVENT_CREATED` : la saga de création peut encore être compensée après cet événement (voir C3, section Scatter-Gather). Un identifiant d'événement annulé peut donc entrer dans une liste. C'est sans conséquence grâce au filtrage à la lecture ([05](05-lecture-et-fallback.md)).

## 2. Émission du job

Dans `post-processor-social`, chaque déclencheur reçoit un post-processor (ou étend l'existant, par exemple `users/user-created.post-processor.ts`) qui insère une ligne `jobs_outbox` via `JobsOutboxEntity.createJob` et `JobsOutboxRepository`, comme décrit par la skill job-flow.

Contrat à ajouter dans `npm-packages/packages/messaging/src/jobs/social/payloads.ts` :

```typescript
export enum SocialJobType {
  FOLLOW_USER = 'social.follow_user',
  COMPUTE_EVENT_MATCHING = 'social.compute_event_matching',
  FANOUT_EVENT_MATCHING = 'social.fanout_event_matching',
}

export type MatchingRefreshReason =
  | 'USER_CREATED'
  | 'WISH_CHANGED'
  | 'EVENT_FINISHED'
  | 'MANUAL';

export interface IComputeEventMatchingPayload {
  userId: string;
  reason: MatchingRefreshReason;
  requestedAt: string; // ISO 8601
}

export interface IFanoutEventMatchingPayload {
  eventId: string;
}
```

Enregistrement dans `JobRegistry` (`messaging/src/jobs/index.ts`), queue réutilisée : `SocialQueue.SOCIAL`. Ces noms sont des **propositions** : l'enum actuel est `SocialJobType` et le registre est référencé via `JobMessagingType` dans les handlers existants, à aligner sur la convention du fichier au moment de l'implémentation.

## 3. Handler `ComputeEventMatchingHandler`

Emplacement : `workers-runners/worker-social/src/workers/handlers/compute-event-matching.handler.ts`, à raccorder à `SocialWorker` (`handlerMap`) et déclaré dans `app.module.ts`. Il implémente l'`IJobHandler` locale de `worker-social` et retourne obligatoirement `{ originalPayload: job.data.payload }`.

Étapes :

1. **Garde de débounce.** Lire `matching:meta:{userId}`. Si `computedAt` date de moins de 30 s et que `reason !== 'MANUAL'`, retourner immédiatement. Cela absorbe une rafale (3 souhaits en 10 secondes = 1 calcul, pas 3).
2. **Historique.** Via `ParticipationService` (déjà injecté dans l'app du worker) : `getUserParticipations` et `getUserWishes`, plafonnés à 20 identifiants chacun.
3. **Candidats.** `Neo4jParticipationRepository.getRecommendedEventIds` avec `excludeCreatedByMe`, `excludeBlockedUsers`, `excludeParticipatedByMe`, `excludeWishedByMe` à `true`, pagination plafonnée (par exemple 100). Un second appel avec `onlyParticipatedByFriends`, `onlyWishedByFriends`, `onlyCreatedByFriends` à `true` donne l'ensemble « touché par des amis » (signal social).
4. **Texte.** Un appel gRPC `ms-event` (recherche par identifiants, comme le fait la gateway avec `query.ids`) pour les candidats **et** les événements de l'historique. On ne garde que les événements publiés et non terminés.
5. **Score.** Voir [04](04-scoring-et-jev.md). Si Jev échoue, on continue avec le score structurel seul et `source = STRUCTURAL_ONLY`.
6. **Écriture Redis atomique** : pipeline `DEL tmp`, `ZADD tmp`, `EXPIRE tmp`, `RENAME tmp -> matching:{userId}`, puis `HSET matching:meta:{userId}` et `SADD matching:active`.
7. Retourner `{ originalPayload }`.

## 4. Handler `FanoutEventMatchingHandler`

Pour un nouvel événement, le handler lit `matching:active`, puis pour chaque utilisateur (plafond `MATCHING_MAX_FANOUT`, par exemple 200) applique **la même logique que ci-dessus** en appelant directement le service de calcul (pas de nouveaux jobs, pour rester dans le cadre « 1 job = 1 exécution » de la skill). Pour la volumétrie d'un projet de démonstration c'est suffisant ; au-delà, il faudrait émettre un job par utilisateur.

## 5. Idempotence et reprise

- `BaseWorker` saute un job déjà `COMPLETED` dans `job_audit` et rejoue un job resté `PROCESSING` : le handler doit donc supporter d'être rejoué. C'est le cas : le résultat dépend de l'état courant du graphe, l'écriture est un `RENAME` atomique, et la garde de débounce évite le travail inutile.
- Une erreur Jev ne fait **pas** échouer le job (repli structurel). Une erreur Neo4j ou `ms-event` fait échouer le job : BullMQ retente, la liste existante reste servie en attendant.

## 6. Observabilité

Chaque exécution journalise via `@volontariapp/logger` : `userId`, `reason`, nombre de candidats, durée par étape, `source`, et l'issue de l'appel Jev (succès, timeout, erreur). Aucun texte d'événement ni donnée de profil n'est journalisé. Pour diagnostiquer un job bloqué, utiliser la skill `volontariapp-trace-async-flow` (tables `jobs_outbox`, `job_audit`, `event_queue`).

> [!WARNING]
> Bug connu de la plateforme (voir C3) : les échecs de jobs ne remontent pas jusqu'à `jobs_outbox` à cause du décalage `failure`/`failed` du post-processor commun. Un job de matching en échec sera donc visible dans `job_audit` mais pas nettoyé. Sans conséquence fonctionnelle ici (la liste précédente reste servie), mais à ne pas prendre pour un bug du matching.
