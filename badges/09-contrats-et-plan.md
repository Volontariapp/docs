# 09 - Contrats, Plan d'Implémentation et Points Ouverts

## 1. Contrats à créer

| Contrat | Repo | Fichier cible | Utilisé par |
| :--- | :--- | :--- | :--- |
| `event.finished` + `IEventFinishedPayload` (`eventId`, `eventType`) | `npm-packages` | `messaging/src/events/event/payloads.ts` | `ms-event` (émet), `pp-user` (consomme) |
| `event_social.wished` + `IEventSocialWishedPayload` | `npm-packages` | `messaging/src/events/social/payloads.ts` | `ms-social` (émet), `pp-user` (consomme) |
| `user.badge_awarded` + `IUserBadgeAwardedPayload` (`userId`, `badges[]`) | `npm-packages` | `messaging/src/events/user/payloads.ts` | `pp-user` (émet), `ws-service` (consomme) |
| Type WebSocket `user.badge_awarded` | `npm-packages` | `messaging/src/websockets/users/` | `ws-service`, `nativapp` |
| Streams `EVENT_FINISHED`, `EVENT_SOCIAL_WISHED`, `USER_BADGE_AWARDED` | `npm-packages` | `shared/src/enums/streams.enum.ts` | outbox runners, post-processors |
| Migration `badge_progress`, `badge_progress_events` | `ms-user` | `src/migrations/domain/` | `pp-user` |

Aucun changement de proto n'est nécessaire : `PaginationResponse.total` existe (vérifié, [10](10-guide-technique-pp-user.md) section 5), donc `AdminGetUserLikes` et `AdminGetUserWishEvent` suffisent. Pas de cascade `proto-registry`.

Côté `pp-user`, les changements qui ne touchent pas `npm-packages` (config, `AuthModule`, client gRPC, post-processors) sont décrits dans [10](10-guide-technique-pp-user.md).

## 2. Règle du STOP

Toute modification de `npm-packages` impose l'arrêt après `yarn build`, `yarn test`, `yarn changeset add` et `yarn changeset version`. Les microservices consommateurs ne sont modifiés qu'après la publication par la CI. Le plan est donc découpé en vagues bloquantes.

## 3. Vagues

```mermaid
flowchart TD
    V0[Vague 0<br/>Lever les points ouverts] --> V1
    V1[Vague 1<br/>npm-packages : contrats + streams<br/>build, tests, changeset] --> STOP{{STOP<br/>PR + publication CI}}
    STOP --> V2
    V2[Vague 2<br/>ms-user : migrations<br/>ms-event : emet event.finished<br/>ms-social : emet event_social.wished] --> V3
    V3[Vague 3<br/>pp-user : BadgeEvaluator + 5 post-processors<br/>ws-service : UserBadgeAwardedPostProcessor] --> V4
    V4[Vague 4<br/>nativapp : listener + modale + invalidation]
```

| Vague | Contenu | Préalable |
| :--- | :--- | :--- |
| 0 | Trancher les points ouverts ci-dessous. | Aucun. |
| 1 | Contrats et streams dans `npm-packages`. | Vague 0. |
| 2 | Émetteurs (`ms-event`, `ms-social`), migrations `ms-user`, y compris le fallback de `ChangeEventState`. | Publication de la vague 1. |
| 3 | `pp-user` (moteur et 5 consommateurs) et `ws-service`. | Vague 2 déployée. |
| 4 | `nativapp`. | Vague 3 déployée. |

Les consommateurs `pp-user` peuvent être livrés avant les émetteurs sans risque : sans événement, ils restent inactifs.

## 4. Points ouverts

| # | Point | Impact | Document |
| :--- | :--- | :--- | :--- |
### Tranchés

| Point | Décision |
| :--- | :--- |
| Token interne pour `pp-user` | `pp-user` forge son token (clé privée interne montée dans le pod). [10](10-guide-technique-pp-user.md), section 3. |
| Écriture des badges | Via `@volontariapp/domain-user`, en une transaction avec l'outbox. [10](10-guide-technique-pp-user.md), section 6. |
| Total de pagination | Existe. Pas de changement de proto. |
| Événement créé par un admin pour un tiers | Edge case accepté. |
| Atomicité Neo4j et outbox | Non atomique, latence et perte occasionnelle acceptées. |

### Restent ouverts

| # | Point | Impact | Document |
| :--- | :--- | :--- | :--- |
| 1 | Auto-likes non exclus dans la v1 : à valider (le message `post.liked` ne donne pas l'auteur du post). | Abus possible du badge `SOCIAL_LIKE_COUNT_10`. | [05](05-evenement-post-liked.md) |
| 2 | Qui passe un événement à `FINISHED` (humain ou job planifié) ? | Émetteur de `event.finished`. | [07](07-evenement-event-finished.md) |
| 3 | Rattrapage de l'historique de participation. | Utilisateurs existants sans compteur. | [07](07-evenement-event-finished.md) |
| 4 | Modale pour un utilisateur hors ligne (marqueur "non vu"). | Expérience utilisateur. | [08](08-evenement-user-badge-awarded.md) |
| 5 | Le front possède-t-il déjà un mécanisme de listeners WebSocket ? | Taille de la vague 4. | [08](08-evenement-user-badge-awarded.md) |
| 6 | Secret scellé et règle réseau `pp-user` vers `ms-social` / `ms-user` dans `deploy`. | Vague 3, non vérifié. | [10](10-guide-technique-pp-user.md), section 3 |
| 7 | Validation de la sécurité : `pp-user` devient second émetteur de tokens internes (écart à `AGENTS.md` section 6). | Revue du Lead Dev. | [10](10-guide-technique-pp-user.md), section 3 |

## 5. Tests attendus

Conformément aux conventions du projet : mocks dans des fichiers `*.mock.ts`, données via factories `*.factory.ts`, `jest.spyOn()` avec restauration systématique.

| Cible | Cas minimum |
| :--- | :--- |
| `BadgeEvaluator` | Sortie anticipée sans appel réseau quand tout est possédé ; attribution de plusieurs paliers dans une passe ; seuils `>=` ; idempotence sur rejeu. |
| `EventFinishedBadgePostProcessor` | Déduplication `(eventId, userId)` ; événement éco vs socio ; hybride ; reprise après échec partiel. |
| `PostLikedBadgePostProcessor` | Cache Redis hit/miss ; seuil à 9 puis 10 ; courses sur la contrainte unique. |
| `UserBadgeAwardedPostProcessor` | Push avec liste de plusieurs badges ; utilisateur sans socket. |

## 6. Mise à jour des skills

Ce chantier modifiera `pp-user`, `ws-service`, `messaging` et `ms-user`. En fin de chaque vague, lancer `python3 .agents/skills/volontariapp-skill-evolution/scripts/evolve.py plan` pour relire les skills `volontariapp-implement-async-event-flow` et `volontariapp-implement-async-job-flow`.
