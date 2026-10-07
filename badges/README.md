# Badges - Attribution Asynchrone Automatique

Ce dossier décrit comment les 13 badges de Volontariapp sont débloqués automatiquement, et comment l'utilisateur est notifié en temps réel.

> [!NOTE]
> **Statut : En cours d'implémentation (3/13 badges déployés et validés en production).**
> - Badges fonctionnels et vérifiés en production : `EVENT_HOST_COUNT_1` ([03](03-evenement-event-creation-successfull.md)), `COMMUNITY_POST_COUNT_1` ([04](04-evenement-post-creation-successfull.md)), et `SOCIAL_LIKE_COUNT_10` ([05](05-evenement-post-liked.md)).
> - Prochaine étape : `EVENT_WISHLIST_COUNT_10` ([06](06-evenement-event-social-wished.md)) et les badges de participation ([07](07-evenement-event-finished.md)).

## Principe en une phrase

Un microservice émet un événement via l'outbox. Le post-processor `pp-user` le consomme, évalue les règles de badges, écrit les badges gagnés dans la base de `ms-user` avec un événement `user.badge_awarded` (même transaction), et `ws-service` pousse ce dernier au client, qui affiche une modale unique.

## Décisions actées

| # | Décision | Raison |
| :--- | :--- | :--- |
| 1 | La participation compte à `FINISHED` (nouvel événement `event.finished`), pas à l'inscription. | Un inscrit/désinscrit répété suffirait à farmer les paliers. |
| 2 | Un badge est un acquis : jamais retiré (unlike, désinscription, suppression de contenu). | Cohérence produit, et aucune logique de révocation à maintenir. |
| 3 | Un seul message WebSocket par passage de `pp-user`, avec la liste des badges gagnés. | Une seule modale côté client, pas d'ordre d'arrivée aléatoire. |
| 4 | Les badges de participation reposent sur des compteurs incrémentaux dans `ms-user`. | `ms-social` ne connaît ni l'état ni le type d'un événement (voir [07](07-evenement-event-finished.md)). |
| 5 | Pas de Scatter-Gather pour les badges. | Un seul service décide, il n'y a rien à agréger. |

## Catalogue des 13 badges

La source de vérité visuelle est `nativapp/src/components/dataDisplay/badge/badge.config.ts`. Le seed backend est `ms-user/src/migrations/domain/1780000000001-SeedDefaultBadges.ts`. Les slugs sont identiques.

| Statut | Slug | Nom | Condition | Événement déclencheur | Document |
| :---: | :--- | :--- | :--- | :--- | :--- |
| [x] | `EVENT_HOST_COUNT_1` | Bâtisseur·se | Créer 1 événement | `event.creation_successfull` | [03](03-evenement-event-creation-successfull.md) |
| [x] | `COMMUNITY_POST_COUNT_1` | Première Plume | Poster 1 post | `post.creation_successfull` | [04](04-evenement-post-creation-successfull.md) |
| [x] | `SOCIAL_LIKE_COUNT_10` | Soutien du cœur | Liker 10 posts | `post.liked` | [05](05-evenement-post-liked.md) |
| [ ] | `EVENT_WISHLIST_COUNT_10` | Curieux·se | Wishlist 10 événements | `event_social.wished` (nouveau) | [06](06-evenement-event-social-wished.md) |
| [ ] | `EVENT_PARTICIPATION_TIER_1` | Premier Pas | 1 événement | `event.finished` (nouveau) | [07](07-evenement-event-finished.md) |
| [ ] | `EVENT_PARTICIPATION_TIER_2` | Engagé·e | 5 événements | `event.finished` | [07](07-evenement-event-finished.md) |
| [ ] | `EVENT_PARTICIPATION_TIER_3` | Pilier | 10 événements | `event.finished` | [07](07-evenement-event-finished.md) |
| [ ] | `EVENT_PARTICIPATION_TIER_4` | Figure locale | 20 événements | `event.finished` | [07](07-evenement-event-finished.md) |
| [ ] | `EVENT_SOCIAL_TIER_1` | Cœur Solidaire | 1 événement socio | `event.finished` | [07](07-evenement-event-finished.md) |
| [ ] | `EVENT_SOCIAL_TIER_2` | Tisseur·se de liens | 5 événements socio | `event.finished` | [07](07-evenement-event-finished.md) |
| [ ] | `EVENT_ECOLOGY_TIER_1` | Graine d'écolo | 1 événement éco | `event.finished` | [07](07-evenement-event-finished.md) |
| [ ] | `EVENT_ECOLOGY_TIER_2` | Main Verte | 5 événements éco | `event.finished` | [07](07-evenement-event-finished.md) |
| [ ] | `EVENT_HYBRID_ECO_SOCIAL_TIER_1` | Éco-Solidaire | 5 éco et 5 socio | `event.finished` | [07](07-evenement-event-finished.md) |

## Navigation

| # | Document | Contenu |
| :--- | :--- | :--- |
| 01 | [État des lieux](01-etat-des-lieux.md) | Ce qui existe, ce qui manque. |
| 02 | [Architecture cible](02-architecture-cible.md) | Pipeline commun, moteur de règles de `pp-user`, idempotence, performance. |
| 03 | [`event.creation_successfull`](03-evenement-event-creation-successfull.md) | Badge `EVENT_HOST_COUNT_1`. |
| 04 | [`post.creation_successfull`](04-evenement-post-creation-successfull.md) | Badge `COMMUNITY_POST_COUNT_1`. |
| 05 | [`post.liked`](05-evenement-post-liked.md) | Badge `SOCIAL_LIKE_COUNT_10`. |
| 06 | [`event_social.wished`](06-evenement-event-social-wished.md) | Badge `EVENT_WISHLIST_COUNT_10`. |
| 07 | [`event.finished`](07-evenement-event-finished.md) | Les 9 badges de participation. |
| 08 | [`user.badge_awarded`](08-evenement-user-badge-awarded.md) | Push WebSocket et comportement de `nativapp`. |
| 09 | [Contrats et plan](09-contrats-et-plan.md) | Contrats à créer, règle du STOP, vagues, points ouverts. |
| 10 | [Guide technique `pp-user`](10-guide-technique-pp-user.md) | Faits vérifiés pour implémenter : token interne, client gRPC, pagination, écriture de badges, outbox, pièges. À lire avant de coder. |
