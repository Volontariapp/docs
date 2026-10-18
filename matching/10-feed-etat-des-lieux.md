# 10 - Feed de posts : état des lieux

Extension de `ms-ranking` : en plus des événements, le service classe **les posts** pour produire un feed fondé sur ce que l'utilisateur aime, commente et suit. Ce document établit ce qui existe ; la conception est en [11](11-feed-conception.md), le plan en [12](12-feed-plan-et-risques.md).

Faits vérifiés le 2026-10-11 par lecture directe du code et par une revue indépendante, puis mis à jour le 2026-10-18 (médias de `ms-post`, usage du feed existant). Chemins relatifs à la racine `meta`. Les corrections issues de la revue sont signalées par « Corrigé ».

## 1. Le feed qui existe déjà

| Élément | Réalité | Source |
| :--- | :--- | :--- |
| RPC | `PublicationQueryService.GetFeed` et `AdminGetFeed` | `proto-registry/proto/volontariapp/social/social.services.proto:54-56` |
| Requête | `MATCH (me)-[:FOLLOW]->(followed)-[:OWN]->(p:SocialPost) RETURN DISTINCT p.postId SKIP $skip LIMIT $limit` | `npm-packages/packages/domain-social/src/repositories/neo4j-publication.repository.ts:186-197` |
| Tri | **Aucun `ORDER BY`** : ordre arbitraire, pagination `SKIP/LIMIT` instable | même fichier |
| Contenu renvoyé | des **identifiants de posts uniquement** | même fichier |
| Route gateway | `GET /api/v1/social/feed/me` (`@Controller('social')`, préfixe global `api/v1`) | `api-gateway/src/modules/social/controllers/queries/publication/publication.query-controller.ts:11-12, 23-31` ; `api-gateway/src/main.ts:66` |
| Consommation côté application | **Aucune.** `GET_FEED_SELF` est déclaré mais jamais utilisé (et mal typé) ; les posts s'affichent via `GET /posts?authorId=` | `nativapp/src/api/endpoints/social.endpoints.ts:318-323` ; `nativapp/src/api/post/post.api.ts:67-88` |

Corrigé : le feed existant n'est consommé par **aucun écran**. L'idée de « deux onglets, dont l'existant » supposait une interface qui n'existe pas ; le nouveau feed serait le premier feed de l'application.

## 2. Ce que le graphe sait des posts (`ms-social`, Neo4j)

| Relation / nœud | Définition | Source |
| :--- | :--- | :--- |
| `(:SocialPost {postId})` | **un seul champ : l'identifiant** | `neo4j-publication.repository.ts:24-29` |
| `(:SocialUser)-[:OWN]->(:SocialPost)` | auteur du post | même fichier, lignes 69-78 |
| `(:SocialUser)-[:LIKE]->(:SocialPost)` | like d'un utilisateur | `neo4j-interaction.repository.ts:25-33` |
| `(:SocialPost)-[:LINK_TO_EVENT]->(:SocialEvent)` | post rattaché à un événement | `neo4j-event-post-link.repository.ts` (lecture partielle, lignes 80-94) |
| `(:SocialUser)-[:FOLLOW]->(:SocialUser)` et `[:BLOCK]` | abonnements et blocages | `neo4j-relationship.repository.ts` |

Limites : **aucune relation n'a d'horodatage** ; **aucune relation de commentaire n'existe** (recherche de « comment » dans `domain-social/src` et `ms-social/src` : aucun résultat) ; pas de requête « propriétaire de ce post ».

## 3. Ce que sait `ms-post` (PostgreSQL)

| Élément | Réalité | Source |
| :--- | :--- | :--- |
| Entité | `PostEntity` : `id`, `authorId`, `title`, `content`, `createdAt`, `updatedAt`, `saga_status` | `npm-packages/packages/domain-post/src/entities/post.entity.ts` |
| `eventId` | **N'est pas une colonne.** `ms-post` l'obtient de `ms-social` à chaque lecture, seulement si un jeton est transmis | `ms-post/.../post.query.controller.ts:36-41, 60-68` ; `post.model.ts` (pas de colonne) |
| Médias | Corrigé le 2026-10-18 : `toPostDTO` renseigne `media` (`fileId`, `position`) et `mediaStatus` (`NONE`, `PENDING`, `READY`, `REJECTED`, repli `NONE`). La création gère `fileIds` et les statuts de scan | `ms-post/src/modules/post/transformers/post.transformer.ts:41-69` ; `npm-packages/packages/domain-post/src/repositories/postgres-post.repository.ts:149-205` |
| Colonnes SQL | `"authorId"` et `"createdAt"` (camelCase), `TIMESTAMP` sans fuseau. **Aucun index** sur `authorId` ni `createdAt` (seul `saga_status` est indexé) | `ms-post/src/migrations/domain/1776000000000-InitialPostSchema.ts:9` ; `post.model.ts` |
| RPC de lecture de posts | `GetPost(id)`, `ListPosts(pagination, optional author_id)` | `post.services.proto:14-25` |
| Tri de `ListPosts` | **Aucun** : `paginate({page, limit}, {where})` sans `order` ; défaut page 1, limit 10, **aucun plafond** | `postgres-post.repository.ts:59-66` ; `database/src/core/base.repository.ts:227-251` ; `ms-post/.../post.query.controller.ts:55-56` |
| Commentaires | `ListComments(post_id, pagination)` : tri `createdAt DESC`, défaut 10. **Index sur `authorId` présent côté commentaires** | `postgres-comment.repository.ts:33-45` ; `ms-post/src/migrations/domain/1780000000000-InitialCommentSchema.ts:11` |
| Visibilité d'un post | **Public** : aucun champ ni filtre de visibilité | `post.model.ts`, `post.entity.ts`, `ListPosts` |
| Compteur de likes | **Inexistant** : seul `GetPostLikers` (liste paginée) existe | `social.services.proto:68` |
| Absent | recherche par liste d'identifiants, par liste d'auteurs, filtre de date, lecture des commentaires par auteur, modération, signalement | `post.query.proto`, recherche « moderat\|report » : aucun résultat |
| Enrichissement gateway | **Aucun** : le DTO de liste contient `id`, titre, contenu, `authorId`, dates, événement ; ni profil d'auteur, ni compteurs, ni médias | `api-gateway/src/modules/post/dto/response/list-posts.response.dto.ts:18-31` |

Corrigé le 2026-10-18 : la visibilité des médias est désormais implémentée dans `ms-post`. Un filtre `NONE`/`READY` n'exclut plus tous les posts ; `PENDING` et `REJECTED` restent à exclure.

## 4. Signaux asynchrones : sémantique réelle des payloads

Corrigé (point bloquant de la revue, vérifié dans le code) : la première version de ce document inversait le sens des champs.

| Flux | Producteur | Payload réel | Acteur | Source |
| :--- | :--- | :--- | :--- | :--- |
| `Streams.POST_LIKED` | `domain-social/src/services/interaction.service.ts:51-60` | `{ postId, authorId }` | **`authorId` = l'utilisateur qui like** ; `userId` jamais renseigné ; **l'auteur du post est absent** ; `emitterId` = le liker | idem lignes 51-54 |
| `Streams.POST_UNLIKED` | `interaction.service.ts:95-104` | `{ postId, authorId }` | `authorId` = l'utilisateur qui retire son like | idem |
| `Streams.COMMENT_CREATED` | `domain-post/.../postgres-comment.repository.ts:54-66` | `{ commentId, postId, authorId }` | **`authorId` = l'auteur du commentaire** ; `userId` jamais renseigné ; l'auteur du post est absent | idem lignes 54-58 |
| `Streams.COMMENT_DELETED` | `postgres-comment.repository.ts:87-100` | `{ commentId, postId }` | aucun dans le payload ; l'acteur est `emitterId` (auteur du commentaire) | idem |
| `Streams.POST_CREATED` | `domain-post/.../postgres-post.repository.ts:81-96` | `{ postId, userId, eventId?, fileIds }` | `userId` = auteur ; `fileIds` toujours `[]` | idem |
| `Streams.POST_DELETED` | `postgres-post.repository.ts:116-126` | `{ postId }` | `userId` jamais renseigné ; acteur = `emitterId`. **`deleteByAuthorId` ne publie aucun `POST_DELETED`** | `post.service.ts:158` |

Enveloppe commune (`npm-packages/packages/messaging/src/events/utils.ts:5-21`) : `id`, `emitterId`, `createdAt`, `correlationId`, `payload.after`. **L'acteur et la date de l'événement se lisent dans l'enveloppe** (`emitterId`, `createdAt`), pas dans le payload. `post-processor-social/.../post-created.post-processor.ts:50-60` lit déjà `event.emitterId`.

Flux distincts par type : `post-liked` et `post-unliked`, `comment-created` et `comment-deleted` sont **des flux séparés** (`shared/src/enums/streams.enum.ts:23-29`) : l'ordre relatif d'un like et de son annulation n'est pas garanti.

Fiabilité : l'émission d'un like est faite après l'écriture Neo4j, hors transaction, et l'échec est avalé par un `logger.warn` (`interaction.service.ts:69-73`). Un événement peut être perdu : un unlike perdu laisse un fantôme dans un journal alimenté par les flux.

## 5. Appels de service à service déjà possibles

| Besoin | RPC existante | Remarque |
| :--- | :--- | :--- |
| Comptes que je suis | `AdminGetMyFollows` | `social.services.proto:34-37` ; **sans tri, défaut 10, aucun plafond, aucun garde de rôle** (`neo4j-relationship.repository.ts:76-126`) |
| Comptes qui me suivent (fan-out) | `AdminGetMyFollowers` | idem, `relationship.query.controller.ts:102-111` |
| Blocages dans les deux sens | `AdminGetMyBlocks`, `AdminGetWhoBlockedMe` ; RPC utilisateur `GetMyBlocks`, `GetWhoBlockedMe` | idem |
| Mes likes (identifiants seulement) | `AdminGetUserLikes` | `social.services.proto:69` ; `neo4j-interaction.repository.ts` |
| Posts liés à un événement (identifiants seulement) | `EventPostLinkQueryService.GetEventPosts` | `social.services.proto:107` ; `neo4j-event-post-link.repository.ts:80-94` |
| Ami (suivi mutuel) | `AdminGetIsFollowing` | `social.services.proto:39` |
| Contenu d'un post | `PostService.GetPost` | un appel par post (N+1) ; **lève une erreur si le post n'existe pas** (`post.service.ts:18-31`) |

## 6. Ce qui manque pour un feed classé

1. Lecture des **posts récents d'un ensemble d'auteurs**, avec contenu, tri et plafond par auteur (RPC `ms-post`).
2. Lecture de **posts par identifiants**, tolérante aux identifiants absents (RPC `ms-post`).
3. Lecture des **commentaires d'un utilisateur**, datés (RPC `ms-post`, index d'auteur déjà présent).
4. Une trace **datée des likes** (le graphe n'a pas de dates).
5. Un **index** `("authorId", "createdAt" DESC)` sur la table des posts.
6. (Fait depuis le 2026-10-11) Le câblage des **médias** (`mediaStatus`) est en place dans `ms-post` ; le filtre de visibilité du feed peut être strict.
7. Une stratégie de **démarrage à froid** (un compte neuf ne suit personne) et de **découverte** (rien dans ce design ne remonte un auteur totalement inconnu).
8. Un moyen d'**appliquer les blocages à la lecture** (ils ne sont aujourd'hui appliqués qu'au calcul).
