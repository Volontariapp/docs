# ADR : Convention de pagination

**Statut : accepté (2026-11-03).** Les faits sont référencés par fichier ; ce qui n'a pas pu être vérifié est listé en fin de document.

## Contexte

Les listes de l'API (événements, posts, utilisateurs, likes, abonnements, participants) étaient paginées de façon hétérogène : plafonds différents selon les services, ordres non déterministes (deux pages successives pouvaient se chevaucher), appels internes à `limit=1000` pour charger « tout », N appels unitaires pour hydrater une liste (comptage des participants, résumé des likes). Cette décision fixe une convention unique.

## Décision

### 1. Pagination par page et limite (offset), base 1

Le contrat est `page` (entier >= 1) et `limit` (entier >= 1). La gateway applique `DEFAULT_PAGE = 1` et `DEFAULT_LIMIT = 10`.[^gw-constants] Côté `BaseRepository`, `paginate` normalise la page (< 1 devient 1) et la limite (< 1 devient 10, au-delà du plafond elle est ramenée au plafond), et renvoie les valeurs normalisées.[^base-repo]

### 2. Ordre stable obligatoire, départage par identifiant

Toute requête paginée a un `ORDER BY` déterministe qui se termine par l'identifiant, sinon deux pages se chevauchent ou perdent des lignes :

- `BaseRepository.paginate` : sans `options.order`, tri sur les colonnes de clé primaire (ASC).[^base-repo]
- `domain-event` : `searchAdvanced` départage par id ; `domain-post` : `createdAt DESC` puis `id DESC` ; `domain-social` : chaque requête Cypher paginée a un `ORDER BY` déterministe.[^changelog]

Toute nouvelle requête paginée se termine donc par un départage sur l'identifiant.

### 3. Plafond de 100 côté gateway, par écrêtage et non par rejet

`MAX_LIMIT = 100`. Une `limit` supérieure est ramenée à 100 (`clampPaginationLimit`, `@PaginationLimit`) : la requête réussit, la réponse porte la limite effective. Une limite invalide (non entière ou < 1) reste un 400.[^gw-constants][^gw-decorators] Raison : un client qui envoie 500 reçoit des données plutôt qu'une erreur, ce qui ne casse aucun client existant.

Les DTO se construisent avec le module commun `src/common/pagination` de l'api-gateway (`createPaginationRequestDTO`, `createFlatPaginationQueryDTO`) : aucun DTO ne redéclare `page`, `limit` ou un plafond.[^gw-dto]

### 4. Exception legacy : 500 sur deux routes, à supprimer

`LEGACY_MAX_LIMIT = 500` pour `GET /api/v1/social/likes` et `GET /api/v1/users` (admin) uniquement, parce que les anciens builds de nativapp les appellent avec `limit=500`.[^gw-constants][^gw-legacy] Cette exception est temporaire : elle sera supprimée (retour au plafond de 100) une fois décidée la version minimale supportée de l'application. Aucune autre route ne reçoit d'exception.

### 5. Plafond côté microservice : 1000 aujourd'hui, cible 100

Les microservices valident et plafonnent aussi leur entrée (défense en profondeur, la gateway n'étant pas leur seul appelant). Aujourd'hui `MAX_PAGINATION_LIMIT = 1000` dans `ms-user`, `ms-event`, `ms-post` et `ms-social`, et `MAX_PAGE_LIMIT = 1000` dans `@volontariapp/database`, parce que des appels internes demandent encore `limit=1000`.[^ms-caps] La cible est 100, après la PR « G3 » qui remplace ces appels internes par des lectures par lot (section 6). Tant que cette PR n'est pas fusionnée, ne pas abaisser les plafonds des microservices.

### 6. Lectures par lot au lieu de boucles et de pages géantes

- `findByIds` : 100 identifiants au plus. `domain-event` ignore les doublons, les vides et les identifiants au-delà de `MAX_EVENT_IDS_PER_LOOKUP = 100` sans lever d'exception ; `domain-user` ignore les identifiants vides et plafonne à `MAX_USER_IDS_PER_LOOKUP = 100` sans exception ; `ms-user` valide `MAX_USERS_BY_IDS = 100`.[^batch]
- RPC par lot de `ms-social` : `CountEventParticipants` (au plus 100 `event_ids`, une entrée par identifiant demandé) et `GetPostsLikeSummary` (au plus 100 `post_ids`, `liked_by_me` relatif à l'appelant).[^proto]
- Route gateway `POST /api/v1/social/likes-summary` : 1 à 100 `postIds` uniques, réponse 200. Lecture exposée en POST pour éviter une URL de 100 identifiants.[^gw-likes]

### 7. Champ `pagination` sur les réponses, `total_count` déprécié

Chaque réponse de liste porte `pagination` (`total`, `page`, `limit`, `totalPages`). Les champs `total_count` des réponses d'événements (`SearchEventsResponse`, `GetUserCreatedEventsResponse`, `GetUserParticipatedEventsResponse`, `GetUserWishedEventsResponse`) sont dépréciés au profit de `pagination.total` et conservés pour la compatibilité du format fil (jamais supprimés sans le cycle de dépréciation du playbook `volontariapp-proto-contract-evolution`).[^proto-events]

### 8. Curseur seulement pour ms-ranking

Le classement personnalisé utilise un curseur opaque `(listVersion, lastRank)` encodé en base64url, parce que la liste est un instantané versionné dont les rangs changent (`DEFAULT_PAGE_LIMIT = 20`, `MAX_PAGE_LIMIT = 50` dans `domain-ranking`).[^cursor] Pour les posts et les abonnements, le choix entre offset et curseur reste une **décision ouverte** : l'offset reste la règle tant qu'elle n'est pas prise.

## Conséquences

- Une seule règle à appliquer et à relire : ordre stable, plafond 100, écrêtage, pagination en réponse.
- L'offset coûte à grande profondeur et tolère mal les insertions concurrentes ; accepté pour la taille actuelle des données et réévalué avec la décision sur le curseur.
- Deux dettes datées : l'exception legacy 500 (dépend de la version minimale de l'app) et le plafond 1000 des microservices (dépend de la PR G3).

## Sources vérifiées (origin/main au 2026-11-03)

[^gw-constants]: `api-gateway/src/common/pagination/pagination.constants.ts`
[^gw-decorators]: `api-gateway/src/common/pagination/pagination.decorators.ts` et `clamp-pagination-limit.helper.ts`
[^gw-dto]: `api-gateway/src/common/pagination/pagination.request.dto.ts` et `flat-pagination.request.dto.ts`
[^gw-legacy]: `api-gateway/src/modules/social/dto/request/get-my-likes.request.dto.ts` et `api-gateway/src/modules/user/dto/request/list-users.request.dto.ts`
[^gw-likes]: `api-gateway/src/modules/social/controllers/queries/interaction/interaction.query-controller.ts` et `api-gateway/src/modules/social/dto/request/get-posts-like-summary.request.dto.ts`
[^base-repo]: `npm-packages/packages/database/src/core/base.repository.ts`
[^changelog]: `npm-packages/packages/database/CHANGELOG.md`
[^ms-caps]: `ms-user/src/common/dto/pagination.dto.ts`, `ms-event/src/modules/event/dto/common/pagination.dto.ts`, `ms-post/src/modules/post/dto/common/pagination.dto.ts`, `ms-social/src/common/dto/pagination.dto.ts`
[^batch]: `npm-packages/packages/domain-event/src/constants.ts`, `npm-packages/packages/domain-user/src/constants.ts`, `ms-user/src/modules/user/dto/request/query/get-users-by-ids.query.dto.ts`
[^proto]: `proto-registry/proto/volontariapp/social/social.query.proto` et `social.responses.proto`
[^proto-events]: `proto-registry/proto/volontariapp/event/event.responses.proto`
[^cursor]: `npm-packages/packages/domain-ranking/src/helpers/cursor.helpers.ts` et `src/constants/pagination.constants.ts`
