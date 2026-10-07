# 08 - Événement `user.badge_awarded`

Dernier maillon commun : il notifie le client qu'un ou plusieurs badges viennent d'être gagnés.

**Statut** : **Implémenté et opérationnel de bout en bout** (`messaging`, `ws-service` et `nativapp`).

## Un message par passage de `pp-user`

Décision 3 du [README](README.md). `pp-user` décide de tous les badges d'un utilisateur en une passe et les écrit dans **une** transaction avec **une** ligne d'outbox. Le message transporte donc la liste.

## Scénario

```mermaid
sequenceDiagram
    autonumber
    participant PU as pp-user
    participant UDB as DB ms-user
    participant OB as outbox
    participant RS as Redis Streams
    participant WS as ws-service
    participant NA as nativapp
    participant Q as React Query

    PU->>UDB: Transaction
    Note right of UDB: INSERT user_badges (N lignes)<br/>INSERT event_queue user.badge_awarded {userId, badges[]}
    OB--)RS: user.badge_awarded
    RS--)WS: UserBadgeAwardedPostProcessor
    Note right of WS: Meme principe que PostLikedPostProcessor :<br/>pas de gather, push direct a l'utilisateur
    WS--)NA: WebSocket user.badge_awarded {badges[]}
    NA->>Q: invalide la query du profil
    NA->>NA: file d'attente de modales (badgeAwardedBus)
```

## Contrats (Implémentés)

| Contrat | Contenu |
| :--- | :--- |
| `UserEventMessagingType.USER_BADGE_AWARDED = 'user.badge_awarded'` | Événement outbox (`messaging`). |
| `IUserBadgeAwardedPayload` | `userId: string`, `badges: IBadgePayload[]` (`messaging`). |
| Type WebSocket `user.badge_awarded` | `WebsocketMessagingType.USER_BADGE_AWARDED` (`messaging`). |
| Stream | `Streams.USER_BADGE_AWARDED` (`shared`). |

## Côté `ws-service` (Implémenté)

`UserBadgeAwardedPostProcessor` (`ws-service/src/post-processors/users/user-badge-awarded.post-processor.ts`) : lit le payload, résout l'utilisateur cible (`userId`), appelle `NotificationService.notifyUser(targetUserId, WebsocketMessagingType.USER_BADGE_AWARDED, ...)`.

## Côté `nativapp` (Implémenté)

1. Listener WebSocket `WebsocketMessagingType.USER_BADGE_AWARDED` dans `nativapp/src/hooks/useNotificationHandlers.ts`.
2. Invalidation de `PROFILE_QUERY_KEY` (TanStack Query) pour rafraîchir les badges du profil.
3. Émission sur `badgeAwardedBus.emit(data.badges)` et toast de félicitations.

## Scénarios d'erreur

| Cas | Comportement |
| :--- | :--- |
| Utilisateur hors ligne | Le push est perdu (WebSocket non persistant). Les badges sont néanmoins en base et visibles au prochain chargement du profil. Pas de modale. |
| `ws-service` indisponible | Le message reste dans le stream, rejoué au retour : la modale arrive en retard. |
| Slug inconnu du front | `ProfileBadges` affiche le rendu de secours (icône générique et nom). |

## Point ouvert

Pour qu'un utilisateur hors ligne voie quand même la modale, il faudrait un marqueur "badge non vu" (ex. `seen_at` sur la liaison utilisateur-badge, ou comparaison avec `awardedAt`). Non prévu dans cette version : à décider si la modale est jugée essentielle ou secondaire.
