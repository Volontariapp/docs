# ms-post : réduire le CPU par requête (service et base `ms-post-db`)

Analyse du 2026-11-09, sans modification d'aucun dépôt et sans requête sur une base de production. Code lu sur `origin/main` (ms-post exporté par `git archive origin/main`, npm-packages par `git show origin/main:...`).

**Avertissement.** Aucun profil CPU de `ms-post` n'existe. Les gains annoncés sont des **INFERENCES** tirées de la lecture du code, plus une **mesure locale sur données synthétiques** (Postgres 16 sur un Mac M2, 29 000 posts, 30 médias, TypeORM 0.3.30 de `ms-post/node_modules` ; la prod a 0.3.31). Cette mesure locale est un FAIT pour ce banc, pas pour la prod. La section 6 donne les étapes de mesure qui confirment ou infirment chaque gain.

Conventions : **FAIT** = ligne lue ou sortie d'outil de cette session, avec `fichier:ligne` ; **INFERENCE** = déduction non vérifiée ; **NON VERIFIE** = point à mesurer en prod.

---

## 1. Le chemin `posts-list` de bout en bout

### 1.1 Qui appelle quoi (FAIT)

- Le mélange de charge envoie `GET /posts?page={1..3}&limit=20`, sans `authorId`, avec le jeton d'un acteur tiré au hasard parmi 200 (`traffic-simulator` `src/load/load-request.ts:44-45`, `src/load/load-runner.ts:62`).
- Gateway : `api-gateway` `src/modules/post/controllers/queries/post/post.query-controller.ts:76-95` appelle `listPosts`, puis `eventLookup.getByIds` (cache de 30 s à la gateway). Ligne 80 : un `info` avec `JSON.stringify(request)` à chaque requête (coût gateway, hors périmètre).
- `ms-post` `src/modules/post/controllers/post.query.controller.ts:69-111` (`listPosts`) :
  1. ligne 75 : un `info` "gRPC: Listing posts..." ;
  2. lignes 80-90 : cache du total, clé `PostsTotalCache.buildKey(authorId, user?.id)` ;
  3. ligne 85/86 : `postService.listPosts` puis `PostgresPostRepository.listPaginated` ;
  4. lignes 92-100 : appel gRPC **sortant** vers `ms-social` `GetEventsRelatedToPosts` à chaque requête qui a un jeton et au moins un post (`clients/social-event-post.query-client.ts:61-86`) ;
  5. lignes 102-110 : transformation en DTO (`transformers/post.transformer.ts:41-80`).
- `analyze_grpc PostService` (toutes les racines indexées) : un seul client de `ListPosts`, la gateway (`post.query-controller.ts:75` dans l'index local). `analyze_grpc GetEventsRelatedToPosts` : aucun appel littéral résolu, deux clients de service construits (`ms-post` `social-event-post.query-client.ts:34` et `workers-runners/worker-ranking/src/clients/social-feed.client.ts:39`) ; l'appel de `ms-post` est lu ligne 74 du client. Remarque : `mesh-mcp` indexe les copies de travail locales, pas `origin/main` ; les numéros de ligne de ce rapport viennent de `origin/main`.

### 1.2 Le SQL réellement émis (FAIT sur le banc local)

TypeORM a été exécuté sur le même constructeur de requête que `listPaginated` (`npm-packages` `packages/domain-post/src/repositories/postgres-post.repository.ts:150-173`), avec un journal de requêtes. Pour un lecteur connecté, sans `authorId`, page 3 :

**Requête 1, sélection des identifiants (DISTINCT)**

```sql
SELECT DISTINCT "distinctAlias"."post_id" AS "ids_post_id", "distinctAlias"."post_createdAt", "distinctAlias"."post_id"
FROM (SELECT "post"."id" AS "post_id", "post"."authorId" AS "post_authorId", "post"."title" AS "post_title",
             "post"."content" AS "post_content", "post"."createdAt" AS "post_createdAt", "post"."updatedAt" AS "post_updatedAt",
             "post"."saga_status" AS "post_saga_status", "post"."media_status" AS "post_media_status",
             "media"."id" AS "media_id", "media"."post_id" AS "media_post_id", "media"."file_id" AS "media_file_id",
             "media"."position" AS "media_position", "media"."scan_status" AS "media_scan_status"
      FROM "posts" "post" LEFT JOIN "post_media" "media" ON "media"."post_id"="post"."id"
      WHERE ("post"."authorId" = $1 OR "post"."media_status" IN ($2, $3))) "distinctAlias"
ORDER BY "distinctAlias"."post_createdAt" DESC, "distinctAlias"."post_id" DESC, "post_id" ASC
LIMIT 20 OFFSET 40
```

**Requête 2, chargement des lignes** : même SELECT avec jointure, `AND "post"."id" IN ($4 ... $23)`, `ORDER BY createdAt DESC, id DESC`.

**Requête 3, total (seulement sur un défaut de cache)** :

```sql
SELECT COUNT(*) AS "total" FROM "posts" "post" WHERE ("post"."authorId" = $1 OR "post"."media_status" IN ($2, $3))
```

Pourquoi deux requêtes de page : `skip`/`take` combinés à une jointure déclenchent le mode « deux requêtes » de TypeORM (FAIT : `ms-post/node_modules/typeorm/query-builder/SelectQueryBuilder.js:1961` et suivantes, condition `(skip || take) && joinAttributes.length > 0`, deux `clone()` de la requête, une requête DISTINCT puis une requête `IN (...)`).

### 1.3 Ce que coûte chaque requête côté base (FAIT sur le banc, `EXPLAIN (ANALYZE, BUFFERS)`)

| Requête | Plan | Exécution | Planification |
| :--- | :--- | ---: | ---: |
| 1, DISTINCT | `Index Scan` de `IDX_posts_created_at`, boucle imbriquée vers `idx_post_media_post`, `Incremental Sort`, `Unique`, `Limit` | 0,10 ms | 0,09 ms (0,77 ms à froid) |
| 3, COUNT avec lecteur | **`Seq Scan` des 29 000 lignes**, 1 160 blocs | **5,6 ms** | 0,03 ms |
| Page sans jointure (alternative) | `Index Scan` + `Incremental Sort` | 0,03 ms | 0,05 ms |
| Page avec sous-requête `json_agg` des médias (alternative) | idem + sous-plan par ligne | 0,16 ms | 0,07 ms |
| Posts cachés du lecteur (alternative au total) | `Bitmap Index Scan` de `IDX_posts_author_created_at` | 0,03 ms | 0,02 ms |

Lecture :

- **La page n'est pas le problème côté base** : le plan DISTINCT est bon grâce à `IDX_posts_created_at` (`ms-post` `src/migrations/domain/1792200000000-AddCommentsAndPostsFeedIndexes.ts:23`) et à l'`Incremental Sort` de Postgres 16. Cela concorde avec le « 0,2 ms » mesuré en prod pour la page.
- **Le COUNT est 50 fois plus cher que la page**. Le `OR "authorId" = :readerId` et un `media_status` présent sur presque toutes les lignes interdisent tout index : chaque défaut de cache relit la table entière. INFERENCE : sur l'hôte de prod (2,8 à 3,4 GHz, sous limite thermique), compter 6 à 10 ms.
- Index déclarés dans les migrations (FAIT, NON VERIFIE contre la prod) : `PK_posts_id`, `UQ_posts_title`, `IDX_posts_saga_status`, `IDX_posts_media_status` (`1781000000000-AddPostMediaAndMediaStatus.ts:10`), `IDX_posts_author_created_at ("authorId", "createdAt" DESC)` (`1792100000000-AddPostsAuthorCreatedAtIndex.ts:12`), `IDX_posts_created_at ("createdAt" DESC)`, `idx_post_media_post` (`1781000000000-...ts:22`). Le modèle déclare aussi `@Index()` sur `post_media.post_id` (`packages/domain-post/src/models/post-media.model.ts:6,12`), mais `synchronize: false` : seul l'index de migration existe (INFERENCE).

### 1.4 Ce que coûte la page côté Node (FAIT sur le banc, `process.cpuUsage`, 300 appels, sans OpenTelemetry)

| Variante | CPU Node par appel (M2) |
| :--- | ---: |
| `getMany()` actuel (deux requêtes TypeORM, jointure, transformation en entités) | **470 µs** |
| Page sans jointure puis médias par `post_id IN (...)`, toujours TypeORM | 244 µs |
| Une requête SQL brute avec `json_agg` des médias | 109 µs |

INFERENCE : un cœur de l'hôte de prod est 1,5 à 2 fois plus lent qu'un cœur M2 pour Node, et l'instrumentation `pg` d'OpenTelemetry ajoute un span par requête : le mode deux requêtes coûte de l'ordre de 0,7 à 1 ms de CPU par `listPosts` en prod, dont 0,5 à 0,8 ms évitables.

### 1.5 Colonnes, mapping, taille de réponse

- Colonnes : toutes les colonnes de `posts` et de `post_media` sont lues, deux fois pour la page (requêtes 1 et 2). `saga_status` et `updatedAt` sont lus mais `saga_status` n'est pas exposé (FAIT : `post.transformer.ts:41-80`).
- Mapping : `databaseMapper.map` crée un `PostEntity` par ligne (`packages/database/src/core/mapper.service.ts:60-96`), puis un `PostDTO`, deux objets `Timestamp`, un tableau `media`. Coût faible par rapport à TypeORM (INFERENCE : moins de 20 µs pour 20 posts).
- Charge utile protobuf (INFERENCE, calcul sur `proto-registry` `proto/volontariapp/post/post.proto`, message `Post`) : par post environ 38 + 38 octets d'UUID, un titre, le contenu (jusqu'à 500 caractères selon le modèle), deux `Timestamp` d'environ 13 octets, l'énum, un `event_id` optionnel. Pour 20 posts : 6 à 14 Ko par page selon la longueur du contenu. Pas un poste majeur, mais chaque octet est encodé deux fois sur le chemin (ms-post vers gateway) et les `int64` des `Timestamp` passent par une conversion `Long` côté protobufjs (option `longs: String`, `packages/contracts-nest/src/grpc.helpers.ts:116-121`).

---

## 2. Le cache du total : ce qu'il rapporte vraiment

FAIT : clé `${authorId ?? '*'}|reader:${readerId}` pour un lecteur qui n'est pas l'auteur (`ms-post` `src/modules/post/providers/posts-total-cache.provider.ts:28-36`), TTL 10 s (ligne 8), 2 000 entrées (ligne 9), cache **par pod** (fournisseur Nest en mémoire, `post.module.ts:30`).

**Taux de réussite attendu dans la rampe** (INFERENCE, calcul) : à 250 req/s, `posts-list` fait 75 req/s ; 200 acteurs tirés au hasard, 2 pods en `round_robin` : environ 0,19 requête par seconde et par couple (pod, acteur). Sur une fenêtre de 10 s : 1 défaut puis 1,9 réussite en moyenne, soit **environ 65 % de réussite, 35 % de COUNT**, environ 26 COUNT par seconde. À 6 à 10 ms chacun : **150 à 260m de CPU de `ms-post-db`** pour les seuls totaux.

**En trafic réel** (INFERENCE) : un utilisateur ouvre le fil toutes les quelques minutes, pas trois fois en 10 s sur le même pod. Le taux de réussite tend vers 0 et chaque `posts-list` relit toute la table. Le cache actuel mesure mieux qu'il ne sert (la doc 04, section 5, le dit déjà : borne haute).

Pourquoi la clé porte le lecteur : seul le terme `post.authorId = :readerId` dépend du lecteur, c'est-à-dire ses propres posts en `PENDING` ou `REJECTED`. Pour presque tous les lecteurs, ce nombre vaut 0.

Deux corrections possibles (section 4, P1).

**Mode « self »** (FAIT, hors mélange de charge) : quand l'auteur lit son propre fil, `listPaginated` passe par `BaseRepository.paginate` (`postgres-post.repository.ts:121-131`, `packages/database/src/core/base.repository.ts:242-269`), donc `findAndCount` : deux requêtes de page **et** un COUNT DISTINCT avec jointure, à chaque appel. `knownTotal` y est ignoré alors que le contrôleur continue de remplir le cache pour la clé `self`. Le cache n'économise rien dans ce mode.

---

## 3. Le coût fixe par appel gRPC

| Poste | Où (origin/main) | FAIT | Coût estimé (INFERENCE) |
| :--- | :--- | :--- | :--- |
| Vérification du jeton interne RS256 (`jose.jwtVerify`) à chaque RPC entrant | garde globale `ms-post` `src/app.module.ts:45-48` ; `packages/auth/src/guards/grpc-internal.guard.ts:15-40` ; `packages/auth/src/services/jwt.service.ts:161-177` | La clé publique est importée une fois (`jwt.service.ts:48-60`) ; le jeton change à chaque requête (signé par la gateway avec un `jti` aléatoire, ligne 155) | 3 à 5 % (référence : 4,5 % de `ms-social` au profil du 2026-11-09). Partie sous-estimée par les profils : la vérification WebCrypto tourne dans le pool de threads de libuv (skill `volontariapp-load-ramp`, section profil). Un cache de jetons vérifiés ne sert à rien tant que la gateway ne réutilise pas ses jetons (plan C3). |
| Même jeton revérifié par `ms-social` | `social-event-post.query-client.ts:67-70` transmet le jeton | | Coût porté par `ms-social`, supprimé si l'appel disparaît (P2) |
| `GrpcValidationPipe` global (class-transformer puis class-validator, `whitelist`, conversion implicite, parcours récursif `processData`) | `ms-post` `src/app.module.ts:38-44` ; `npm-packages` `packages/validation-nest/src/pipes/grpc-validation.pipe.ts:10-32` ; DTO `src/modules/post/dto/request/query/post.query.dto.ts:26-35` (pagination imbriquée) | Les décorateurs personnalisés `@InternalToken` et `@CurrentUser` ne passent pas par le pipe (défaut Nest `validateCustomDecorators: false`, INFERENCE sur le comportement de Nest) | 2 à 4 % (référence : 2,5 % `ms-social`, 4,2 % `ms-event`) |
| Une ligne `info` par RPC | `post.query.controller.ts:75` ; côté `ms-social` `event-post-link.query.controller.ts:42` | Par ligne : `toISOString`, 3 `replace` par expression régulière (`packages/logger/src/masking.ts:59-64`), `maskRecord`, lecture du span actif, `JSON.stringify`, `console.log` (écriture synchrone sur un tube sous Linux) (`packages/logger/src/logger.ts:93-127`) | 1 à 3 % (référence : 3,5 % de `ms-social` à environ 10 lignes par seconde et par pod) |
| `this.logger.debug(\`...${...}\`)` | `social-event-post.query-client.ts:62`, `grpc-internal.guard.ts:34` | Le gabarit est construit même quand `debug` est coupé | négligeable |
| OpenTelemetry : toutes les instrumentations automatiques sauf `fs` et `dns` | `packages/monitoring/src/tracing.ts:37-51,70-78` ; `auto-instrumentations-node` 0.75.0, `build/src/utils.js:107` (seul `fs` exclu par défaut) | Actives donc : `grpc`, `http`, `pg`, `nestjs-core`, `net`, `undici`, `generic-pool`, `runtime-node`, etc. Échantillonnage `parentbased_traceidratio` à 0,1 (`deploy` `apps/base/ms-post/deployment.yaml`) | 2 à 6 % (INFERENCE). Les 90 % non échantillonnés créent quand même un `NonRecordingSpan` par point d'instrumentation, des contextes, et souvent les attributs avant la décision ; `pg` enregistre aussi des histogrammes de durée. Par `listPosts` : span serveur gRPC, 2 spans `nestjs-core`, 2 à 3 spans `pg`, span client gRPC vers `ms-social`. NON VERIFIE : avec `"type": "module"` et `CMD ["dist/main"]` sans `--import` d'un crochet ESM, une partie des instrumentations peut ne pas s'appliquer ; le profil le dira. |
| Appel sortant `ms-social` | `post.query.controller.ts:92-100` | `new Metadata()`, observable rxjs, `firstValueFrom`, encodage et décodage protobuf, trame HTTP/2, span client | 10 à 20 % du CPU d'un `listPosts` (INFERENCE : c'est un second aller-retour gRPC complet, comparable en coût client à la moitié du coût serveur du RPC entrant) |

### 3.1 Un ordre de grandeur qui ne colle pas

FAIT (doc 04, section 4.1) : `ms-post` consomme 315 à 336m par pod aux paliers 225 et 250, pour environ 35 `listPosts` par seconde et par pod. Soit **environ 9 ms de CPU par `listPosts`**. La couche base de données mesurée sur le banc pèse 0,5 à 1 ms, le reste du tableau ci-dessus quelques centaines de microsecondes. INFERENCE : il manque plusieurs millisecondes par requête, ou une part fixe (au repos) importante. Candidats : ramasse-miettes (13 à 15 % ailleurs), OpenTelemetry, encodage protobuf, ou un coût de fond (exports OTLP, métriques). **Seul un profil tranche** ; c'est la première action (section 6). Mesurer aussi le CPU de `ms-post` au repos, sans charge, pour isoler la part fixe.

---

## 4. Propositions

Chaque gain est relatif au CPU consommé à 250 req/s : `ms-post` environ 330 à 400m par pod, `ms-post-db` environ 490m (chiffres de contexte).

### P1. Total en cache global au lieu d'un total par lecteur

- **Quoi** : ne plus mettre l'identifiant du lecteur dans la clé du total.
  - **Variante A, `ms-post` seul** : clé `${authorId ?? '*'}|anon` ou `|reader` (sans l'identifiant) dans `posts-total-cache.provider.ts:28-36`. Le total devient celui du premier lecteur qui a rempli l'entrée : il peut différer de ses propres posts cachés pour les autres lecteurs (0 pour presque tous, 1 à quelques-uns pour un auteur dont un média est en attente ou refusé). Effet visible : `totalPages` faux d'une unité dans un cas rare.
  - **Variante B, exacte** : total = nombre de posts visibles (cache global, une clé par pod) + nombre de posts cachés du lecteur (`COUNT(*) WHERE "authorId" = :reader AND media_status NOT IN (...)`, 0,03 ms sur le banc grâce à `IDX_posts_author_created_at`), lancé en parallèle de la page ou mis en cache par lecteur. Nouvelle méthode ou option dans `domain-post` `listPaginated` (`postgres-post.repository.ts:163-171`).
- **FAIT / INFERENCE** : coût du COUNT et du compte des posts cachés : FAIT sur le banc. Gain : INFERENCE.
- **Gain attendu** : `ms-post-db` : de 26 COUNT par seconde (rampe) à environ 0,2 par seconde, soit **150 à 260m de moins dans la rampe** et jusqu'à 400 à 700m évités en trafic réel à débit égal (taux de réussite actuel proche de 0). `ms-post` : 100 à 200 µs de CPU Node par COUNT évité (requête, span `pg`, conversion du résultat), soit 1 à 2 %.
- **Effort** : A, 30 min avec tests. B, une demi-journée.
- **Risque** : A, total approximatif dans un cas rare (décision produit). B, faible.
- **npm-packages** : A non. B oui (`domain-post`, règle du STOP). Pas de migration.
- **Option en plus** : corriger le mode « self » (section 2) dans la même PR B : il fait un COUNT DISTINCT avec jointure à chaque appel.

### P2. Cache des liens post vers événement dans `ms-post`

- **Quoi** : un cache borné en mémoire `postId -> eventId | aucun` (TTL 30 s pour un lien trouvé, 5 à 10 s pour une absence, pour qu'un lien créé par la saga après la création du post apparaisse vite), consulté avant `getEventsRelatedToPosts` ; seuls les identifiants absents du cache partent vers `ms-social`. Même cache utilisable par `getPost` (`post.query.controller.ts:57-62`).
- **Où** : `ms-post` `src/modules/post/clients/social-event-post.query-client.ts:61-86`, nouveau fournisseur à côté de `posts-total-cache.provider.ts`.
- **FAIT** : l'appel part à chaque `listPosts` (lignes 92-100) ; les liens changent par `LinkPostToEvent` et `UnlinkPostFromEvent`, appelés par la gateway (`analyze_grpc`, client unique `api-gateway` `src/modules/social/controllers/event-post-link.controller.ts:69` et `:87`, index local) et par la saga de création.
- **Gain attendu (INFERENCE)** : rampe (pages 1 à 3 d'un fil global, 60 posts) : taux de réussite proche de 100 %, donc l'appel disparaît presque. `ms-post` : **10 à 20 %** de son CPU par `listPosts` (un aller-retour gRPC client en moins, un span, des objets `Metadata`, rxjs, protobuf). `ms-social`, le processus le plus chargé (70 %) : environ 75 RPC par seconde en moins, chacun avec vérification de jeton, requête Neo4j (et sa capture de pile, 3,7 % du profil) et une ligne `info` ; INFERENCE **5 à 15 % de `ms-social`**. C'est le plus gros gain de plateforme de cette liste.
- **Effort** : 2 à 3 h avec tests (`*.mock.ts`, `*.factory.ts` séparés, horloge injectée comme `PostsTotalCache`).
- **Risque** : un lien créé ou retiré par la route de la gateway met jusqu'au TTL à apparaître dans la liste (même classe de fraîcheur que le cache d'événements de 30 s déjà accepté à la gateway). Décision produit sur le TTL.
- **npm-packages** : non. Migration : non.
- **À plus long terme** : dénormaliser `eventId` dans `posts` (migration Expand/Contract + mise à jour par la saga et par Link/Unlink) supprimerait l'appel sans aucune fraîcheur à gérer ; effort de plusieurs jours, plusieurs dépôts.

### P3. Une seule requête de page au lieu du mode deux requêtes de TypeORM

- **Quoi** : dans `listPaginated`, remplacer `leftJoinAndSelect` + `skip/take` par :
  - soit une requête SQL brute avec `json_agg` des médias (une requête, aucune transformation TypeORM) ;
  - soit page sans jointure (`offset/limit`) puis `post_media WHERE post_id IN (...)` seulement si `media_status` d'au moins un post n'est pas `NONE` (avec `post_media` presque vide, la seconde requête disparaît presque toujours).
- **Où** : `npm-packages` `packages/domain-post/src/repositories/postgres-post.repository.ts:150-157` et `:173` ; mode « self » `:121-131`.
- **FAIT (banc)** : CPU Node 470 µs actuel, 244 µs page puis médias, 109 µs requête brute. Base : deux instructions (planification + exécution environ 0,2 ms) remplacées par une (environ 0,2 ms, ou 0,05 ms sans médias).
- **Gain attendu (INFERENCE)** : 0,5 à 0,8 ms de CPU par `listPosts` en prod, soit **5 à 8 % de `ms-post`** ; une instruction et un span `pg` de moins par requête pour `ms-post-db` (quelques pour cent de la base, la planification comprise).
- **Effort** : une demi-journée avec les tests d'intégration de `domain-post` (`jest.integration.config.js`).
- **Risque** : mapping des lignes brutes (noms de colonnes, dates, ordre stable `createdAt DESC, id DESC`, filtre de visibilité identique à celui du total). Moyen, couvert par les tests d'intégration.
- **npm-packages** : oui (`domain-post`, règle du STOP). Migration : non.

### P4. Cache court de la page du fil global

- **Quoi** : mettre en cache 2 à 5 s, par pod, la page déjà enrichie (posts + `eventId`) pour la clé `(authorId | *, page, limit)`, servie aux lecteurs qui n'ont aucun post caché (variante B de P1 : compte des posts cachés du lecteur à 0,03 ms, lui-même cachable). Un lecteur qui a des posts cachés passe par le chemin actuel.
- **Où** : `ms-post` `post.query.controller.ts:69-111` ; le compte des posts cachés vient de `domain-post`.
- **Gain attendu (INFERENCE)** : sur une réussite, plus de requête de page ni d'appel `ms-social` ; il reste le décodage, la garde, la validation, l'encodage. **30 à 50 % du CPU de `ms-post`** dans la rampe (pages 1 à 3 partagées par tous), et la page 1 du fil global est commune à tous en trafic réel. `ms-post-db` : la charge de `posts-list` devient quasi nulle. Englobe P1 et l'essentiel de P2 pour ce chemin.
- **Effort** : 1 jour.
- **Risque** : fraîcheur : un post créé ou supprimé apparaît ou disparaît jusqu'à 5 s plus tard sur l'autre pod (vider l'entrée sur `CreatePost` et `DeletePost` dans le pod qui les traite). Un auteur qui vient de supprimer son post peut le revoir quelques secondes. Décision produit.
- **npm-packages** : oui pour le compte des posts cachés (sinon variante approximative comme P1-A). Migration : non.

### P5. Lignes « gRPC: ... » en `debug`

- **Quoi** : passer `post.query.controller.ts:75` (et les autres `this.logger.log('gRPC: ...')` des RPC de lecture, lignes 52, 115, 149, 171, 185) en `debug`, comme prévu au plan 2.4. Même chose dans `ms-social` `event-post-link.query.controller.ts:42`.
- **Gain attendu (INFERENCE)** : 1 à 3 % de `ms-post`, plus la part de l'agent Datadog (hors pod).
- **Effort** : 15 min. **Risque** : moins de visibilité ; les traces à 10 % et les erreurs restent. **npm-packages** : non.

### P6. Réduire OpenTelemetry au nécessaire

- **Quoi** : `OTEL_NODE_DISABLED_INSTRUMENTATIONS=net,nestjs-core,undici,generic-pool,express,router,connect` (à valider une par une) dans `deploy` `apps/base/ms-post/deployment.yaml` ; garder `grpc`, `http`, `pg`. `nestjs-core` double le span gRPC, `net` crée des spans par socket.
- **Gain attendu (INFERENCE)** : 1 à 4 %, à confirmer par le profil (ajouter une famille `@opentelemetry` à `analyze-cpuprofile.mjs`, section 6).
- **Effort** : PR `deploy` de 15 min. **Risque** : traces moins détaillées. **npm-packages** : non (ou, pour tous les services, dans `monitoring` `buildInstrumentationConfig`, règle du STOP).

### P7. Jetons internes vérifiés en cache (plan C3)

- **Quoi** : cache `jeton -> utilisateur` jusqu'à `exp` dans `JwtService.verifyInternal`, utile seulement quand la gateway réutilise un jeton quelques secondes.
- **Où** : `packages/auth/src/services/jwt.service.ts:124-127` (vérification) et la signature côté gateway (`grpc-metadata.helper.ts:13-19`).
- **Gain attendu (INFERENCE)** : 3 à 5 % de `ms-post`, autant dans chaque `ms-*`, plus la signature à la gateway.
- **Effort** : 1 jour avec revue de sécurité. **Risque** : un jeton révoqué reste valable jusqu'à son expiration (déjà le cas aujourd'hui, la vérification ne consulte aucune liste). **npm-packages** : oui (`auth`, règle du STOP).

### P8. Validation allégée sur les RPC de lecture chauds

- **Quoi** : pour `ListPosts`, valider à la main (`page`, `limit` entiers bornés, `authorId` UUID) et exclure ce RPC du pipe global, ou passer le pipe en `transform` sans `whitelist` pour les DTO de lecture.
- **Gain attendu (INFERENCE)** : 2 à 3 %. **Effort** : 2 h. **Risque** : moyen (entrée non validée si mal fait) ; à faire seulement si le profil montre class-validator au-dessus de 3 %. **npm-packages** : non.

### P9. Mémoire de Node

- FAIT : `ms-post` tourne déjà avec `NODE_OPTIONS=--max-semi-space-size=16` (`deploy` `apps/base/ms-post/deployment.yaml`, variable `NODE_OPTIONS`) ; le plan 05 proposait 32 pour les `ms-*`.
- **Quoi** : essayer 32 si le profil montre le ramasse-miettes au-dessus de 10 %, en surveillant la mémoire (limite 256Mi).
- **Gain attendu (INFERENCE)** : 2 à 5 %. **Effort** : 15 min. **npm-packages** : non.

### P10. Pistes écartées ou de faible gain

| Piste | Pourquoi faible ou écartée |
| :--- | :--- |
| Pagination par curseur (keyset) au lieu d'`OFFSET` | FAIT banc : page 3 (`OFFSET 40`) à 0,1 ms, l'`OFFSET` ne coûte rien aux profondeurs servies. Changement de contrat (`proto-registry`, gateway, `nativapp`). À garder pour le jour où les pages profondes compteront. |
| Index `("createdAt" DESC, id DESC)` | Supprime l'`Incremental Sort` (quelques microsecondes sur le banc). Migration pour un gain invisible. |
| Index couvrant | Inutile : la page lit `content` et toutes les colonnes. |
| Deux `DataSource` vers la même base (`PostgresBridgeModule` et `TypeOrmModule`, `ms-post` `src/providers/database/database.module.ts:17-37`) | Deux pools, deux fois plus de connexions au repos ; aucun coût par requête (INFERENCE). À regarder pour la mémoire de `ms-post-db`, pas pour le CPU. |
| Coût de fond de `ms-post-db` (outbox interrogé toutes les 500 ms à 5 s, `deploy` `apps/base/ms-post/deployment-outbox.yaml`, `OUTBOX_BATCH_INTERVAL_MS=500`, `OUTBOX_MAX_IDLE_INTERVAL_MS=5000` ; check Datadog Postgres) | Probablement faible ; à chiffrer avec `pg_stat_statements` (section 6) avant d'agir. |

### 4.1 Autres RPC de `ms-post`

FAIT (`analyze_grpc PostService`, toutes les racines indexées) : hors `ListPosts`, les lectures appelées depuis l'extérieur sont `GetPost` (gateway, page d'un post ; elle aussi appelle `ms-social` à chaque fois, `post.query.controller.ts:57-62`), `ListComments` (gateway), `ListRecentPostsByAuthors` et `ListPostsByIds` (gateway `ranked-feed.service.ts`, `worker-ranking` `post-ranking.client.ts`). Aucune n'est dans le mélange de charge. `ListRecentPostsByAuthors` fait une requête de fenêtre puis un `find` avec relation (`postgres-post.repository.ts:399-463`) : même mode TypeORM sans `skip/take`, donc une seule requête. Rien d'urgent ; P2 et P3 s'appliquent à `GetPost`.

---

## 5. Sources d'allocation (ramasse-miettes)

Par `listPosts`, du plus lourd au plus léger (INFERENCE, à confirmer par un profil d'allocation) :

1. **TypeORM** : construction de deux à trois `SelectQueryBuilder`, deux `clone()` de l'`expressionMap`, chaînes SQL de 1 à 2 Ko construites à chaque appel, réécriture des noms de propriétés par expressions régulières, lignes brutes (environ 13 colonnes par ligne, deux fois), regroupement par `RawSqlResultsToEntityTransformer`. Supprimé en grande partie par P3.
2. **pg** : objets de ligne, analyse des `timestamp` en `Date` (40 à 60 par page), tampons du protocole.
3. **gRPC et protobuf** : tampons de 6 à 14 Ko par réponse, objets `Metadata`, `Long` pour les `int64`, et le même lot pour l'appel `ms-social` (supprimé par P2).
4. **OpenTelemetry** : spans non échantillonnés, contextes, attributs (P6).
5. **Validation** : instances de DTO, tableaux d'erreurs vides (P8).
6. **Logger** : objet de charge utile, chaîne ISO, trois copies masquées du message, chaîne JSON (P5).
7. **Mapping et DTO** : `PostEntity`, `PostDTO`, deux `Timestamp`, tableau `media` par post : faible.

---

## 6. Mesures qui confirment ou infirment (à lancer par Victor)

### 6.1 Profil CPU d'un pod `ms-post`

Procédure de la skill `volontariapp-load-ramp`, section « Profil CPU d'un pod Node », appliquée à `ms-post` :

```bash
POD=$(kubectl -n prod get pods -l app=ms-post -o name | head -1)
kubectl -n prod exec "$POD" -c ms-post -- sh -c 'kill -USR1 1'
kubectl -n prod port-forward "$POD" 9229:9229 &
# charge stable : LOAD_STEPS="225" LOAD_STEP_SECONDS=120, 20 s de chauffe
node .agents/skills/volontariapp-load-ramp/scripts/capture-cpu-profile.mjs 30 ms-post-225.cpuprofile
node .agents/skills/volontariapp-load-ramp/scripts/analyze-cpuprofile.mjs ms-post-225.cpuprofile 30
# puis : arrêter le port-forward et supprimer le pod profilé
```

Avant de lancer l'analyse, ajouter trois familles à `analyze-cpuprofile.mjs` (aujourd'hui elles tombent dans « autres dépendances ») : `/node_modules/typeorm/`, `/node_modules/pg/` et `/node_modules/pg-protocol/`, `/node_modules/@opentelemetry/`. Sans elles, P3 et P6 ne se lisent pas.

Ce qu'il faut lire : part de TypeORM + pg (cible de P3), de grpc-js + protobuf côté client (`ms-social`, cible de P2), d'OpenTelemetry (P6), de class-validator (P8), du logger (P5), du ramasse-miettes (P9). Comparer le temps occupé du fil principal au CPU du pod (`kubectl top pod`) : l'écart donne la part du pool de threads (vérification RSA, P7). Prendre aussi un relevé `kubectl top` de `ms-post` **au repos** (section 3.1).

### 6.2 Ce que fait `ms-post-db`

1. Sans extension, en lecture seule : la fréquence des parcours séquentiels de `posts` donne directement le nombre de COUNT (P1).

```sql
SELECT seq_scan, seq_tup_read, idx_scan FROM pg_stat_user_tables WHERE relname = 'posts';
-- relever, palier de 120 s à 225 req/s, relever : delta(seq_scan) / 120 = COUNT par seconde
SELECT xact_commit FROM pg_stat_database WHERE datname = 'ms-post';  -- transactions par seconde
```

2. Avec `pg_stat_statements` (NON VERIFIE : probablement absent ; il faut `shared_preload_libraries=pg_stat_statements`, donc une PR `deploy` sur `apps/overlays/prod/ms-post/db-postgres/kustomization.yaml` et un redémarrage de la base, puis `CREATE EXTENSION pg_stat_statements;` et `SET pg_stat_statements.track_planning = on` dans la configuration) :

```sql
SELECT pg_stat_statements_reset();
-- palier de 120 s à 225 req/s
SELECT calls, round(total_exec_time::numeric, 1) AS exec_ms, round(total_plan_time::numeric, 1) AS plan_ms,
       round(mean_exec_time::numeric, 3) AS mean_ms, rows, left(query, 120) AS q
FROM pg_stat_statements ORDER BY total_exec_time + total_plan_time DESC LIMIT 15;
```

Ce qu'il faut lire : le COUNT (`calls`, `mean_ms`) contre les deux requêtes de page ; la part de planification ; les requêtes de l'outbox et du check Datadog. Si les COUNT n'expliquent pas l'essentiel des 490m, P1 descend dans le classement.

3. `EXPLAIN (ANALYZE, BUFFERS)` en prod des trois requêtes de la section 1.2 (copies exactes dans `/private/tmp/claude-501/-Users-victoragahi-Developer-meta/a9f40403-efe3-4c69-84c2-d4eb6c9db0a0/scratchpad/pg/explain.sql`) pour vérifier que le plan DISTINCT est le même qu'au banc.

### 6.3 Compteurs des caches (plan C1)

Une ligne `info` par minute dans `ms-post` : réussites, défauts, taille, pour `PostsTotalCache` et, après P2, le cache des liens. Elle donne le taux réel de réussite en trafic réel, la donnée qui manque le plus pour P1 et P4.

---

## 7. Classement

| Rang | Proposition | Gain attendu | Effort | npm-packages | Pourquoi ce rang |
| ---: | :--- | :--- | :--- | :--- | :--- |
| 1 | **P2** cache des liens post vers événement | `ms-post` 10 à 20 %, `ms-social` 5 à 15 % | 2 à 3 h | non | Le seul levier qui soulage aussi le processus le plus chargé de la plateforme ; aucun prérequis |
| 2 | **P1** total global (A tout de suite, B ensuite) | `ms-post-db` 150 à 260m dans la rampe, bien plus en trafic réel ; `ms-post` 1 à 2 % | A 30 min, B ½ jour | A non, B oui | Le COUNT est la requête la plus chère de la base (50 fois la page) et le cache actuel ne sert presque pas en trafic réel |
| 3 | **P3** une seule requête de page | `ms-post` 5 à 8 %, une instruction de moins par requête | ½ jour | oui | Gain FAIT au banc (470 contre 109 µs) ; corrige aussi le mode « self » |
| 4 | **P5** journaux « gRPC: » en `debug` | 1 à 3 % (et `ms-social`) | 15 min | non | Presque gratuit |
| 5 | **P4** cache de la page du fil global | `ms-post` 30 à 50 % sur `posts-list` | 1 jour | oui (compte des posts cachés) | Le plus gros gain pour `ms-post`, mais une décision produit sur la fraîcheur, et il dépend de B (P1) |

Ensuite, selon le profil : P6 (OpenTelemetry), P7 (jetons, déjà plan C3), P9 (semi-space 32), P8 (validation).

## 8. Ordre de PR proposé

1. **Mesurer d'abord** (sans PR de code) : profil `ms-post` à 225 req/s avec les familles ajoutées à `analyze-cpuprofile.mjs` (PR `meta`), delta de `seq_scan` sur `posts`, CPU au repos. Si le profil contredit la section 3.1, réordonner.
2. PR `ms-post` : P5 (journaux en `debug`) + compteurs de caches (C1) + P1 variante A si Victor accepte le total approximatif. Une PR, un déploiement, une mesure.
3. PR `ms-post` : P2 (cache des liens, TTL à décider).
4. PR `npm-packages` (`domain-post`) : P3 + P1 variante B + correction du mode « self ». **STOP** après `yarn build`, `yarn test`, tests d'intégration et changeset ; attendre la publication par la CI.
5. Après publication : PR `ms-post` qui monte `domain-post`, branche P1-B, puis, si la décision produit le permet, P4.
6. PR `deploy` : P6 (instrumentations coupées) et, si le profil le justifie, P9.
7. P7 avec le plan C3 (`auth`, gateway), revue de sécurité.

Une mesure entre chaque étape (règle des chapitres 03 et 05 : une phase, une mesure).

---

## Annexe : périmètre et absences

- « Un seul client de `ListPosts` » : `analyze_grpc PostService` sur toutes les racines indexées par `mesh-mcp` (copies de travail locales). Non vérifié : appels construits à l'exécution.
- « `pg_stat_statements` probablement absent » : NON VERIFIE ; déduit de la configuration du chart (`apps/overlays/prod/ms-post/db-postgres/kustomization.yaml`), qui ne déclare aucune bibliothèque préchargée. Aucune requête n'a été faite sur la base de prod.
- Les chiffres du banc (sections 1.3 et 1.4) viennent d'un Postgres 16.14 local sur Apple M2, données synthétiques (29 000 posts, 1 200 auteurs, contenu de 216 caractères, 0,5 % de posts en `PENDING`, 30 médias), sans OpenTelemetry. Scripts : `/private/tmp/claude-501/-Users-victoragahi-Developer-meta/a9f40403-efe3-4c69-84c2-d4eb6c9db0a0/scratchpad/pg/schema.sql`, `.../pg/gen-sql.cjs`, `.../pg/explain.sql`.
