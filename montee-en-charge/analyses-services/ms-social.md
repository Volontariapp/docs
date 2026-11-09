# ms-social : réduire le CPU par requête

Analyse du 2026-11-09, lecture seule. Code lu sur `origin/main` (ms-social `411781c`, qui est aussi l'image déployée `sha-411781c`) et dans les tarballs npm des versions résolues par `ms-social/yarn.lock` (`domain-social` 0.19.2, `auth` 3.3.29, `bridge` 1.0.13, `bridge-nest` 0.3.23, `logger` 0.5.0, `monitoring` 2.5.1, `validation-nest` 0.1.5, `contracts-nest` 3.5.0, `neo4j-driver(-core, -bolt-connection)` 6.3.0, `jose` 6.2.16). Le `node_modules` local de ms-social est périmé (`domain-social` 0.15.0, `auth` 3.3.24...) et n'a pas servi, sauf pour `@opentelemetry/auto-instrumentations-node`, qui a la même version (0.75.0) que le lockfile.

Conventions : **FAIT** = ligne lue ou sortie d'outil de cette session, avec `fichier:ligne` ; **INFERENCE** = déduction non vérifiée ; **NON VERIFIE** = hypothèse à confirmer par une mesure.

## 0. Avertissement sur le profil fourni

- FAIT : `/Users/victoragahi/Developer/meta/ms-social-225.cpuprofile` ne contient pas le régime établi à 225 req/s. 247 nœuds seulement ; 97,8 % du temps occupé est dans `_kill`, pile `_kill <- kill (node:internal/process/per_thread:253) <- cleanup (@nestjs/core/nest-application-context.js:191) <- processTicksAndRejections`. Le pod était en train de s'arrêter (signal d'arrêt, puis `process.kill` rejoué par Nest) pendant la capture.
- FAIT (précisé par l'orchestrateur) : le fichier a été écrasé à 10:06:45Z par une seconde capture prise pendant la suppression du pod. Le résumé utilisé ici (occupé 70 % sur 30,4 s, GC 14,5 %, autres dépendances 22,3 % dont `captureStacktrace` + `defaultPrepareStackTrace` 3,7 %, `writeBuffer` 5 %, `writeUtf8String` 4 %, jose 4,5 %, class-validator 2,5 %, logger + console 3,5 %, protobuf 1,2 %) a été lu dans le fichier **original**, valide, à 10:04Z : il est traité comme FAIT. Le fichier actuel est inexploitable.
- FAIT : même constat de capture d'arrêt pour `ms-event-225.cpuprofile` (même pile) ; `gateway-225.cpuprofile` est occupé à 9 % seulement, 190 nœuds.
- Conséquence : les pourcentages par famille sont des FAITS, mais le **temps inclusif par gestionnaire RPC ou par requête Cypher** n'a pas pu être calculé. Les gains rapportés à un RPC précis restent donc des INFERENCES.
- Action : refaire une capture de 30 s à 225 req/s sans supprimer ni redémarrer le pod pendant la capture, et ne pas réécrire un fichier existant (nom horodaté). Script d'agrégation inclusive prêt : `/private/tmp/claude-501/-Users-victoragahi-Developer-meta/a9f40403-efe3-4c69-84c2-d4eb6c9db0a0/scratchpad/inclusive-by-bucket.mjs` (attribue chaque échantillon au seau le plus spécifique de sa pile : capture de pile Neo4j, packstream, Record/Result, session/pool, jose, validation, logger, OpenTelemetry, protobuf, grpc-js, domain-social, code ms-social, Nest, GC). Limite : les piles asynchrones sont coupées à chaque `await`, donc le travail fait après la réponse Neo4j n'est pas rattaché au contrôleur ; c'est pourquoi le script raisonne par seau technique et non par RPC.

## 1. Ce que fait ms-social pour le mix de charge

### 1.1 Débits par pod (225 req/s, 2 réplicas, round_robin)

| Route du mix | req/s | Appel ms-social | Requêtes Cypher par appel | Par pod (INFERENCE) |
| :--- | :--- | :--- | :--- | :--- |
| events-list-app 40 % | 90 | `GetSearchExclusions` | 2 | 45 appels/s, 90 requêtes/s |
| events-list-app | | `CountEventParticipants` (cache 30 s gateway) | 1 | ratés du cache seulement, non mesuré |
| posts-list 30 % | 67,5 | `GetEventsRelatedToPosts` (via ms-post) | 1 | environ 6 appels/s (mesuré, donné dans la demande) |
| is-following 10 % | 22,5 | `getIsFollowing` | 1 | 11 appels/s |
| me 20 % | 45 | aucun appel ms-social trouvé (FAIT : `api-gateway/src/modules/user/controllers/queries/user/user.query-controller.ts:37-45` n'appelle que `userService.getUser` ; ce que fait ms-user ensuite n'a pas été suivi) | | |

- FAIT : le simulateur envoie les quatre drapeaux d'exclusion à chaque `events-list-app` (`traffic-simulator/src/load/load-request.ts:13-20`), la gateway appelle donc `GetSearchExclusions` sans cache (`api-gateway/src/modules/event/services/event-social-filter.service.ts:101-120`), et ms-social lance les deux requêtes (`npm-packages/packages/domain-social/src/repositories/neo4j-participation.repository.ts:333-356`).
- INFERENCE : `GetSearchExclusions` représente environ 70 % des RPC de ms-social et environ 84 % de ses requêtes Neo4j (90 sur environ 107 par seconde et par pod). C'est la cible principale.
- Contradiction à lever : la demande dit que "Getting events linked to 20 posts" est la ligne de log la plus fréquente (6/s par pod). Le calcul ci-dessus donne 45/s pour "Getting search exclusions for user: <uuid>". Explication probable (INFERENCE) : la ligne des posts a un texte constant, alors que celle des exclusions contient l'uuid de l'utilisateur, et un comptage par message exact la disperse. À vérifier dans Datadog en groupant par motif (ou par `rpc.method` des traces gRPC) avant de chiffrer quoi que ce soit.
- INFERENCE : 70 % d'un cœur pour environ 62 RPC/s donne environ 11 ms de CPU par RPC, ce qui est beaucoup pour des lectures par index qui renvoient des petites listes. Soit les listes d'exclusion sont longues (centaines d'ids, voir 1.3), soit le débit réel de RPC est plus haut que ce calcul. La nouvelle capture et le décompte par méthode trancheront.

### 1.2 Chemin d'un appel, de bout en bout

Pour chaque RPC, dans l'ordre (FAIT sauf mention) :

1. grpc-js : trames HTTP/2, métadonnées, décodage protobuf via proto-loader avec `defaults: true`, `longs: String`, `enums: String` (`contracts-nest` 3.5.0 `dist/grpc.helpers.js:88-98`).
2. OpenTelemetry : toutes les instrumentations automatiques sauf `fs` et `dns` (`monitoring` 2.5.1 `dist/tracing.js:13-27, 39-41`), traces échantillonnées à 10 % (`deploy/apps/base/ms-social/deployment.yaml`, `OTEL_TRACES_SAMPLER_ARG=0.1`). Pas d'instrumentation Neo4j dans le paquet 0.75.0 (FAIT : `neo4j` absent de `auto-instrumentations-node/build/src/utils.js`).
3. `GrpcInternalGuard` global (`ms-social/src/app.module.ts:44-47`) : `jose.jwtVerify` RS256 à chaque appel (`auth` 3.3.29 `dist/guards/grpc-internal.guard.js:21-43`, `dist/services/jwt.service.js:164-178`).
4. `GrpcValidationPipe` global (`ms-social/src/app.module.ts:52-58`) : copie récursive du payload (`processData`), puis `ValidationPipe` de Nest avec `transform`, `whitelist`, `enableImplicitConversion` (`validation-nest` 0.1.5 `dist/pipes/grpc-validation.pipe.js:14-35`). `GetEventsRelatedToPosts` reçoit un type littéral `{ postIds: string[] }` (`ms-social/src/modules/event-post-link/controllers/event-post-link.query.controller.ts:40`), donc pas de class-validator pour lui (INFERENCE : métatype `Object`, ignoré par `ValidationPipe`).
5. Une ligne `info` par appel : `participation.query.controller.ts:180`, `event-post-link.query.controller.ts:42`, `relationship.query.controller.ts:143`. Chaque ligne fait : `new Date().toISOString()`, trois expressions régulières de masquage sur le message, une copie masquée des métadonnées, `getTraceFields()` avec deux conversions `BigInt`, `JSON.stringify`, puis `console.log` sur la sortie standard (`logger` 0.5.0 `dist/logger.js:60-87`, `dist/masking.js`, `dist/trace-context.js`). Production en `info` (`deployment.yaml`, `LOGGER_LEVEL=info`).
6. Service et dépôt `domain-social` : value objects, un `session()` par requête Cypher, `session.run` en auto-commit, `session.close()` (`domain-social/src/repositories/base/neo4j-base.repository.ts:23-37`).
7. Driver Neo4j 6.3.0 par requête : acquisition dans le pool, création d'un `Result` qui **capture une pile à chaque fois** (`neo4j-driver-core` 6.3.0 `lib/result.js:100-106` : `new Error('')` puis lecture de `error.stack`, appelée sans condition dans le constructeur, `lib/result.js:141`), encodage packstream RUN+PULL, écriture socket, décodage de chaque ligne en `Record`.
8. Encodage protobuf de la réponse, écriture HTTP/2.

### 1.3 Les requêtes Cypher chaudes

| RPC | Cypher (FAIT) | Index (INFERENCE, NON VERIFIE en base) | Taille du résultat |
| :--- | :--- | :--- | :--- |
| `GetSearchExclusions`, partie événements | `MATCH (:SocialUser {userId: $userId})-[:CREATED\|PARTICIPATE\|WISH_TO_PARTICIPATE]->(e:SocialEvent) WHERE e.eventId IS NOT NULL AND e.eventId <> '' WITH DISTINCT e.eventId AS id RETURN id ORDER BY id LIMIT $limit` (`neo4j-participation.repository.ts:339-342`) | ancre par la contrainte unique `social_user_user_id` (`ms-social/src/providers/database/neo4j-schema.initializer.ts:6`), puis expansion des relations de l'utilisateur | une **ligne par id**, jusqu'à 1001 |
| `GetSearchExclusions`, partie blocages | `MATCH (:SocialUser {userId: $userId})-[:BLOCK]-(u:SocialUser) ... RETURN id ORDER BY id LIMIT $limit` (`:348-351`) | même ancre | une ligne par id, jusqu'à 1001 |
| `GetEventsRelatedToPosts` | `UNWIND $postIds AS id MATCH (p:SocialPost {postId: id})-[:LINK_TO_EVENT]->(e:SocialEvent) RETURN p.postId, e.eventId` (`neo4j-event-post-link.repository.ts:68-77`) | contrainte `social_post_post_id` (`neo4j-schema.initializer.ts:7`) | au plus 20 lignes |
| `getIsFollowing` | `MATCH (:SocialUser {userId: $fromId})-[r:FOLLOW]->(:SocialUser {userId: $toId}) RETURN r` (`neo4j-relationship.repository.ts:139-144`) | contrainte `social_user_user_id` | 0 ou 1 ligne, mais renvoie la **relation entière** (propriétés comprises) alors que seul un booléen sert |
| `CountEventParticipants` | `UNWIND $eventIds ... OPTIONAL MATCH (u:SocialUser)-[:PARTICIPATE]->(:SocialEvent {eventId: id}) RETURN id, count(u)` (`neo4j-participation.repository.ts:238-242`) | contrainte `social_event_event_id` (`:8`) | une ligne par événement, 100 au plus |

- Les contraintes sont créées au démarrage, en `IF NOT EXISTS`, et une erreur est seulement journalisée (`neo4j-schema.initializer.ts:30-36`) : leur présence en production est NON VERIFIEE (`SHOW CONSTRAINTS` à lancer par Victor).
- Taille réelle des listes d'exclusion : NON VERIFIEE. C'est la donnée qui décide du poids de la proposition P2. Requête en lecture seule à lancer par Victor sur la base de production :
  ```cypher
  MATCH (u:SocialUser)
  CALL { WITH u MATCH (u)-[:CREATED|PARTICIPATE|WISH_TO_PARTICIPATE]->(e:SocialEvent) RETURN count(DISTINCT e) AS ev }
  CALL { WITH u MATCH (u)-[:BLOCK]-(b:SocialUser) RETURN count(DISTINCT b) AS bl }
  RETURN percentileDisc(ev, 0.5) AS ev_p50, percentileDisc(ev, 0.95) AS ev_p95, max(ev) AS ev_max,
         percentileDisc(bl, 0.95) AS bl_p95, max(bl) AS bl_max
  ```

### 1.4 Sessions, transactions, options du driver

- FAIT : le driver est créé avec `neo4j.driver(url, auth.basic(...), this.setup.config)` (`bridge` 1.0.13 `dist/providers/neo4j.provider.js`), et ms-social ne passe aucune `config` (`ms-social/src/providers/database/database.module.ts:23-26`) : pool par défaut, entiers 64 bits en objets `Integer`, aucun réglage de journalisation ni de notifications.
- FAIT : URL `bolt://` (connexion directe, pas de table de routage) : `ms-social/config/default.config.json` (`"scheme": "bolt"`), et le déploiement ne surcharge pas `NEO4J_SCHEME` (`deploy/apps/base/ms-social/deployment.yaml`, variables lues).
- FAIT : `session()` sans `defaultAccessMode` ni `database` (`neo4j-base.repository.ts:28, 59, 81-82`). En `bolt://` sur un seul serveur, le mode n'a pas d'effet sur le CPU (INFERENCE) ; le passer en `READ` est une correction pour un futur cluster, pas un gain.
- FAIT : lectures en auto-commit (`session.run`), écritures en `executeWrite` (`:58-67`). L'auto-commit est le chemin le moins bavard (RUN+PULL, sans BEGIN/COMMIT) : passer les lectures à `executeRead` coûterait plus de messages, donc **ne pas le faire** pour le CPU (INFERENCE fondée sur le protocole Bolt).
- FAIT : `disableLosslessIntegers` n'est pas utilisé ; mais les requêtes chaudes ne renvoient que des chaînes, sauf `count(u)` de `CountEventParticipants`, converti par `toSafeInt` (`neo4j-base.repository.ts:11-18`). Gain attendu nul (INFERENCE).
- FAIT : aucune option du driver 6.3.0 ne désactive la capture de pile du `Result` : l'appel est inconditionnel (`lib/result.js:141`). 6.3.0 est aussi la dernière version publiée de `neo4j-driver-core` (FAIT : `npm view neo4j-driver-core version` = 6.3.0, même code dans le tarball). Le seul levier sans patch est de **faire moins de requêtes**.
- `readPaginated` ouvre deux sessions par appel (données et total, `neo4j-base.repository.ts:80-105`) : pas sur le chemin chaud du mix, mais à retenir pour `getMyBlocks` / `getWhoBlockedMe` (route du fil classé).

## 2. Propositions

Chaque gain est rapporté au CPU de ms-social à 225 req/s. Les parts par famille sont des FAITS (profil original) ; leur répartition entre RPC est une INFERENCE tant que le profil n'est pas refait.

### P1. Cache des exclusions à la gateway (étape C2 du plan 05)

- **Quoi** : garder `GetSearchExclusions` par utilisateur quelques secondes à la gateway, comme prévu au chapitre 05 ; option B si le produit refuse un blocage différé (seules les listes créés / participés / souhaités en cache, blocages relus à chaque fois).
- **Où** : `api-gateway/src/modules/event/services/event-social-filter.service.ts:101-120`.
- **Pourquoi c'est le premier** : environ 70 % des RPC de ms-social et 84 % de ses requêtes Neo4j viennent de cet appel (INFERENCE, 1.1). Avec un taux de réussite h, ms-social perd environ h x 70 % de ses appels. h dépend de la fréquence de retour d'un même utilisateur dans la fenêtre : avec le simulateur (1 000 acteurs pour 90 req/s d'events-list-app, soit environ un retour toutes les 11 s par acteur), une fenêtre de 5 s donne un h faible, autour de 0,3 à 0,4 (INFERENCE, distribution des acteurs NON VERIFIEE) ; 30 s le monterait vers 0,9.
- **Gain** : 20 à 60 % du CPU de ms-social selon la durée choisie, plus le même ordre sur Neo4j (0,6 vCPU à 250 req/s) et une partie de la gateway (moins d'appels gRPC, moins de signatures si P4 n'est pas fait). Le plus gros levier, de loin.
- **Effort** : une demi-journée (le cache borné et ses compteurs existent déjà à la gateway, `api-gateway#117`).
- **Risque** : produit (blocage visible jusqu'à N s plus tard sur une gateway qui n'a pas traité le blocage) ; option B l'annule mais ne garde qu'environ la moitié du gain (une requête Cypher sur deux reste, plus l'aller-retour gRPC complet).
- **npm-packages** : non. **Pourquoi pas dans ms-social** : un cache côté ms-social économise Neo4j et le driver, mais pas le guard, la validation, les logs, protobuf et HTTP/2 des deux côtés ; et l'invalidation aurait le même problème (2 réplicas, plus les écritures faites par le post-processor). La gateway est le bon endroit.

### P2. Une seule requête Cypher pour `GetSearchExclusions`, résultats agrégés en listes

- **Quoi** : remplacer les deux `this.read(...)` en parallèle (`neo4j-participation.repository.ts:333-356`) par une requête unique qui renvoie **une seule ligne** avec deux listes, par exemple :
  ```cypher
  CALL {
    MATCH (:SocialUser {userId: $userId})-[:CREATED|PARTICIPATE|WISH_TO_PARTICIPATE]->(e:SocialEvent)
    WHERE e.eventId IS NOT NULL AND e.eventId <> ''
    WITH DISTINCT e.eventId AS id ORDER BY id LIMIT $limit
    RETURN collect(id) AS eventIds
  }
  CALL {
    MATCH (:SocialUser {userId: $userId})-[:BLOCK]-(u:SocialUser)
    WHERE u.userId IS NOT NULL AND u.userId <> ''
    WITH DISTINCT u.userId AS id ORDER BY id LIMIT $limit
    RETURN collect(id) AS userIds
  }
  RETURN eventIds, userIds
  ```
  Le sous-bloc est omis (ou remplacé par `RETURN [] AS ...`) quand le drapeau correspondant est faux, comme aujourd'hui. Un agrégat sans clé renvoie toujours une ligne, même si l'utilisateur n'a aucune relation (comportement Cypher standard ; à couvrir par le test d'intégration). La syntaxe `CALL { ... }` sans import est acceptée en Neo4j 5 ; la version du serveur est NON VERIFIEE (à lire avant d'écrire la requête, la forme `CALL () { ... }` est la forme récente).
- **Gain côté ms-social** : par appel, une session, un `Result` (donc une capture de pile), une acquisition de pool, un RUN+PULL et un décodage de réponse en moins ; et une seule ligne au lieu de jusqu'à 2 002 `Record` (chaque ligne crée aujourd'hui un `Record`, un tableau de champs et un appel au mappeur : `neo4j-driver-bolt-connection` 6.3.0 `lib/bolt/stream-observers.js:142`, `neo4j-base.repository.ts:31`). La part "dépendances" (22,3 %, surtout le driver) et une partie du GC (14,5 %) et de `writeBuffer` (5 %) suivent le nombre de requêtes et de lignes. Ordre de grandeur : 5 à 10 % du CPU de ms-social si les listes sont courtes, davantage si elles comptent des centaines d'ids (INFERENCE, dépend de la requête de 1.3).
- **Gain côté Neo4j** : 45 transactions par seconde et par pod en moins à 225 req/s, soit environ 40 % des requêtes que ms-social envoie (INFERENCE, 1.1) ; le travail de parcours ne change pas, le coût fixe par transaction (analyse Bolt, recherche dans le cache de plans, ouverture et fermeture de transaction) disparaît pour moitié.
- **Effort** : 2 à 3 h avec les tests d'intégration existants de `domain-social` (`src/test/neo4j-driver.ts`, `src/test/setup.ts`).
- **Risque** : faible ; le contrat `SearchExclusionsVO` et la sémantique de troncature (`maxIds + 1`) restent identiques. Vérifier le plan avec `PROFILE` sur un utilisateur réel.
- **npm-packages** : **oui** (`domain-social`). Règle du STOP : build, test, changeset, PR, publication par la CI, puis seulement `yarn up @volontariapp/domain-social` dans ms-social.

### P3. Lignes `info` par RPC passées en `debug` sur les lectures chaudes (étape 2.4 non livrée)

- **Quoi** : `this.logger.log(...)` devient `this.logger.debug(...)` pour les RPC de lecture à fort débit : `participation.query.controller.ts:180` (`getSearchExclusions`) et `:223` (`countEventParticipants`), `event-post-link.query.controller.ts:32, 42`, `relationship.query.controller.ts:143`. Avec `LOGGER_LEVEL=info`, `print` sort dès la première ligne (`logger` 0.5.0 `dist/logger.js:61-63`) ; la chaîne du message est encore construite par l'appelant, ce qui est négligeable.
- **Gain** : la famille logger + console (3,5 %) disparaît presque pour ces RPC ; `writeUtf8String` (4 %) est très probablement l'écriture des journaux sur la sortie standard (INFERENCE : c'est l'écriture de chaînes sur un flux libuv, alors que grpc-js et le driver Neo4j écrivent des `Buffer`, comptés dans `writeBuffer`). Total attendu : 4 à 7 % du CPU de ms-social, plus moins d'allocations (objet `payload`, copie masquée, chaîne JSON), donc un peu de GC.
- **Effort** : 30 min, ms-social seul.
- **Risque** : moins de traçabilité appel par appel. La règle "chaque action tracée" du projet reste couverte par les spans gRPC (10 %), les métriques gRPC d'OpenTelemetry et les logs `error` / `warn`, qui restent ; à valider par Victor, puisque la règle d'or 6 demande une trace de chaque action. Option intermédiaire : garder `info` sur les commandes, `debug` sur les lectures.
- **npm-packages** : non.

### P4. Vérification du jeton interne : réutilisation à la gateway, cache des jetons vérifiés dans les ms-* (étape C3)

- **Constat** : FAIT, chaque requête HTTP signe un jeton neuf (`auth` 3.3.29 `dist/interceptors/grpc-internal.interceptor.js:28`) avec un `jti` aléatoire (`dist/services/jwt.service.js:159`, `setJti(crypto.randomUUID())`). Deux requêtes ne portent donc jamais le même jeton.
- **Conséquence** : un cache de jetons vérifiés **dans ms-social seul** ne gagne presque rien (réussite seulement quand une même requête HTTP appelle ms-social plusieurs fois : `GetSearchExclusions` puis un raté de `CountEventParticipants`). Il ne sert qu'avec la réutilisation du jeton à la gateway pendant quelques secondes par utilisateur.
- **Quoi** : (a) gateway : garder le jeton interne par (utilisateur, rôle) jusqu'à peu avant son `exp` ; (b) `GrpcInternalGuard` : LRU borné, clé = jeton complet (ou son SHA-256), valeur = `AuthUser`, durée de vie = min(`exp` du jeton, quelques secondes), jamais d'entrée pour un échec.
- **Gain** : jusqu'à la part de jose dans ms-social (4,5 %), plus la signature RS256 à la gateway (environ 1 ms par requête selon le chapitre 04). Le travail de `subtle.verify` fait hors du fil principal n'apparaît pas dans le profil (INFERENCE sur jose 6, qui passe par WebCrypto), donc le gain réel en CPU du conteneur peut être un peu plus grand.
- **Sécurité** : le cache ne prolonge pas la validité (borné par `exp`) ; un jeton réutilisé n'est pas plus dangereux qu'aujourd'hui tant que sa durée reste courte, puisqu'il n'existe pas de révocation des jetons internes ; la seule perte est l'unicité par requête (`jti`) si un jour on s'en sert pour corréler ou rejouer. Revue de sécurité à faire, comme le dit le plan 05.
- **Effort** : 1 jour avec la revue. **npm-packages** : **oui** (`auth`), STOP puis gateway et les `ms-*`.

### P5. Instrumentations OpenTelemetry inutiles désactivées par variable d'environnement

- **Quoi** : ajouter `OTEL_NODE_DISABLED_INSTRUMENTATIONS` au déploiement de ms-social, par exemple `nestjs-core,net,express`, en gardant `grpc`, `http`, `pg`, `runtime-node`. FAIT : la version 0.75.0 lit cette variable et préfixe chaque nom par `@opentelemetry/instrumentation-` (`auto-instrumentations-node/build/src/utils.js:166-198`). Que la configuration explicite de `monitoring` (`fs`, `dns`) ne l'écrase pas est NON VERIFIE : regarder la liste des instrumentations au démarrage en préproduction.
- **Gain** : NON VERIFIE ; `nestjs-core` crée un span (non enregistré à 90 %) par gestionnaire, `net` instrumente chaque socket. Probablement 1 à 3 % (INFERENCE). À lire dans le nouveau profil (seau "OpenTelemetry" du script).
- **Effort** : 15 min, PR `deploy` seule. **Risque** : moins de spans Nest dans Datadog (le span gRPC serveur reste). **npm-packages** : non.

### P6. Petites corrections des requêtes et du mapping

- `relationshipExists` : `RETURN r` devient `RETURN true AS found LIMIT 1` (`neo4j-relationship.repository.ts:140-141`) : la relation et ses propriétés ne sont plus sérialisées puis décodées. Gain faible (11 appels/s par pod), surtout côté Neo4j. npm-packages : oui, à grouper avec P2.
- `getEventsRelatedToPosts` : passe par `SocialPostMapper.toEntity` puis `toModel` puis `new PostId` pour chaque id (`event-post-link.service.ts:68`, `neo4j-event-post-link.repository.ts:66`) : allocations inutiles mais petites (20 ids, 6 appels/s). À grouper avec P2 seulement si c'est gratuit.
- `session({ defaultAccessMode: READ })` dans `read()` : gain CPU nul aujourd'hui (FAIT : `bolt://`), utile pour un futur cluster. À grouper avec P2.

### P7. Capture de pile du driver Neo4j (à ne faire qu'en dernier recours)

- **Constat** : 3,7 % dans `captureStacktrace` + `defaultPrepareStackTrace` (chiffre fourni), code inconditionnel (FAIT, `lib/result.js:100-106, 141`), aucune version plus récente.
- **Options** : (a) P1 et P2 réduisent ce coût en proportion des requêtes supprimées, sans rien toucher : c'est la voie recommandée ; (b) `yarn patch` de `neo4j-driver-core` pour rendre la capture paresseuse : gain restant de 1 à 2 % après P2, coût de maintenance à chaque mise à jour du driver ; (c) baisser `Error.stackTraceLimit` globalement : rejeté, cela appauvrit toutes les piles d'erreur du service ; (d) ouvrir un ticket chez Neo4j pour une option de configuration.
- **npm-packages** : non pour (b) (patch dans ms-social), mais à éviter.

### P8. Validation et GC

- class-validator (2,5 %) : le DTO chaud `GetSearchExclusionsQueryDTO` n'a que quatre booléens (`ms-social/src/modules/participation/dto/participation.query.dto.ts`). Retirer la validation globale serait contraire au playbook gRPC ; gain plafonné à environ 2 %. Ne rien faire.
- GC (14,5 %) : FAIT, `--max-semi-space-size=32` est déjà déployé (`deploy/apps/base/ms-social/deployment.yaml`, commentaire "13 a 15 % du temps occupé au profil du 2026-11-09"), donc le chiffre de 14,5 % date d'avant ce réglage (INFERENCE d'après le commentaire). La nouvelle capture dira ce qui reste. Les sources d'allocation que P2 et P3 suppriment : un `Record` et un tableau par ligne Neo4j, l'objet journal masqué et sa chaîne JSON, un `Result` et une `Error` par requête.

### P9. Caches à l'intérieur de ms-social : à ne pas faire maintenant

- `GetSearchExclusions` : voir P1 (la gateway économise plus, l'invalidation est la même).
- `getIsFollowing` : un cache casserait le bouton "suivre" juste après un clic, sur l'autre réplica ; 11 appels/s par pod : gain faible.
- `GetEventsRelatedToPosts` : lien posté une fois, retiré à la suppression du post ou de l'événement ; un LRU de 30 s serait sûr en pratique, mais 6 appels/s par pod et déjà un cache de 500 entrées à la gateway (`api-gateway#117`) : gain inférieur à 2 % (INFERENCE).
- `CountEventParticipants` : déjà en cache 30 s à la gateway.

## 3. Coûts côté Neo4j

- INFERENCE : environ 0,6 vCPU pour environ 110 à 140 requêtes/s venant de ms-social à 250 req/s, soit plusieurs ms de CPU serveur par requête : beaucoup pour des parcours depuis un index unique. Hypothèses à vérifier dans cet ordre : listes d'exclusion longues (requête de 1.3), contraintes absentes en production (`SHOW CONSTRAINTS`), coût fixe par transaction et GC de la JVM (métriques Neo4j dans Datadog si l'intégration est active : NON VERIFIE).
- P1 et P2 sont les deux seuls leviers qui réduisent Neo4j de façon nette ; P6 (`RETURN r`) un peu.

## 4. Classement

| Rang | Proposition | Gain CPU ms-social (INFERENCE) | Effort | Risque | npm-packages |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | P1 cache des exclusions à la gateway | 20 à 60 %, plus Neo4j | 0,5 j | produit (délai d'un blocage) | non |
| 2 | P2 une requête et des listes pour `GetSearchExclusions` (+ P6) | 5 à 10 %, plus si listes longues ; Neo4j environ -40 % de transactions | 2 à 3 h | faible | oui (`domain-social`) |
| 3 | P3 logs `info` des lectures en `debug` | 4 à 7 % | 30 min | traçabilité, à valider | non |
| 4 | P4 jeton réutilisé + cache des jetons vérifiés | jusqu'à 4,5 %, plus la gateway | 1 j | sécurité, revue | oui (`auth`) |
| 5 | P5 instrumentations désactivées | 1 à 3 % (NON VERIFIE) | 15 min | faible | non |

Hors classement : P7 (patch du driver, en dernier recours), P8 (rien à faire), P9 (pas de cache dans ms-social).

## 5. Ordre des PR suggéré

0. **Mesure d'abord** : nouvelle capture de 30 s à 225 req/s (pod non supprimé pendant la capture), lue avec `analyze-cpuprofile.mjs` et `inclusive-by-bucket.mjs` ; décompte des RPC par méthode et par pod (Datadog, traces ou motifs de logs) ; requête de taille des listes de 1.3 ; `SHOW CONSTRAINTS`. Sans ces quatre chiffres, les gains ci-dessus restent des ordres de grandeur.
1. `ms-social` : P3 (30 min, indépendant, mesurable tout de suite).
2. `deploy` : P5 (15 min, indépendant ; à faire dans une fenêtre séparée de P3 pour mesurer chacun).
3. `npm-packages` : P2 + P6 dans `domain-social`, changeset ; **STOP** jusqu'à la publication par la CI.
4. `ms-social` : `yarn up @volontariapp/domain-social` vers la version publiée, puis mesure.
5. `api-gateway` : P1, après la décision produit A ou B (section 6 du chapitre 05).
6. `npm-packages` (`auth`) : P4, revue de sécurité ; **STOP** ; puis `api-gateway` et les `ms-*`.

## 6. Ce qui n'a pas été vérifié

- Profil : seul le résumé par famille du fichier original est disponible (section 0) ; le temps inclusif par gestionnaire demande une nouvelle capture.
- `analyze_grpc` (mesh-mcp) n'a pas trouvé `GetSearchExclusions` (0 définition, 0 client, 0 serveur) : index en génération 37, antérieur au RPC (FAIT : le handler existe, `participation.query.controller.ts:175-193`, commit `2d033fb`). Les appelants de ce RPC ont été lus directement dans `api-gateway` origin/main (`event-social-filter.service.ts:119`), pas dans toutes les racines : d'autres appelants éventuels sont **non déterminés**.
- `GetEventsRelatedToPosts` : `analyze_grpc` donne 1 serveur (ms-social) et 2 clients de service (`ms-post/src/modules/post/clients/social-event-post.query-client.ts:34`, `workers-runners/worker-ranking/src/clients/social-feed.client.ts:39`), sans appel littéral de méthode résolu ; l'appel de ms-post a été lu (`social-event-post.query-client.ts:74`, appelé depuis `post.query.controller.ts:94`).
- Ce que fait ms-user pour `GET /users/me` (appels éventuels vers ms-social) : non suivi.
- Version du serveur Neo4j, présence des contraintes, tailles des listes : NON VERIFIEES.
- Priorité entre la configuration explicite de `monitoring` et `OTEL_NODE_DISABLED_INSTRUMENTATIONS` : NON VERIFIEE.
