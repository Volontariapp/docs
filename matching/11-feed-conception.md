# 11 - Feed de posts : conception

Prérequis : lire [02](02-architecture-cible.md) à [06](06-lecture-et-206.md). Le feed **réutilise la même mécanique** (écriture asynchrone, lecture synchrone, liste en PostgreSQL, 206 à froid, coalescence, Jev derrière un port). Ce document décrit ce qui change. Il intègre les corrections d'une revue indépendante ; les faits de départ sont en [10](10-feed-etat-des-lieux.md).

## 1. Objectif, honnêteté sur la promesse

Fournir `GET /ranking/feed` : les posts classés pour l'utilisateur selon **ce qu'il aime, commente et suit**.

Précision (revue) : l'ensemble de candidats est composé des comptes **suivis**, des comptes avec lesquels l'utilisateur **interagit** et des posts **liés à ses événements**. Aucun auteur inconnu n'y entre, hors complément de démarrage à froid. C'est donc un **feed d'abonnements re-classé par affinité**, pas un feed de découverte. Le nom « Pour toi » n'est pas justifié tant qu'une part d'exploration n'existe pas ([12](12-feed-plan-et-risques.md), question 3). Dans cette documentation : « feed d'affinité ».

| Dimension | Événements | Posts |
| :--- | :--- | :--- |
| Durée de vie utile d'un élément | jours à semaines | heures à jours |
| Volume | faible | élevé |
| Fraîcheur acceptable d'une liste | 24 h | 2 h |
| Signaux comportementaux | participations, souhaits | **likes, commentaires**, abonnements |
| Source du contenu | `ms-event` | `ms-post` |
| Démarrage à froid | tous les événements publiés sont candidats | un compte neuf ne suit personne : aucun candidat par le graphe |

## 2. Signaux : ce qui est lu où

Décision de simplification issue de la revue : **on ne tient un journal local que pour les likes** (le graphe n'a pas de dates). Les commentaires, eux, sont **lus directement dans `ms-post`** au moment du calcul, avec leur date, par une RPC dédiée. Cela supprime un deuxième registre, les problèmes de clé primaire (plusieurs commentaires d'un même utilisateur sur un post) et ceux d'ordre entre création et suppression de commentaire.

| Signal | Poids | Source | Date |
| :--- | :--- | :--- | :--- |
| Like | 1,0 | journal local `ranking_like_log`, **réconcilié avec le graphe** à chaque calcul | `createdAt` de l'enveloppe du flux ; repli `now() - 30 jours` pour un like découvert seulement dans le graphe |
| Commentaire | 2,0 | `ms-post.ListCommentsByAuthor(userId, since, limit)` à chaque calcul | `createdAt` du commentaire |
| Abonnement | relation, pas un signal daté | `AdminGetMyFollows` | n/a |
| Ami | bonus de relation | `AdminGetIsFollowing` dans les deux sens | n/a |
| Lien événement | bonus | `GetEventPosts` + historique d'événements | n/a |
| Blocage | exclusion | `AdminGetMyBlocks`, `AdminGetWhoBlockedMe` | n/a |

Les signaux sur **ses propres posts** sont ignorés.

### Le journal de likes n'est pas un verdict dérivé

Le principe posé pour les événements est que `ms-ranking` ne stocke que des verdicts recalculables. Le journal de likes est une **donnée comportementale primaire** (date d'un like), non entièrement recalculable (la date d'un like passé est perdue). C'est un écart assumé aux principes du README et de l'ADR-2, qui sont amendés. Conséquences traitées : suppression avec le compte (non couverte en V1, [03](03-modele-de-donnees.md) section 5), purge de rétention, chiffrement au repos à confirmer ([12](12-feed-plan-et-risques.md)).

## 3. Modèle de données (créé d'emblée avec la dimension `list_kind`)

Correction : au lieu d'une migration qui modifie la clé primaire, **`list_kind` est présent dès la première migration** ([03](03-modele-de-donnees.md) a été mis à jour). La colonne s'appelle `list_kind` (`'EVENT'` ou `'POST'`) pour ne pas être confondue avec les types de job ou de fan-out.

### `ranking_like_log`

| Colonne | Type | Rôle |
| :--- | :--- | :--- |
| `user_id` | `uuid` | celui qui like (lu dans `payload.authorId` ou `event.emitterId`) |
| `post_id_enc` | `text` | identifiant du post liké, **chiffré de façon déterministe** (`encryptDeterministic` de `@volontariapp/crypto`, clé `RANKING_LIKE_KEY`) ; pas de clé étrangère |
| `occurred_at` | `timestamptz` | `event.createdAt` de l'enveloppe |
| `deleted_at` | `timestamptz` NULL | pierre tombale posée par un unlike |
| `origin` | `varchar(10)` | `STREAM` ou `BACKFILL` |

PK `(user_id, post_id_enc)` ; index `(user_id, occurred_at DESC)`. `author_id` n'est **pas stocké** : le payload ne le contient pas ([10](10-feed-etat-des-lieux.md) section 4) ; l'auteur du post est résolu au calcul par `ListPostsByIds`.

**Chiffrement (décision du 2026-10-18).** Le lien utilisateur -> post est une donnée comportementale : l'identifiant du post est chiffré avec le paquet déjà utilisé pour les e-mails (`domain-user`). Le mode **déterministe** est volontaire : la clé primaire et les comparaisons d'égalité restent possibles, et le même post donne le même chiffré (compromis assumé : on peut voir que deux lignes visent le même post, pas lequel). `user_id` reste en clair (c'est l'identifiant de partition) ; `occurred_at` aussi. Les identifiants lus dans le graphe ou dans les flux sont chiffrés **en mémoire** avant écriture ou comparaison ; aucun identifiant de post en clair n'est écrit dans cette table. Clé distincte de celle de la position ([13](13-decisions-v1.md) section 3 bis).

Règles d'écriture, qui rendent l'**ordre des événements indifférent** (flux séparés pour like et unlike) :

- `POST_LIKED` : `INSERT ... ON CONFLICT (user_id, post_id_enc) DO UPDATE SET occurred_at = EXCLUDED.occurred_at, deleted_at = NULL WHERE ranking_like_log.deleted_at IS NULL OR ranking_like_log.deleted_at < EXCLUDED.occurred_at`.
- `POST_UNLIKED` : `INSERT ... (deleted_at = event.createdAt) ON CONFLICT (user_id, post_id_enc) DO UPDATE SET deleted_at = EXCLUDED.deleted_at WHERE ranking_like_log.occurred_at < EXCLUDED.deleted_at`.
- Un unlike arrivé avant son like crée une ligne avec pierre tombale ; le like plus ancien qui arrive ensuite ne la réactive pas (sa date est antérieure).

**Réconciliation avec le graphe, à chaque calcul** : `AdminGetUserLikes` (plafonné à `RANKING_FEED_LIKES_LIMIT` = 200, paginé par 50). Un like du journal absent du graphe reçoit une pierre tombale ; un like du graphe absent du journal est ajouté avec `origin = BACKFILL`. Cela corrige les événements perdus (unlike ou like non publié) et fait du **graphe la vérité pour l'existence** d'un like, le journal n'apportant que la **date**.

Rétention : lignes de plus de `RANKING_FEED_LOG_RETENTION_DAYS` (90) et pierres tombales de plus de 7 jours supprimées **dans la transaction d'écriture** de la liste de l'utilisateur (aucun planificateur n'existe : recherche de cron/repeat dans `workers-runners` et `database/src/outbox` : seulement `scheduled_at`). Pour les utilisateurs inactifs, un CronJob Kubernetes (`deploy`) lance une purge globale.

### `ranking_post_score`

Comme `ranking_score` : `user_id`, `post_id`, `score`, `structural_score`, `semantic_score` NULL, `rank` (`integer`), `reasons` (codes d'explication, 2 au plus), `computed_at`, plus `author_id` (utile à la diversité et au diagnostic) et `origin` (`FOLLOWED`, `ENGAGED`, `EVENT`, `GLOBAL`). PK `(user_id, post_id)` ; index `(user_id, rank)`. Taille `RANKING_FEED_LIST_SIZE` (100).

### `ranking_run` et `ranking_request`

Clé `(user_id, list_kind)`. `source` accepte `FULL`, `STRUCTURAL_ONLY` et `COLD_START` ; l'enum proto `RankingSource` reçoit la valeur `RANKING_SOURCE_COLD_START`. `formula_version` est comparée à la constante du `list_kind` concerné (`FORMULA_VERSION` pour les événements, `FEED_FORMULA_VERSION` pour les posts).

## 4. Génération des candidats

Les posts ne sont ni dans le graphe (seulement leur identifiant) ni dans `ms-ranking` : ils viennent de **`ms-post`, source de vérité**.

### Ensemble d'auteurs (plafond `RANKING_FEED_AUTHORS`, 200)

Ordre de priorité corrigé (les comptes suivis sont renvoyés dans un ordre arbitraire et évinceraient les auteurs engagés) :

1. auteurs avec lesquels l'utilisateur a des signaux (likes du journal et commentaires), par pondération décroissante ;
2. comptes suivis (`AdminGetMyFollows`, paginé par 50 jusqu'au plafond).

Les posts **liés à un événement** de l'utilisateur ne passent pas par les auteurs : leurs identifiants (`GetEventPosts`) sont chargés **directement** par `ListPostsByIds`, avec leur propre fenêtre d'âge (`RANKING_FEED_EVENT_POST_MAX_AGE_DAYS` = 30).

### RPC `ms-post` à créer (additifs, un seul passage par le STOP `proto-registry`)

```protobuf
message ListRecentPostsByAuthorsQuery {
  repeated string author_ids = 1;              // plafonne a 200 cote serveur
  bool all_authors = 2;                        // vrai : ignore author_ids (complement / demarrage a froid)
  google.protobuf.Timestamp since = 3;
  int32 per_author_limit = 4;                  // par ex. 5 : evite qu'un auteur prolifique affame les autres
  int32 limit = 5;                             // plafonne a 300
}
message ListPostsByIdsQuery  { repeated string ids = 1; }            // plafonne a 100, ids absents ignores, ordre non garanti
message ListCommentsByAuthorQuery {
  string author_id = 1;
  google.protobuf.Timestamp since = 2;
  int32 limit = 3;                             // plafonne a 200
}
rpc ListRecentPostsByAuthors(ListRecentPostsByAuthorsQuery) returns (ListPostsResponse);
rpc ListPostsByIds(ListPostsByIdsQuery) returns (ListPostsResponse);
rpc ListCommentsByAuthor(ListCommentsByAuthorQuery) returns (ListCommentsResponse);
```

Contraintes d'implémentation (`ms-post`) :

- tri `"createdAt" DESC, id DESC` ; plafond par auteur par `ROW_NUMBER() OVER (PARTITION BY "authorId" ORDER BY "createdAt" DESC)` appliqué **avant** le plafond global ;
- noms de colonnes réels : `"authorId"` et `"createdAt"` (camelCase, `TIMESTAMP` sans fuseau, attention aux comparaisons de dates) ;
- migration à ajouter dans `ms-post/src/migrations/domain/` : `CREATE INDEX ... ON posts ("authorId", "createdAt" DESC)` (aucun index n'existe aujourd'hui), resynchronisée par `sync-migrations.sh` ; l'index d'auteur des commentaires existe déjà ;
- `eventId` n'étant pas une colonne, les RPC le résolvent via `ms-social` **si un jeton est transmis**, comme `ListPosts` : le worker transmet son jeton interne ;
- aucune de ces RPC ne doit lever d'erreur pour un identifiant absent (contrairement à `GetPost`).

### Filtres appliqués par le worker

- exclure les posts de l'utilisateur ;
- exclure les auteurs bloqués ou qui ont bloqué l'utilisateur ;
- exclure les posts plus anciens que `RANKING_FEED_MAX_AGE_DAYS` (7), sauf posts liés à un événement ;
- **médias** : n'inclure que `NONE` et `READY` ; exclure `PENDING` et `REJECTED`. `ms-post` renseigne désormais `mediaStatus` (corrigé le 2026-10-18, [10](10-feed-etat-des-lieux.md) section 3).

### Démarrage à froid et complément

Corrections : `ListPosts` n'a pas de tri et ne convient pas. Le complément utilise `ListRecentPostsByAuthors(all_authors = true)` trié par date.

- Si le nombre de candidats après filtres est inférieur à `RANKING_FEED_MIN_ITEMS` (20), compléter avec les posts récents de la plateforme, marqués `origin = GLOBAL`, **placés après** les posts d'origine personnelle.
- Si aucun candidat personnel n'existe, la liste est marquée `source = COLD_START`.
- **Modération** : `ms-post` n'a ni modération ni signalement. Décision du 2026-10-18 : le complément `GLOBAL` est conservé comme repli, placé après les posts personnels, derrière un indicateur de configuration activé par défaut. Le risque de contenu non modéré est jugé faible (utilisateurs fictifs, aucun client) ; à réexaminer avant un lancement public ([12](12-feed-plan-et-risques.md)).

## 5. Score

### Composantes (0 à 1)

| Composante | Définition | Poids |
| :--- | :--- | :--- |
| `authorAffinity` | `min(1, base + bonus)` où `base = min(1, Σ poidsSignal × décroissance(âge) / K)` avec `K = 6`, et `bonus = 0,25` si l'auteur est suivi, `+0,15` si ami | 0,35 |
| `eventTie` | 1 si le post est lié à un événement que l'utilisateur participe, souhaite ou a créé | 0,15 |
| `recency` | `exp(-âgeEnHeures / 48)` (demi-vie d'environ 33 h) | 0,35 |
| `popularity` | non calculée en V1 (aucun compteur de likes ; `GetPostLikers` serait N appels) | 0,00 |
| `semantic` (Jev) | probabilité renvoyée, **désactivée par défaut** | 0,15 |

`décroissance(âge) = 0,5 ^ (âge en jours / 14)`. Correction : `K = 6` (et non 3) pour ne pas saturer dès un commentaire et un like récents ; sinon plus aucune discrimination entre auteurs.

### Normalisation

`structural_score = Σ(poids actifs × composante) / Σ(poids actifs)`, **toujours borné à [0, 1]**. Sans Jev, les poids actifs sont `0,35 + 0,15 + 0,35` (somme 0,85) ; avec la popularité activée un jour, la somme change. Le code normalise donc par la somme des poids actifs et applique un `clamp`, sinon la contrainte `CHECK (score BETWEEN 0 AND 1)` ([03](03-modele-de-donnees.md)) ferait échouer toute la transaction.

Score final : `0,85 × structurel_normalisé + 0,15 × sémantique` si Jev est actif pour le candidat, sinon `structurel_normalisé`. Les candidats non évalués par Jev sont plafonnés sous le minimum des évalués (règle de [05](05-scoring-et-jev.md) section 5).

### Posts déjà likés ou commentés

Le journal les connaît : leur score est multiplié par `0,6` (rétrogradation, pas exclusion), facteur unique sans cumul si le post est à la fois liké et commenté. Décidé le 2026-10-18 ([13](13-decisions-v1.md)).

### Diversité

Sélection gloutonne sur la liste triée : un post est reporté si les 3 posts précédents retenus ont le même auteur ; si un seul auteur subsiste, aucune troncature (la liste n'est pas vidée pour respecter la règle).

### Jev pour le feed

Désactivé par défaut (indicateur de configuration `RANKING_FEED_JEV_ENABLED = false`). Raison : l'état envoyé décrirait **ce que cet utilisateur aime et commente** (textes de ses 15 derniers posts likés ou commentés). Même sans identifiant, c'est un profil comportemental envoyé à un tiers dont la politique de conservation n'est pas documentée. Si activé : même appel qu'en [05](05-scoring-et-jev.md) (une requête, N questions `noul`, clé = `postId`, 30 meilleurs candidats, textes tronqués à 200 caractères, texte des posts lus par `ListPostsByIds`).

## 6. Déclencheurs

Décision issue de la revue (stabilité du feed) : **un like ou un commentaire ne déclenche pas de recalcul par défaut.** Recalculer à chaque interaction, puis notifier le client, ferait se reclasser le feed pendant que l'utilisateur le lit. Les signaux sont pris en compte au prochain calcul déclenché par une autre cause. Un indicateur `RANKING_FEED_RECOMPUTE_ON_SIGNAL` (désactivé) permet l'inverse, avec un délai de coalescence de 5 minutes.

| Déclencheur | Flux | Action | File | `reason` |
| :--- | :--- | :--- | :--- | :--- |
| Nouveau post | `POST_CREATED` | fan-out vers les abonnés actifs (section 7) | feed | `POST_PUBLISHED` |
| Like / unlike | `POST_LIKED`, `POST_UNLIKED` | écriture du journal seulement | n/a | n/a |
| Commentaire | `COMMENT_CREATED/DELETED` | **aucun consommateur** (commentaires lus dans `ms-post`) | n/a | n/a |
| Nouveau compte | `social:user` (type `user.created`) | demandes `EVENT` **et** `POST`, écrites dans la même transaction | feed / fond | `USER_CREATED` |
| Lecture sans liste | `GetRankingPosts` | demande `ON_DEMAND` | fallback | `ON_DEMAND` |
| Liste périmée (> `RANKING_FEED_STALE_AFTER_HOURS`, 2 h) | `GetRankingPosts` | demande `STALE_REFRESH` | feed | `STALE_REFRESH` |
| Demande manuelle | `RequestRankingRefresh(list_kind)` | demande | fallback | `MANUAL` |
| Follow, unfollow, block | aucun flux (V2) | rafraîchissement périodique | n/a | n/a |
| Suppression d'un post | `POST_DELETED` | aucune : l'identifiant disparaît à la lecture | n/a | n/a |

Corrections de cohérence : `RANKING_STALE_AFTER_HOURS` (24, événements) et `RANKING_FEED_STALE_AFTER_HOURS` (2, posts) sont deux paramètres distincts. Un compte qui vient de suivre quelqu'un **n'est pas** sorti du démarrage à froid avant le prochain rafraîchissement (aucun flux de follow en V1).

## 7. Jobs, files, fan-out

```typescript
export enum RankingJobType {
  COMPUTE_USER_RANKING = 'ranking.compute_user_ranking',   // evenements
  COMPUTE_USER_FEED     = 'ranking.compute_user_feed',       // posts
  FANOUT_RANKING       = 'ranking.fanout',
}

export interface IComputeUserFeedPayload {
  userId: string;
  reason: 'USER_CREATED' | 'POST_PUBLISHED' | 'ON_DEMAND' | 'STALE_REFRESH' | 'MANUAL';
  requestedAt: string; // horloge de la base ms-ranking (voir 04, section 6)
}

export interface IFanoutRankingPayload {
  trigger: 'EVENT_CREATED' | 'EVENT_FINISHED' | 'POST_CREATED';
  eventId?: string;   // pour les declencheurs d'evenement
  postId?: string;    // pour POST_CREATED
  authorId?: string;  // pour POST_CREATED
  requestedAt: string;
}
```

Files : `ranking-feed-queue` (nouvelle, `RankingQueue.FEED`) pour les recalculs de posts, afin qu'un afflux de publications ne retarde pas les calculs d'événements ; `fallback-ranking-queue` pour `ON_DEMAND` et `MANUAL` des deux types. Le second type de job nécessite un **second mapping de notification WebSocket** ([04](04-flux-asynchrone.md) section 9), idéalement dans un enum dédié `ranking` plutôt que dans `EventEventMessagingType` (nom trompeur pour un feed de posts, à confirmer selon ce que `JOB_TO_EVENT_MAPPING` accepte).

### Fan-out de `POST_CREATED` (corrigé)

`AdminGetMyFollowers` n'a ni tri, ni plafond, défaut 10 : un plafond de 200 sur la page 1 prendrait toujours le même sous-ensemble arbitraire, et la pagination non triée peut doubler ou sauter des éléments pendant un changement du graphe. Procédure :

1. paginer les abonnés par 50 jusqu'à épuisement ou plafond `RANKING_FEED_MAX_FANOUT` (200) ;
2. **intersecter avec les utilisateurs actifs** de `ranking_run` (`list_kind = 'POST'`, fenêtre `RANKING_ACTIVE_DAYS`), ce qui évite des calculs pour des abonnés dormants ;
3. dédupliquer ;
4. écrire une demande de calcul par utilisateur restant, dans une seule transaction ; `emitterId` du job de fan-out = `postId`.

## 8. Lecture

```text
GET /ranking/feed?page=1&limit=20     200 | 206
```

1. `ms-ranking.GetRankingPosts` : lecture indexée de `ranking_post_score` (200) ou demande `ON_DEMAND` + `FALLBACK_ACTIVATED('ranking.compute_user_feed', ...)` (206). Le type de job dans l'erreur dépend de `list_kind` (corrigé : il était écrit en dur pour les événements).
2. La gateway charge le contenu via `ms-post.ListPostsByIds` (plafond de 100 identifiants, sans pagination ; la « pagination explicite » héritée des événements est sans objet ici), réordonne selon l'ordre reçu et écarte les posts absents.
3. **Blocages appliqués à la lecture** : la gateway obtient les deux ensembles de blocage de l'utilisateur (`GetMyBlocks`, `GetWhoBlockedMe`, RPC utilisateur existantes) et retire les posts des auteurs concernés. Sans cela, un harceleur bloqué reste visible jusqu'au prochain recalcul (jusqu'à environ 2 h). Si cette étape est jugée trop coûteuse, le risque est à déclarer Haute.
4. Pas d'enrichissement existant à reproduire : le DTO de liste de posts n'en a aucun ([10](10-feed-etat-des-lieux.md) section 3). Les médias ne sont pas transportés non plus par ce DTO.
5. Plafonner `limit` côté gateway (aucun maximum côté services).
6. Réponse : `ranking: { source, computedAt, stale, hasMore, listVersion }` et `rankingScore` par post.

### Stabilité de la liste pendant la lecture

La liste est **remplacée en bloc** à chaque calcul. Une pagination par `rank` sur une liste qui change entre deux pages peut dupliquer ou sauter des éléments. Mesures : la réponse porte `listVersion` (= `computedAt`) ; le client le renvoie en demandant la page suivante ; si la version a changé, le serveur renvoie `versionChanged = true` et le client recharge depuis la page 1 (ou affiche un bandeau « nouveaux posts »). **Le client ne rafraîchit pas automatiquement** une liste en cours de lecture à réception de la notification : il affiche un bandeau et recharge à la demande ou au retour sur l'écran.

## 9. Fraîcheur et évolution

Un post publié à l'instant n'apparaît qu'après un recalcul (délai de coalescence de 30 s + durée du calcul). Évolution si nécessaire : fusion à la lecture des posts récents des abonnements. Elle exige que le chemin de lecture appelle `ms-post`, ce qui rompt la propriété « `ms-ranking` n'appelle aucun service en lecture » ; à ne retenir qu'après mesure.

## 10. Relation avec le feed existant

Le feed existant (`GET /api/v1/social/feed/me`) n'est utilisé par **aucun écran**. Le nouveau feed serait donc le premier feed visible. Proposition : ne pas toucher à l'existant dans ce chantier, et signaler son défaut (aucun `ORDER BY`) séparément.

## 11. Déploiement à chaud

À la mise en production, aucun utilisateur existant n'a de liste `POST` : chaque premier appel produit un 206 et un calcul à la demande, soit une rafale. Parades : concurrence du worker bornée, file `fallback` dédiée, et un indicateur de déploiement progressif (`RANKING_FEED_ENABLED`, activable par cohorte ou globalement) pour échelonner l'ouverture. **Mise à jour du 2026-10-18** : l'indicateur de déploiement progressif est supprimé (aucun client, pas de staging, [13](13-decisions-v1.md) décision 17) ; seules la concurrence bornée et la file de repli dédiée restent utiles.

## 12. Ce qui est volontairement écarté

| Idée | Raison |
| :--- | :--- |
| `createdAt` sur les nœuds `SocialPost` de Neo4j | modification de `domain-social` (STOP) et duplication d'une métadonnée de `ms-post` |
| Index local des posts dans `ms-ranking` | duplique la métadonnée ; les RPC `ms-post` donnent le même résultat |
| Registre local des commentaires | remplacé par `ListCommentsByAuthor` (daté, exact, sans problème d'ordre) |
| Recalcul à chaque like ou commentaire | feed instable pendant la lecture ; coût ; indicateur désactivé |
| Apprentissage d'un modèle de ranking | hors de portée à ce volume |
| Popularité (compteur de likes) | aucun compteur ; N appels Neo4j |
