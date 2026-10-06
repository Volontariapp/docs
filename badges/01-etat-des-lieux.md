# 01 - État des Lieux

Constat du code au moment de la rédaction. Chaque ligne indique le fichier vérifié.

## Ce qui existe

| Élément | Où | Détail |
| :--- | :--- | :--- |
| Table `badges` et seed des 13 badges | `ms-user/src/migrations/domain/1780000000001-SeedDefaultBadges.ts` | `name`, `slug`, `description`. |
| CRUD badges (gRPC) | `proto-registry/proto/volontariapp/user/user.services.proto` (`BadgeService`) | Create, Update, Delete, Get, GetBySlug, List. |
| Attribution manuelle | `api-gateway/.../user-admin.command-controller.ts:101` | `POST /users/:id/badges`, rôle `ADMIN`, RPC `AddBadgeToUser`. C'est le seul appelant. |
| Affichage front | `nativapp/src/components/dataDisplay/badge/*`, `profile/ProfileBadges.tsx` | Médaillons, modale de détail, résolution par slug. |
| Événement `post.liked` | `domain-social/.../interaction.service.ts:55` | Émis par `ms-social` via l'outbox (`Streams.POST_LIKED`). Consommé uniquement par `ws-service` (`post-liked.post-processor.ts`). |
| Saga de création d'événement | `ws-service/src/post-processors/base-gather.post-processor.ts` | À la complétion du gather, `ws-service` écrit `event.creation_successfull` dans l'outbox (stream `Streams.EVENT_SUCCESSFULLY_CREATED`), avec `userId = metadata.emitterId`. Consommé par `post-processor-event` pour passer la saga à `DONE`. |
| Saga de création de post | idem | Même mécanisme, stream `Streams.POST_SUCCESSFULLY_CREATED`. |
| RPC de participation et de wishlist | `social.services.proto` | `PostUserParticipateEvent`, `PostUserWishEvent`, `GetUserWishEvent`, `GetEventParticipants`, variantes `Admin*` avec `user_id`. |
| `EventType` et `EventState` | `event/event.proto` | `SOCIAL`, `ECOLOGY` ; `DRAFT`, `PUBLISHED`, `IN_PROGRESS`, `FINISHED`, `CANCELLED`. |
| Base Postgres dans `pp-user` | `post-processor-user/.../post-processors.module.ts` | `PostgresProvider` et `RedisProvider` sont connectés. |

## Ce qui manque

| Manque | Conséquence |
| :--- | :--- |
| Aucun consommateur d'événement ne déclenche `AddBadgeToUser`. | Aucun badge n'est attribué automatiquement. Les seuils affichés par le front ("5 événements", "10 likes") ne sont vérifiés nulle part. |
| `pp-user` n'a que deux post-processors (`JobOutboxSuccess`, `JobOutboxFailed`). | Aucune logique métier de badge. |
| Pas d'événement `event.finished` (`ChangeEventState` vers `FINISHED` n'émet rien). | Impossible de réagir à la fin d'un événement. |
| Pas d'événement pour la wishlist (`PostUserWishEvent`) ni pour la participation. | Rien à consommer. |
| Pas d'événement `user.badge_awarded`, ni de type WebSocket associé. | Le client ne peut pas être notifié. |
| `ms-social` stocke un nœud d'événement réduit à `event_id` (`CreateSocialEventCommand`). Les requêtes de participation renvoient uniquement des `ids`. | `ms-social` ne peut pas répondre à "combien d'événements terminés de type éco ?". |
| Aucun client gRPC sortant dans `pp-user`. | Pas de moyen actuel d'interroger `ms-social` depuis `pp-user`. |

## Points tranchés

| Point | Décision | Détail technique |
| :--- | :--- | :--- |
| Token interne pour appeler `ms-social` | `pp-user` forge son propre token (JWT RS256, `x-internal-token`). | [10](10-guide-technique-pp-user.md), section 3. |
| Écriture des badges | `pp-user` utilise `@volontariapp/domain-user` et une transaction unique. | [10](10-guide-technique-pp-user.md), section 6. |
| Total de pagination | `PaginationResponse.total` existe (vérifié dans `pagination.proto`). | [10](10-guide-technique-pp-user.md), section 5. |
| Événement créé par un admin pour un tiers | Edge case accepté : le badge va à l'émetteur. | [03](03-evenement-event-creation-successfull.md). |
| Atomicité Neo4j et outbox | Non atomique (best effort, vérifié). Latence et pertes occasionnelles acceptées. | [10](10-guide-technique-pp-user.md), section 8. |

## Points encore non vérifiés

- Les valeurs exactes des entrées de `Streams` (seules les clés `EVENT_SUCCESSFULLY_CREATED`, `POST_SUCCESSFULLY_CREATED`, `POST_LIKED`, `USER_JOB_OUTBOX_SUCCESS` sont confirmées, `POST_LIKED = 'post-liked'`).
- Un `groupName` distinct de celui de `pp-event` suffit-il pour lire `EVENT_SUCCESSFULLY_CREATED` en parallèle (comportement standard de Redis Streams, non testé ici).
- Valeur minimale acceptée pour `PaginationRequest.limit`.
- Existence d'un mécanisme de listeners WebSocket dans `nativapp`.
