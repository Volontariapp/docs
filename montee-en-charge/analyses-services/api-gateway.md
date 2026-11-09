# api-gateway : où gagner du CPU et de la latence par requête

Analyse seule, rédigée le 2026-11-09. Aucun fichier modifié dans un repo. Code lu sur `origin/main` :
`api-gateway` 716f3d9 (PR #117), `npm-packages` fff2319f (PR #313), `deploy` cdedc92 (PR #71).
Conventions : **FAIT** = ligne lue ou sortie d'outil de cette session, avec `fichier:ligne` ;
**INFERENCE** = raisonnement non mesuré ; **NON VERIFIE** = hypothèse à tester.

---

## 0. Avertissement sur les profils (à lire d'abord)

- **FAIT** : `gateway-225.cpuprofile` (mtime 2026-11-09 11:06:45, 190 noeuds) n'est pas le profil
  de 10:03Z décrit au chapitre 04. 9 % de temps occupé, dont 89 % dans `_kill`, et le reste dans
  `cleanup` / `hasOnModuleDestroyHook` de Nest et `goaway` HTTP/2 : c'est un processus en arrêt.
  `ms-event-225.cpuprofile` et `ms-social-225.cpuprofile` ont le même défaut (98 % `_kill`).
  Les trois fichiers ont été réécrits à 11:06, probablement pendant un déploiement (INFERENCE).
- Conséquence : la répartition « GC 13,8 %, HTTP 21,1 %, gRPC 8,5 %, JWT 4,5 % » à 225 req/s
  vient du chapitre 04 (section 4.5) et **ne peut pas être recalculée** à partir des fichiers
  présents. Pour creuser par fonction, j'ai utilisé `gateway.cpuprofile` (2026-11-08, 150 req/s,
  logs `debug`, traces à 100 %, 39 % occupé). Ses parts de journaux et d'OpenTelemetry sont donc
  plus fortes qu'aujourd'hui ; la **structure** (qui appelle quoi) reste valable.
- Scripts jetables : `scratchpad/incl.mjs` (temps inclusif par motif), `bucket.mjs` (temps attribué
  au composant le plus profond de la pile), `callers.mjs` (appelants d'une fonction),
  `bench-jwt.mjs` (jose RS256 / ES256 / EdDSA).
- **À refaire avant toute PR de code** : un profil propre à 225 req/s, plus un profil d'allocation
  (section 7). Sans lui, les gains ci-dessous restent des ordres de grandeur.

### Ordre de grandeur du budget

- INFERENCE (calcul) : 5 pods occupés à 48 % pour 225 req/s donnent environ 2,4 coeurs de fil
  principal, soit **environ 10 à 11 ms de CPU par requête** sur le fil principal, plus le pool de
  threads (signature RSA) et les threads du GC. Au profil du 2026-11-08 : 11,8 s occupées pour
  environ 30 req/s par pod, soit environ 13 ms par requête.
- Le noeud fait 7,2 à 8,4 vCPU à 225 req/s (chapitre 05). La gateway en porte environ 30 à 35 %
  (INFERENCE). **Chaque point de CPU gagné sur la gateway vaut environ 0,3 point de noeud.**
- Côté latence, la gateway ajoute surtout son propre CPU et l'attente de sa boucle d'événements
  (quelques ms à 48 % d'occupation). La p95 de 489 ms à 250 req/s vient de la saturation du noeud
  (chapitre 04, 4.3). **Le levier latence de la gateway passe donc d'abord par le CPU total du
  noeud**, ensuite par les sauts gRPC en série.

### Profil du 2026-11-08, attribution au composant le plus profond (FAIT, `bucket.mjs`)

| Composant | Part du temps occupé |
| :--- | ---: |
| OpenTelemetry (traces à 100 % ce soir-là) | 17,2 % |
| Ramasse-miettes | 16,2 % |
| Journaux et console (`debug` actif ce soir-là) | 11,1 % |
| grpc-js | 8,5 % |
| Serveur HTTP Node | 7,2 % |
| jose (JWT) | 7,0 % |
| Réseau et flux Node | 5,7 % |
| Express et routeur | 3,2 % |
| `JSON.stringify` de la réponse (`express/lib/response.js:1029`) | 3,1 % |
| Nest | 2,9 % |
| protobufjs | 2,2 % |
| rxjs | 1,9 % |
| Notre code | 1,2 % |
| class-validator + class-transformer | 1,5 % |
| etag, body-parser, qs, cors | 1,4 % |

---

## 1. Les quatre routes du mélange : appels gRPC

Outils : `analyze_grpc` (mesh-mcp) sur `SearchEvents`, `GetIsFollowing`, `ParticipationQueryService`,
puis lecture du code sur `origin/main`. **Remarque d'outil (FAIT)** : `analyze_grpc` sur
`GetSearchExclusions` et `CountEventParticipants` renvoie « 0 client, 0 handler, pas de .proto
indexé », alors que les deux RPC existent (`proto-registry`, `social.services.proto:95` et `:106`,
lu dans `origin/main` et `HEAD`) et sont appelés par la gateway (lignes citées ci-dessous). Je ne
qualifie pas cela de défaut de l'outil sans la procédure `volontariapp-mesh-mcp-verification` ;
les séquences ci-dessous reposent sur la lecture du code. L'index mesh-mcp lit les checkouts locaux
(`api-gateway` est sur `feat/admin-active-locations`), d'où des numéros de ligne différents
de `origin/main`.

### 1.1 `GET /events` avec les 4 filtres `exclude*` (40 %)

Séquence (FAIT, `event.query-controller.ts:56-80`, `event-social-filter.service.ts:52-120`,
`event-participants.service.ts:59-116`) :

1. `GrpcInternalInterceptor` : signature RS256 du jeton interne (attendue avant le handler).
2. **Série 1** : `ParticipationQueryService.GetSearchExclusions` (ms-social, Neo4j), un seul appel
   (`event-social-filter.service.ts:119`).
3. Filtrage `isUUID` de chaque id, jusqu'à 2 x 1 000 ids (`event-social-filter.service.ts:129`).
4. **Série 2** : `EventQueryService.SearchEvents` (ms-event) avec `excludedIds` et
   `excludedOrganizerIds` (`event.query-controller.ts:72`).
5. Mapping `SearchEventsResponseDTO.fromResponse` (spread de chaque événement, `event.dto.ts:86-101`).
6. **Série 3, conditionnelle** : `CountEventParticipants` pour les ids absents du cache de 30 s,
   lots de 100 en `Promise.all` (`event-participants.service.ts:99`). Avec `limit=20`, un seul lot.
7. Une ligne `info` « Listing events » par requête (`event.query-controller.ts:57`).

Ce qui est en série et pourquoi : 2 dépend de rien, 4 dépend de 2 (les exclusions changent la page
renvoyée), 6 dépend de 4 (ids de la page). **Aucune parallélisation correcte n'est possible à
l'intérieur de la requête** sans changer la sémantique (INFERENCE : lancer `SearchEvents` sans les
exclusions puis filtrer casserait la pagination et `totalCount`).

Ce qui peut être évité :
- **Saut 2, cache des exclusions par utilisateur (5 s)** : déjà au plan, phase C2, décision produit
  (« un blocage s'applique tout de suite »). Gain le plus fort de toute la liste côté latence
  (un aller-retour ms-social + Neo4j en moins sur 40 % du trafic) et côté noeud (ms-social est à 70 %).
  Le CPU gagné est surtout dans ms-social et Neo4j, pas dans la gateway.
- **Saut 6** : déjà amorti par le cache de 30 s (PR #117). Son taux de réussite n'est pas mesuré
  (phase C1). À plus long terme, un compteur dénormalisé dans ms-event supprimerait le saut,
  mais c'est un chantier multi-repo (événements, migration) : hors périmètre gateway.
- Taille des messages (INFERENCE, NON VERIFIE en production) : pour un utilisateur très actif, la
  réponse de `GetSearchExclusions` puis la requête `SearchEvents` portent chacune jusqu'à environ
  70 Ko d'UUID (2 000 x 36 octets) ; pour l'utilisateur moyen du simulateur, beaucoup moins.
  `isUUID` (validator.js, regex) sur 2 000 ids coûte de l'ordre de 0,1 à 0,3 ms (INFERENCE).
  Option peu chère : ne filtrer que si ms-social peut renvoyer un id vide (la cause documentée est la
  chaîne vide), c'est-à-dire remplacer `isUUID` par un test `id !== ''` plus une vérification de
  longueur ; ms-event revalide de toute façon. Gain faible, risque faible.

### 1.2 `GET /posts` (30 %)

FAIT (`post.query-controller.ts:76-95`, `event-lookup.service.ts:48-86`) :
1. Signature du jeton interne.
2. Une ligne `info` avec `JSON.stringify(request)` puis masquage par le logger
   (`post.query-controller.ts:80`).
3. **Série 1** : `PostService.ListPosts` (ms-post).
4. **Série 2, conditionnelle** : `GetEventsByIds` pour les événements absents du cache (500 entrées,
   30 s).
5. `EventDTO.fromResponse` pour chaque événement trouvé, même ceux venant du cache
   (`event-lookup.service.ts:82`) : un objet neuf par post et par requête.

Évitable : rien côté sauts au-delà du cache. INFERENCE : on peut garder en cache le `EventDTO`
déjà construit plutôt que l'`Event` brut (le DTO ne dépend que de l'événement et de la base d'URL
publique, fixe par pod), ce qui retire un spread et un calcul d'URL par post. Gain faible (moins
de 1 %), allocation en moins.

### 1.3 `GET /users/me` (20 %)

FAIT (`user.query-controller.ts:36-45`) : signature du jeton interne, une ligne `info`, un appel
`UserService.GetUser` (ms-user), mapping `UserResponseDTO`. Un seul saut, rien à paralléliser.

### 1.4 `GET /social/users/:userId/is-following` (10 %)

FAIT (`relationship.query-controller.ts:87-95`, `analyze_grpc GetIsFollowing` : client unique dans
la gateway, handler `ms-social/.../relationship.query.controller.ts:139`) : signature du jeton
interne, un appel `GetIsFollowing`, mapping trivial. Pas de log `info`.

### 1.5 Bilan des sauts

| Route | Sauts gRPC en série | Signature RS256 attendue avant le 1er saut |
| :--- | ---: | :--- |
| events-list-app | 2 à 3 | oui |
| posts-list | 1 à 2 | oui |
| me | 1 | oui |
| is-following | 1 | oui |

Moyenne pondérée : environ 1,6 à 2 appels gRPC par requête (INFERENCE, selon les taux de cache).

---

## 2. Le pipeline par requête

Ordre des couches Express (FAIT, `main.ts` sur `origin/main`, et l'ordre d'enregistrement de Nest) :
`query` (qs, `main.ts:57`), `expressInit`, `jsonParser`, `urlencodedParser`, `cors` (`main.ts:61`),
9 middlewares Scalar montés sur leur chemin (`swagger-setup.ts:237-256`, appelés à `main.ts:69`),
`AccessTokenMiddleware` et `RefreshTokenMiddleware` (`main.ts:77-78`), puis environ 132 routes
Nest (décompte des décorateurs `@Get/@Post/...` dans `src/modules`) et le proxy WebSocket.

| Élément | Constat | Coût mesuré (profil du 08-11) |
| :--- | :--- | :--- |
| `AccessTokenMiddleware` | extrait le Bearer, une ligne `debug` (filtrée aujourd'hui) | faible hors log |
| `RefreshTokenMiddleware` | tourne sur **toutes** les routes ; avec un Bearer, il range le **jeton d'accès** dans `request.refreshToken` (`refresh-token.middleware.ts:16-17`) ; sans Bearer, une ligne `warn` par requête (`:26`) | faible ; bug latent, pas de perf |
| Cookies | aucune dépendance `cookie-parser` dans `package.json` : la branche cookies des deux middlewares est morte (FAIT) | nul |
| `AccessTokenGuard` | `jose.jwtVerify` RS256 à chaque requête, clé importée une fois et gardée (`jwt.service.ts:76-88`) | jose verify environ 4,5 % inclusif |
| `RolesGuard` | deux lectures de métadonnées | 0,2 % |
| `ValidationPipe({ transform: true })` | `plainToInstance` + `validate` sur les DTO `@Query` | 1,4 % inclusif |
| `GrpcInternalInterceptor` | `from(promise).pipe(switchMap)` + signature RS256 (`grpc-internal.interceptor.ts:24-38`) | voir section 3 |
| `GlobalExceptionFilter` | seulement sur erreur | 0 % |
| `ClassSerializerInterceptor` | non trouvé dans `api-gateway/src` (recherche de `ClassSerializer` et `UseInterceptors`, `origin/main`) | 0 |
| ETag | Express 5 calcule un ETag faible (hachage du corps) sur chaque réponse ; aucun réglage `etag` dans `api-gateway/src` et aucun usage de `If-None-Match` / `etag` dans `nativapp/src` (git grep, `origin/main`) | 0,5 % (etag) + `fresh` |
| `x-powered-by` | non désactivé (non trouvé dans `api-gateway/src`) | négligeable, hygiène |
| Compression | aucune dans la gateway ni dans `deploy` (git grep `compress`) | 0 ; ne pas l'ajouter dans Node |
| Swagger / Scalar en production | 9 documents générés au démarrage et gardés en mémoire, 9 couches traversées par chaque requête | quelques dixièmes de % ; tas plus gros (NON VERIFIE) |
| Journaux `info` par requête | `listEvents` (`:57`), `listPosts` avec `JSON.stringify` (`:80`), `getMe` (`:38`) : environ 0,9 ligne par requête du mélange | 0,7 % du temps à 225 (chapitre 04) |
| Routeur Express | appariement linéaire de toutes les couches (`path-to-regexp match` 0,3 % propre, `router next` 1,0 % propre) | 1 à 2 % |

---

## 3. JWT

### Mesure locale (FAIT, `bench-jwt.mjs`, Node 24.2, jose 6.2.13, Mac, clé RSA 2048)

| Algorithme | Signature (CPU) | Vérification (CPU) | Taille du jeton |
| :--- | ---: | ---: | ---: |
| RS256 | 596 us | 45 us | 602 o |
| ES256 | 52 us | 85 us | 346 o |
| EdDSA (Ed25519) | 64 us | 120 us | 346 o |

La taille réelle de la clé de production n'est pas lue (NON VERIFIE ; 2048 supposé). L'hôte Proxmox
est probablement plus lent que le Mac (INFERENCE).

### Constats (FAIT)

- `signInternal` signe un JWT RS256 neuf **à chaque requête authentifiée**, avec un `jti` aléatoire
  (`jwt.service.ts:118-122`, `:151-159`). Le jeton interne vit **1 h** (`config/default.config.json`,
  `internalExpiresIn: "1h"`, non surchargé dans `production.config.json`).
- La charge utile est une copie complète du jeton d'accès vérifié (`{ ...user }`, `:152`), donc avec
  son `jti`, `iat` et `exp`, que `SignJWT` écrase ensuite.
- `jose` copie la charge utile par `structuredClone` à chaque signature
  (`JWTClaimsBuilder`, 0,5 % du profil du 08-11).
- La signature RSA tourne dans le pool de threads libuv (`SignJob`) : **elle n'apparaît presque pas
  dans le profil du fil principal mais elle consomme le CPU du pod**. INFERENCE : à 45 req/s par pod
  et environ 0,6 ms par signature, cela fait environ 27 ms de CPU par seconde et par pod, soit
  5 à 6 % du CPU d'un pod à 450 à 500m, invisibles dans les 48 % « occupés ».
- Le `jti` n'est lu nulle part : non trouvé dans `src/` de `ms-user`, `ms-event`, `ms-post`,
  `ms-social`, `ms-storage`, `ms-ranking`, `ws-service`, ni dans `npm-packages/packages/auth/src`
  et `packages/shared/src` (git grep `jti` sur `origin/main` de chacun). Les runners ne sont pas
  couverts par cette recherche.
- Aucune révocation des jetons d'accès : le garde ne fait que vérifier la signature et l'expiration
  (`access-token.guard.ts:46-55`).
- **L'instrumentation gRPC d'OpenTelemetry écrit `traceparent` dans l'objet `Metadata` passé par
  l'appelant** (`instrumentation-grpc/build/src/clientUtils.js:118` et `:175-178`). Il ne faut donc
  jamais réutiliser un même `Metadata` entre deux requêtes ; seule la chaîne du jeton peut l'être.

### Options

**J1. Réutiliser le jeton interne pour une courte durée (recommandé).**
Cache borné (LRU, par exemple 10 000 entrées) clé = jeton d'accès complet (ou son segment de
signature), valeur = jeton interne, durée = min(60 s, expiration du jeton d'accès, expiration du
jeton interne moins une marge). Nouveau `Metadata` à chaque requête, avec la chaîne en cache.
- Gain CPU (INFERENCE) : la signature passe de 1 par requête à 1 par utilisateur et par minute ;
  environ 5 à 6 % du CPU du pod (pool de threads) + 2 à 2,5 % du fil principal
  (`SignJWT`, `structuredClone`, base64). Total **7 à 8 % du CPU de la gateway**, soit
  0,15 à 0,2 vCPU à 225 req/s.
- Gain latence : la signature (0,6 ms et plus, attente du pool comprise) est sur le chemin critique
  avant le premier saut gRPC : **environ -0,6 à -1 ms par requête**. Bonus : un en-tête
  `x-internal-token` identique d'une requête à l'autre est indexé par HPACK dans la table dynamique
  HTTP/2 (environ 650 à 900 octets en moins par appel, moins de décodage côté `ms-*`) (INFERENCE).
- Sécurité : la fenêtre de rejeu ne grandit pas (le jeton vit déjà 1 h). Un changement de rôle
  produit un nouveau jeton d'accès, donc une nouvelle clé de cache. On perd l'unicité par requête
  du `jti`, que personne ne lit (voir ci-dessus). À faire valider en revue de sécurité (phase C3).
- Où : `npm-packages/packages/auth/src/services/grpc-metadata.helper.ts:13-19` ou
  `jwt.service.ts:118`. **Règle du STOP** : PR `npm-packages`, publication, puis montée de version
  dans la gateway.

**J2. Cache des jetons d'accès vérifiés à la gateway.**
Même LRU : clé = chaîne complète du jeton, valeur = charge utile, jusqu'à min(exp, 60 s).
- Gain CPU (INFERENCE) : la vérification RS256 coûte peu en crypto (45 us) mais `jwtVerify` pèse
  environ 4,5 % inclusif au profil du 08-11 (décodage base64, JSON, `validateClaimsSet`,
  webcrypto). Environ **2 à 4 % de la gateway**.
- Sécurité : équivalente à l'existant tant qu'il n'y a pas de révocation ; à revoir le jour où une
  liste de révocation existe. Comparer la chaîne entière, jamais un préfixe.
- Où : `access-token.guard.ts:47` ou `jwt.service.ts:135`. Même PR que J1 (une seule entrée de cache
  peut porter `{ user, internalToken, expiresAt }`). Règle du STOP.

**J3. Cache des jetons internes vérifiés dans les `ms-*`.** Conséquence directe de J1 : avec un
jeton réutilisé, `GrpcInternalGuard` (`grpc-internal.guard.ts:30`) peut garder le résultat par chaîne.
Chapitre 04 : `verifySignature` pèse 4,5 % de ms-social, le service le plus chargé. Hors gateway,
mais même PR `auth`.

**J4. ES256 ou EdDSA à la place de RS256 : non recommandé maintenant.**
ES256 signe 11 fois plus vite mais vérifie 2 fois plus lentement (85 contre 45 us). Avec J1, la
signature devient rare et la vérification reste fréquente dans chaque `ms-*` : passer à ES256
**coûterait** du CPU au total. Et il faut une rotation de clés coordonnée sur tous les services.
Pour le jeton d'accès (signé par ms-user à la connexion, vérifié à chaque requête), RS256 est déjà
l'algorithme le moins cher à vérifier.

**J5. `UV_THREADPOOL_SIZE` : inutile.** INFERENCE : 45 signatures/s x 0,6 ms = 3 % d'un thread sur
4 ; aucune file d'attente. Après J1, encore moins.

---

## 4. Clients gRPC

FAIT :
- Un client Nest par package, et un client grpc-js par service mis en cache par Nest
  (`@nestjs/microservices/client/client-grpc.js:51-52`, `clients.get(name)`, Nest 11.2.8). Les
  canaux sont réutilisés ; pas de création de canal par requête.
- Options de canal : `round_robin`, résolution de service config désactivée,
  `max_connection_age` 5 min côté serveur (`contracts-nest/src/grpc.helpers.ts:92-97`).
  Aucun `keepalive_time_ms` côté client.
- `ms-storage` et `ms-ranking` restent sur des `Service` ClusterIP (`deployment.yaml` de la gateway,
  `MS_STORAGE_URL=ms-storage:80`, `MS_RANKING_URL=ms-ranking:80`) : pas de répartition entre réplicas,
  sans effet sur le mélange (aucune de ces routes ne les appelle).
- Chargement des protos : `keepCase: false, longs: String, enums: String, defaults: true`
  (`grpc.helpers.ts:116-123`). `defaults: true` matérialise chaque champ absent (chaînes vides,
  tableaux vides) dans chaque message décodé : plus d'objets, plus d'octets dans le JSON final.
- **Aucune échéance (deadline) sur les appels des routes chaudes** : la seule échéance trouvée est
  dans `storage-grpc-errors.ts:31-36` (git grep `deadline` / `timeout(` dans `api-gateway/src`).
  Nest transmet un 3e argument comme `CallOptions` (`client-grpc.js:196`,
  `client[methodName](...args, callback)`) et annule l'appel au désabonnement (`:204-207`).

Options :
- **G1. Échéances sur les appels chauds (2 à 3 s)** en passant `{ deadline: Date.now() + N }` en
  3e argument ; étendre `WithMetadata` (`src/common/types/grpc.types.ts:4-8`) pour l'accepter.
  Gain CPU nul en régime normal. Gain **latence en surcharge** : au-delà de 275 req/s, les requêtes
  s'empilent sans limite ; une échéance coupe le travail inutile dans les `ms-*` (le serveur grpc-js
  reçoit l'annulation) et rend l'effondrement moins brutal (INFERENCE). Gateway seule, effort S.
  Risque : erreurs `DEADLINE_EXCEEDED` à mapper en 503/504.
- **G2. `defaults: false`** : moins d'allocations et de JSON (INFERENCE, quelques % de protobuf et de
  GC). **Risque élevé** : tous les mappers qui supposent un tableau ou une chaîne par défaut
  changent de comportement. À ne pas faire sans une campagne de tests ; `npm-packages`, règle du STOP.
- Keepalive client : non nécessaire tant que `max_connection_age` recycle les connexions toutes les
  5 min (INFERENCE).
- Construction des métadonnées : un `Metadata` par requête, partagé par ses appels ; coût faible hors
  signature. Garder ce modèle (voir le piège OpenTelemetry en section 3).

---

## 5. OpenTelemetry

FAIT :
- `initTracing` active `getNodeAutoInstrumentations` avec seulement `fs` et `dns` désactivés
  (`monitoring/src/tracing.ts:37-51`, `:75-77`). Échantillonnage `parentbased_traceidratio` à 0,1
  (`deploy/apps/base/api-gateway/deployment.yaml`, `OTEL_TRACES_SAMPLER_ARG: "0.1"`).
- Modules actifs dans le profil : `instrumentation-http`, `-express`, `-router`, `-nestjs-core`,
  `-grpc`, `-runtime-node`, `sdk-metrics`, exportateurs OTLP.
- Le sampler est appelé **dans** `startSpan` (`sdk-trace-base Tracer.startSpan`) : chaque couche
  instrumentée crée son contexte, ses attributs d'entrée (`getIncomingRequestAttributes` pour http)
  et un span non enregistré même pour les 90 % de traces écartées. Les métriques HTTP
  (`sdk-metrics _record`, `hashAttributes`) sont enregistrées pour **toutes** les requêtes.
- Temps propre d'OpenTelemetry au profil du 08-11, rangé par instrumentation d'entrée : grpc 3,4 %,
  express 2,9 %, http 2,8 %, router 1,8 %, nestjs-core 1,35 %, export OTLP 1,3 %, métriques 0,5 %.
- `instrumentation-express` crée un span par couche de middleware (query, expressInit, json,
  urlencoded, cors, les deux middlewares d'auth, le handler), et `instrumentation-router` un de plus
  par couche du paquet `router` d'Express 5 : **environ 15 des 20 spans d'une requête** (INFERENCE,
  d'après la liste des couches de la section 2).
- La désactivation par variable d'environnement existe : `OTEL_NODE_DISABLED_INSTRUMENTATIONS`
  (`auto-instrumentations-node 0.75.0`, `build/src/utils.js:135-157` et `:191-198`, version
  confirmée dans `api-gateway/yarn.lock`). La configuration programmatique `enabled` est prioritaire,
  et `tracing.ts` ne la fixe pas pour ces modules.

Options :
- **O1. `OTEL_NODE_DISABLED_INSTRUMENTATIONS=express,router` sur la gateway.** PR `deploy` seule.
  On garde le span racine HTTP, le span du handler Nest et les spans clients gRPC (indispensables :
  ce sont eux qui propagent `traceparent`, dont dépend l'échantillonnage parent des `ms-*`).
  Gain (INFERENCE) : à 10 % d'échantillonnage, la part express + router passe d'environ 4,7 % à
  2,5 à 3,5 % du temps occupé ; on récupère cela plus le GC associé : **3 à 5 % de la gateway**.
  Risque : on perd la durée par middleware dans Datadog (peu utile ici). Effort : 15 min.
  Variante : `ignoreLayersType: ['middleware']` dans `buildInstrumentationConfig` (PR `npm-packages`).
- **O2. `runtime-node`** : 0,05 % propre plus l'observateur GC (`perf/observe`, environ 1 % inclusif,
  avec un appel à `deprecate` à chaque événement GC). Si Datadog collecte déjà les métriques du
  runtime, l'ajouter à la liste O1. Gain faible.
- **O3. Ne pas toucher `http` ni `grpc`.** Ce sont les deux qui portent la propagation.
  Pour réduire leur coût : `ignoreIncomingRequestHook` sur les sondes, mais les sondes sont TCP
  (pas de requête HTTP), donc rien à gagner ici.

---

## 6. Runtime Node

- **N1. Keep-alive HTTP derrière Traefik.** FAIT : aucun réglage `keepAliveTimeout` /
  `headersTimeout` dans `api-gateway/src` ; aucun `serversTransport` / `idleConnTimeout` dans
  `deploy` (git grep `origin/main`). Le défaut de Node est 5 s ; celui de Traefik pour les connexions
  vers les backends est 90 s (NON VERIFIE pour la version déployée). Node ferme donc les connexions
  inactives bien avant Traefik : reconnexions TCP et risque de 502 sur la course de fermeture.
  Correctif : `server.keepAliveTimeout = 95_000`, `headersTimeout = 96_000` après `app.listen`
  (`main.ts:83`). Gain CPU : faible à modéré selon le taux de reconnexion (NON VERIFIE ; à mesurer
  par le nombre de connexions ouvertes par seconde côté pod). Effort S, risque faible.
- **N2. Express vers Fastify.** Gain (INFERENCE) : routeur en arbre au lieu de 150 couches
  parcourues, objets requête et réponse plus légers, moins de couches à instrumenter : 5 à 10 % du
  CPU de la gateway ; davantage avec une sérialisation par schéma (`fast-json-stringify`), ce qui
  demande des schémas de réponse. Coût : L. Risques : `query parser` étendu à reproduire
  (`querystringParser` avec `qs`), middlewares Express (`app.use` passe par `@fastify/middie`),
  proxy WebSocket (`http-proxy-middleware` et l'`upgrade` lu via `HttpAdapterHost`,
  `ws-proxy.middleware.ts`), Scalar (option Fastify), tests E2E qui montent l'app Express en mémoire,
  instrumentation OTel différente (`@fastify/otel`). À garder pour après les gains peu chers, et
  seulement si la gateway reste au-dessus de 25 % du CPU du noeud (chapitre 02, section 10).
- **N3. Mode cluster** : inutile, l'HPA multiplie les pods.
- **N4. `--max-semi-space-size=16`** : déjà déployé (`deploy#71`) ; sa porte (GC sous 10 %) n'est pas
  encore mesurée.

---

## 7. Ce qui alimente le GC

Aucun profil d'allocation n'existe ; tout ce qui suit est **INFERENCE** classée par volume probable :
1. Spans et contextes OpenTelemetry (un contexte et un span non enregistré par couche, attributs,
   fermetures liées par `_bindFunction`) : O1 en retire la majorité.
2. Messages protobuf décodés avec `defaults: true` et `longs: String`, puis recopiés par spread dans
   les DTO (`event.dto.ts:88-92`) : deux copies complètes de chaque événement d'une page.
3. `JSON.stringify` de la réponse (chaîne de quelques dizaines de Ko pour 20 événements) puis le
   tampon d'écriture.
4. JWT : décodage base64, `structuredClone` de la charge utile, chaîne de 600 octets et plus,
   tampons webcrypto : J1 et J2 en retirent l'essentiel.
5. Listes d'exclusion (jusqu'à 2 000 chaînes UUID, filtrées par `filter`, recopiées dans la requête
   `SearchEvents`).
6. rxjs : un `Observable`, un `from`, un `switchMap` et un `firstValueFrom` par requête et par appel.
7. En-têtes HTTP/2 des appels gRPC (`toHeaderObject`, `fromHttp2Headers`).

**Mesure à faire** : ajouter à `capture-cpu-profile.mjs` (skill `volontariapp-load-ramp`) un mode
`HeapProfiler.startSampling({ samplingInterval: 32768 })` puis `HeapProfiler.stopSampling` pour
écrire un `.heapprofile` lisible dans DevTools. Sans cela, l'ordre ci-dessus reste une hypothèse.

---

## 8. Toutes les propositions

Gains en % du CPU de la gateway (fil principal + pool de threads), à 225 req/s, INFERENCE sauf
mention. « STOP » = changement `npm-packages` à publier avant les consommateurs.

| # | Quoi | Où | Gain CPU gateway | Gain latence | Effort | Risque | STOP |
| :--- | :--- | :--- | ---: | :--- | :--- | :--- | :--- |
| J1 | Jeton interne réutilisé 60 s | `auth/src/services/grpc-metadata.helper.ts:13-19` | 7 à 8 % | -0,6 à -1 ms par requête ; HPACK sur chaque appel | S-M | revue sécurité | oui |
| J2 | Cache des jetons d'accès vérifiés | `auth/src/guards/access-token.guard.ts:47` | 2 à 4 % | -0,1 ms | S | faible (pas de révocation aujourd'hui) | oui |
| J3 | Cache des jetons internes vérifiés dans les `ms-*` | `auth/src/guards/grpc-internal.guard.ts:30` | 0 (gain dans ms-social, jusqu'à 4,5 %) | faible | S | faible | oui |
| O1 | Désactiver OTel `express,router` | `deploy/apps/base/api-gateway/deployment.yaml` (env) | 3 à 5 % | faible | 15 min | perte des spans de middleware | non |
| C2 | Cache des exclusions 5 s (déjà au plan) | `event-social-filter.service.ts:101-120` | faible à la gateway | **un saut ms-social + Neo4j en moins sur 40 % du trafic** | M | décision produit | non |
| L1 | Logs `info` des routes chaudes en `debug` | `event.query-controller.ts:57`, `post.query-controller.ts:80`, `user.query-controller.ts:38` | 0,5 à 1,5 % | faible | XS | aucun | non |
| E1 | `etag` et `x-powered-by` désactivés | `main.ts` (après `:59`) | 0,5 à 1 % | faible | XS | aucun 304 utilisé par nativapp | non |
| N1 | `keepAliveTimeout` 95 s | `main.ts:83` | 0 à 2 % (NON VERIFIE) | moins de reconnexions, moins de 502 | XS | faible | non |
| G1 | Échéances gRPC sur les routes chaudes | contrôleurs + `grpc.types.ts:4-8` | 0 en régime normal | **meilleure tenue en surcharge** | S | mapping 503/504 | non |
| M1 | `RefreshTokenMiddleware` limité à la route de rafraîchissement | `main.ts:78` | moins de 0,5 % | nul | XS | corrige aussi le jeton d'accès rangé comme refresh | non |
| P1 | Cache du `EventDTO` construit dans `EventLookupService` | `event-lookup.service.ts:78-85` | moins de 1 % | nul | XS | faible | non |
| U1 | `isUUID` remplacé par un test de chaîne vide | `event-social-filter.service.ts:129` | moins de 1 % | -0,1 à -0,3 ms pour les gros comptes | XS | ms-event revalide | non |
| S1 | Scalar désactivé en production (ou une seule doc) | `main.ts:69` | moins de 0,5 % + mémoire | nul | XS | perte de la doc publique | non |
| N2 | Adaptateur Fastify | toute la gateway | 5 à 10 % | faible | L | élevé (ws-proxy, E2E, qs) | non |
| G2 | `defaults: false` au chargement des protos | `contracts-nest/src/grpc.helpers.ts:116-123` | quelques % | faible | M | élevé | oui |
| J4 | ES256 / EdDSA | `auth` + clés | négatif au total avec J1 | nul | M | rotation de clés | oui |

Ordre de grandeur du total des leviers peu chers (J1, J2, O1, L1, E1) : **15 à 20 % du CPU de la
gateway**, soit 0,4 à 0,5 vCPU à 225 req/s, environ 5 à 6 % du noeud (INFERENCE). C'est de l'ordre
des « environ 10 % de CPU par requête » qui manquent pour 300 req/s (chapitre 04, 4.4), à condition
d'ajouter J3 et C2 côté ms-social.

---

## 9. Top 5 classé

1. **J1 + J2 (+ J3) : un cache de jetons dans `@volontariapp/auth`.** Plus gros gain de CPU
   gateway (9 à 12 %), retire la signature RSA du chemin critique, et débloque J3 qui soulage
   ms-social, le service le plus chargé. STOP et revue de sécurité.
2. **O1 : `OTEL_NODE_DISABLED_INSTRUMENTATIONS=express,router`.** 3 à 5 % pour une ligne de `deploy`,
   sans code ni publication. À étendre aux `ms-*` après mesure si leurs profils montrent le même motif.
3. **C2 : cache des exclusions 5 s.** Seul levier qui retire un saut gRPC en série sur la route la
   plus fréquente ; gain surtout dans ms-social et Neo4j. Bloqué par la décision produit.
4. **L1 + E1 + N1 + M1 : réglages Express et journaux de la gateway**, une seule PR `api-gateway`,
   1,5 à 4 % en tout, risque quasi nul.
5. **G1 : échéances gRPC** : pas de CPU en régime normal, mais c'est ce qui empêche une surcharge à
   275 req/s de se transformer en effondrement (requêtes inutiles annulées dans les `ms-*`).

Fastify (N2) n'entre pas dans le top 5 : gain comparable à O1 + L1 + E1 pour un coût et un risque
bien plus grands.

## 10. Ordre suggéré des PR

1. **Mesure** : profil CPU propre à 225 req/s (les fichiers `*-225.cpuprofile` actuels sont
   inutilisables, section 0) et profil d'allocation (section 7). Sert aussi de porte à `deploy#71`.
2. **`deploy`** : O1 (une phase, une mesure : rampe à 225 et 250, profil).
3. **`api-gateway`** : L1, E1, N1, M1 dans une PR ; G1 dans une seconde PR (comportement d'erreur
   différent, à relire à part).
4. **`npm-packages` (`auth`)** : J1 + J2 + J3, changeset, **arrêt**, publication par la CI, levée du
   verrou, puis montée de `@volontariapp/auth` dans `api-gateway` et dans les `ms-*`
   (une PR par repo).
5. **`api-gateway`** : C2 si la décision produit est prise, avec les compteurs de cache de C1.
6. Seulement si la gateway dépasse encore 25 % du CPU du noeud : étude Fastify (prototype jetable
   sur les quatre routes chaudes).

## 11. Couverture et limites

- Recherches d'absence : `git grep` sur `origin/main` de chaque repo nommé, chemins `src/`
  (gateway, `ms-*`, `ws-service`, `nativapp`) ou `packages/auth/src`, `packages/shared/src`
  (`npm-packages`), et `deploy` entier. Les runners (`workers-runners`, `post-processors-runner`)
  n'ont pas été cherchés pour `jti`.
- `analyze_grpc` n'a pas résolu `GetSearchExclusions` ni `CountEventParticipants` (section 1) ; la
  séquence de ces appels vient de la lecture du code.
- Pas d'accès au cluster : tailles réelles des réponses, taux de cache, taux de reconnexion et taille
  de la clé RSA sont NON VERIFIES.
