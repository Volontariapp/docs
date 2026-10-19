# Fan-out des streams : le cas de `user.deleted`

> [!NOTE]
> **Statut : décision ouverte.** Ce document trace une discussion de conception (2026-10-12). Il décrit l'état réel du code et compare deux designs. Aucune décision n'est prise ni aucun code modifié. Les raisons du design actuel sont déduites du code : aucun ADR ne les documente.

## 1. État actuel (vérifié dans le code)

### Émission

`requestDeletionWithUserDeleted(id)` dans `npm-packages/packages/domain-user/src/repositories/postgres-user.repository.ts:90-127` fait, dans une même transaction :

1. passage du user en `PENDING_DELETION` et renseignement de `deletionRequestedAt` ;
2. création d'un `EventQueueEntity` de type `UserEventMessagingType.USER_DELETED` (`emitter: 'ms-user'`, payload `{ id, role }`) ;
3. insertion dans `event_queue` avec 5 `targetServices` : `Streams.USER_DELETED`, `SOCIAL_USER`, `USER_DELETED_POST`, `USER_DELETED_EVENT`, `USER_DELETED_STORAGE`.

Si le user est déjà `PENDING_DELETION`, rien n'est écrit : pas de second événement.

### Relais vers Redis

`npm-packages/packages/outbox/src/pushers/event-queue.pusher.ts:73-101` boucle sur `targetServices` et fait un `XADD` du même message dans chaque stream (`getEventStreamName(targetService)`), dans un seul pipeline, avec `MAXLEN ~ 10000`. Un événement produit donc **5 copies**, une par stream.

### Consommation

| Stream (`Streams`) | Consommateur | Groupe |
| :--- | :--- | :--- |
| `user:deleted:post` | `post-processor-post/.../user-deleted.post-processor.ts` | `PostUserDeletedPostProcessors` |
| `user:deleted:event` | `post-processor-event/.../user-deleted.post-processor.ts` | non relevé |
| `social:user` | `post-processor-social/.../users/user-deleted.post-processor.ts` | non relevé |
| `user:deleted:storage` | `post-processor-storage/.../user-deleted.post-processor.ts` | non relevé |
| `user:deleted` | `ws-service/.../ws-user-deleted.options.ts` | non relevé |

Chaque post-processor étend `BatchPostProcessor`, filtre via `shouldProcess` sur `USER_DELETED`, purge son domaine, puis écrit un événement `USER_<DOMAINE>_DELETED` (ou `_DELETION_FAILED` après passage en DLQ) dans son propre `event_queue`, ciblé sur `Streams.WS_USER_DELETED_FEEDBACK`. `ws-service` agrège ces retours (Scatter-Gather).

## 2. Constat : un stream pour un consommateur

Chaque stream n'a qu'un consommateur. Le consumer group n'apporte donc rien de plus qu'une file 1:1. Le 1:N est **émulé côté producteur** (5 `XADD`) au lieu d'être délégué à Redis (1 `XADD`, N groupes). AGENTS.md section 4 décrit pourtant les événements comme des Redis Streams 1:N écoutés par les post-processors.

Incohérences de nommage relevées : `user:deleted:post`, `user:deleted:event` et `user:deleted:storage` suivent un schéma, `social:user` est un stream générique (il porte probablement d'autres événements user, à vérifier), `user:deleted` est consommé par `ws-service`.

## 3. Comparaison des deux designs

| | Actuel : N streams | Alternative : 1 stream, N groupes |
| :--- | :--- | :--- |
| Écriture Redis | N `XADD` par événement | 1 `XADD` |
| Fan-out | `targetServices` côté producteur | un consumer group par domaine |
| Ajouter un consommateur | modifier `domain-user` (enum `Streams` + `targetServices`), règle du STOP, changeset, publication | créer un groupe côté consommateur, aucun changement producteur |
| Couplage | le producteur connaît ses consommateurs | le producteur ignore ses consommateurs |
| DLQ | `<stream>-dlq`, de fait une par consommateur | à rendre explicite par groupe |
| Trimming `MAXLEN` | isolé par stream | partagé : un groupe en retard peut perdre des messages |

Raisons plausibles du design actuel : DLQ isolée par consommateur, trimming isolé, routage explicite. Ce sont des déductions, pas des intentions documentées.

## 4. DLQ

La DLQ est dérivée du nom du stream : `retryHelper.getDlqStreamName(this.options.streamName)` (`npm-packages/packages/post-processors/src/core/processors/base.post-processor.ts:565`). Le format exact n'a pas été relu.

**Une DLQ unique lue par N consommateurs est un anti-pattern.** Une DLQ ne se fan-out pas : un message y entre parce qu'**un** groupe a échoué dessus, alors que les autres l'ont peut-être traité avec succès. Si tous les groupes la lisaient, chacun retraiterait des messages qui n'ont échoué que pour un autre, et on perdrait la trace de qui a échoué.

Avec un stream partagé, la DLQ doit être **par groupe** (par exemple `<stream>-dlq:<groupName>`). Cela demande une modification du package `post-processors`.

La skill `volontariapp-trace-async-flow` signale par ailleurs qu'aucune DLQ n'est rejouée automatiquement (problème P2). Ce point est indépendant du choix de design.

## 5. Points à vérifier avant toute migration

- Contenu réel de `social:user` : quels autres événements y transitent, et qui d'autre le lit.
- Noms de groupes des consommateurs `event`, `social`, `storage`, `ws-service`.
- Le trimming `MAXLEN ~ 10000` ignore les groupes en retard : mesurer l'exposition sur un stream partagé.
- Compatibilité à la migration : pendant la transition, producteur et consommateurs sont déployés indépendamment (règle du STOP, publication CI via `npm-packages`).

## 6. Recommandation

Conserver le design actuel pour `user.deleted` tant qu'il fonctionne. Trancher la cible par un ADR, car la décision touche tous les événements outbox et pas seulement celui-ci (outils : `domain-modeling` ou `grill-with-docs`).

## 7. Décisions ouvertes

- [ ] Stream unique avec consumer groups, ou streams dédiés par consommateur ?
- [ ] Format de la DLQ si stream partagé (par groupe).
- [ ] Faut-il unifier le nommage des streams (`social:user` notamment) ?
