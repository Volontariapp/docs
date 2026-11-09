# ms-user : réduire le CPU par requête (analyse, 2026-11-09)

Analyse seule : aucun fichier modifié, aucune requête sur une base de production. Code lu sur `origin/main` (ms-user `57c4345`, qui est aussi l'image déployée `sha-57c4345` dans `deploy/apps/base/ms-user/deployment.yaml`), npm-packages `origin/main` (versions identiques au `yarn.lock` de ms-user : `domain-user` 2.17.12, `auth` 3.3.29, `crypto` 0.3.15, `database` 3.13.2, `logger` 0.5.0, `monitoring` 2.5.1), TypeORM 0.3.31 et `@opentelemetry/auto-instrumentations-node` 0.75.0 lus dans `ms-user/node_modules` (même version que le lockfile).

Conventions : **FAIT** = ligne lue ou sortie d'outil de cette session, avec `fichier:ligne`. **INFERENCE** = raisonnement non vérifié par une mesure. **NON VERIFIE** = hypothèse à tester.

**Avertissement principal : aucun profil CPU de ms-user n'existe.** Tous les gains ci-dessous sont estimés par lecture de code et par analogie avec les profils de `ms-social` et `ms-event` du 2026-11-09 (docs `montee-en-charge/04-resultats.md`, section 4.5). La section 7 donne la procédure qui les confirmerait ou les infirmerait.

---

## 1. Qui appelle ms-user sur le mélange de charge

### FAIT

- `analyze_grpc({ target: "volontariapp.user" })` (toutes les racines indexées de mesh-mcp) : 30 sites clients, **tous dans `api-gateway`** ; 25 handlers dans ms-user (19 `UserService`, 6 `BadgeService`).
- `analyze_grpc({ target: "GetUsersByIds" })` : 0 site client littéral dans les racines indexées.
- Contrôle ciblé `git grep` sur `origin/main` de chaque dépôt, motif `USER_SERVICE_NAME|UserServiceClient|getUsersByIds|GetUsersByIds` : aucun résultat hors tests dans `ms-event`, `ms-post`, `ms-social`, `ms-ranking`, `ms-storage`, `ws-service`, `post-processors-runner`, `workers-runners`, `outbox-runners`. `ms-event`, `ms-post` et `ms-social` déclarent un client `USER_PACKAGE` (`src/grpc/grpc-client.options.ts`) mais aucun fichier ne l'injecte (motif `USER_PACKAGE|UserService\b|BadgeService` sur `src`).
- Dans `api-gateway` (`origin/main`), `USER_PACKAGE` n'est injecté que dans les modules `user`, `system` (seed) et `social/relationship.query-controller.ts` (routes `follows` et `followers` seulement, lignes 44 à 61). Les modules `event` et `post` ne l'importent pas.
- Chemins du mélange (`traffic-simulator/src/load/load-request.ts`, `buildTarget`) : `events-list-app` = `GET /events?...`, `posts-list` = `GET /posts?...`, `me` = `GET /users/me`, `is-following` = `GET /social/users/:id/is-following`.
- `GET /users/me` : `api-gateway/src/modules/user/controllers/queries/user/user.query-controller.ts:36-45`, un seul appel `userService.getUser`.

### Conclusion

| Route du mélange | Part | Appels ms-user par requête | RPC |
| :--- | ---: | ---: | :--- |
| `events-list-app` | 40 % | 0 (non trouvé : gateway et `ms-event`, voir ci-dessus) | |
| `posts-list` | 30 % | 0 (non trouvé : gateway et `ms-post`) | |
| `me` | 20 % | 1 | `GetUser` |
| `is-following` | 10 % | 0 (route servie par `queryService` social) | |

**ms-user reçoit donc 0,2 × R appels `GetUser` par seconde** : 40/s à 200 req/s, 55/s à 275 req/s. Aucune autre RPC ms-user n'est sur le chemin chaud de ce mélange. Ce qui n'est pas couvert : les racines non indexées par mesh-mcp et un nom de méthode construit à l'exécution ; `nativapp` n'appelle pas gRPC.

### Ce que cela dit du coût unitaire (INFERENCE, calcul)

- 350m à 275 req/s pour 55 `GetUser`/s donne **environ 6,4 ms de CPU par appel** si le CPU au repos est négligeable. Le relevé de 350m à 200 req/s (`02-analyses.md`, section 1) date d'avant la correction du niveau de log (logger en `debug`) : 8,75 ms par appel, non comparable.
- Comparaison : `ms-social` à environ 430m par pod à 225-250 req/s, pour environ 1,2 × R appels répartis sur 2 pods (2 appels par `events-list-app`, 1 par `posts-list`, 1 par `is-following`), soit environ 3 ms par appel. **Un `GetUser`, qui ne fait qu'une lecture par clé primaire, coûterait donc environ deux fois un appel `ms-social`.** Deux explications possibles, que seul un profil départage : un coût fixe au repos important (NON VERIFIE, à mesurer avec `kubectl top` sans charge), ou un chemin de lecture plus lourd qu'il n'en a l'air (section 2).

---

## 2. GetUser de bout en bout

### FAIT : le chemin

1. Garde : `@UseGuards(GrpcInternalGuard)` (`ms-user/src/modules/user/controllers/queries/user.query.controller.ts:44`) puis `jwtService.verifyInternal` (`npm-packages/packages/auth/src/guards/grpc-internal.guard.ts:30`), qui appelle `jose.jwtVerify` en RS256 avec la clé publique gardée en mémoire après le premier appel (`packages/auth/src/services/jwt.service.ts:48-60, 124-127, 167`). Pas de lecture de fichier par appel.
2. Pipe global `GrpcValidationPipe` (`ms-user/src/app.module.ts:38-44`) : `processData` récursif puis `ValidationPipe.transform` (class-transformer et class-validator) sur `GetUserQueryDTO`, classe vide (`dto/request/query/get-user.query.dto.ts:3`) (`packages/validation-nest/src/pipes/grpc-validation.pipe.ts:22-27`).
3. Une ligne `info` par appel : `this.logger.log('gRPC: Getting user with id: ' + user.id)` (`user.query.controller.ts:50`). Le logger applique 3 expressions régulières de masquage, un `JSON.stringify`, une conversion `BigInt` des identifiants de trace quand une trace est active (`packages/logger/src/logger.ts:93-127`, `masking.ts:24-28, 59-64`, `trace-context.ts:12-26`).
4. `userService.findById(new UserId(...))` (`packages/domain-user/src/services/user.service.ts:60-69`) puis `PostgresUserRepository.findById` = `findWithRelations(where, ['userBadges', 'userBadges.badge'])` (`packages/domain-user/src/repositories/postgres-user.repository.ts:64-66`) puis `repository.findOne({ where, relations })` (`packages/database/src/core/base.repository.ts:116-122`).
5. **TypeORM transforme ce `findOne` en deux requêtes SQL.** `EntityManager.findOne` impose `take: 1` (`ms-user/node_modules/typeorm/entity-manager/EntityManager.js:622-627`). Avec `take` et des jointures, `SelectQueryBuilder.executeEntitiesAndRawResults` lance d'abord `SELECT DISTINCT "distinctAlias"."UserModel_id" ... FROM (<requête complète avec les 2 LEFT JOIN>) "distinctAlias" ORDER BY ... LIMIT 1`, puis la requête complète avec `WHERE ... IN (<ids>)` (`node_modules/typeorm/query-builder/SelectQueryBuilder.js:1984-2050`). La stratégie par défaut est `join` (ligne 1796).
6. Colonnes lues : toutes celles de `users`, y compris `password_hash` (pas de `select: false`, `packages/domain-user/src/models/user.model.ts:22-23`) et `phone` (ligne 13-14), plus `user_badges` et `badges` (dont `description` en `text`, `badge.model.ts:15-16`).
7. Index : clés primaires `users(id)`, `badges(id)`, `user_badges(user_id, badge_id)` (`ms-user/src/migrations/domain/1776334421317-InitialUserSchema.ts:14, 31, 40`). La jointure par `user_id` est servie par le préfixe de la clé primaire composite.
8. Conversion modèle vers entité : `databaseMapper.map` générique (boucle sur les clés partagées, `instanceof`, lookup de Map par clé texte `"UserModel->UserEntity"`, `packages/database/src/core/mapper.service.ts:60-96, 109-122`), plus un override qui mappe chaque badge (`packages/domain-user/src/models/mapper.ts:23-34`).
9. Déchiffrement de l'email : `decrypt(model.email, this.emailSecret)` à chaque lecture (`postgres-user.repository.ts:37-41`). `decrypt` appelle `deriveKey` à chaque appel (`packages/crypto/src/symmetric/cipher.ts:44-46`) : si le secret ne fait pas 32 octets, un SHA-256 du secret par appel, et dans tous les cas un `Buffer.from(secret)` (`kdf.ts:10-14`). Puis `createDecipheriv('aes-256-gcm')`, 3 `Buffer.from(hex)`, `split(':')` (`cipher.ts:48-64`). Aucune dérivation lente (pas de PBKDF2 ni scrypt).
10. Statut `PENDING_DELETION` vérifié dans le contrôleur (`user.query.controller.ts:52-54`), puis `UserTransformer.toUserDTO` (`transformers/user.transformer.ts:45-61`) et `BadgeTransformer.toBadgeDTO` par badge (`transformers/badge.transformer.ts:22-31`).
11. Sérialisation protobufjs avec `defaults: true`, `oneofs: true`, `longs: String`, `enums: String` (`packages/contracts-nest/src/grpc.helpers.ts:116-123`).

### Lecture des coûts (INFERENCE)

| Poste | Coût relatif estimé d'un `GetUser` | Justification |
| :--- | :--- | :--- |
| TypeORM : 2 requêtes construites, envoyées, lues, transformées | le plus gros poste applicatif, 20 à 35 % | Deux constructions SQL complètes (dont un `clone()` de l'expression), deux allers-retours `pg`, deux spans `pg`, `RawSqlResultsToEntityTransformer` sur 3 alias. `ms-event` passe déjà environ 6 % de son temps dans la seule transformation TypeORM (`04-resultats.md`, 4.5) |
| grpc-js, protobuf, pipeline Nest RPC | 10 à 20 % | profils `ms-social` et `ms-event` : 3 à 4 % gRPC plus Nest et natif |
| Ramasse-miettes | 13 à 15 % | même ordre que les trois profils existants |
| JWT (`jose`) | 3 à 6 % | `ms-social` 4,5 % pour le même code de vérification |
| OpenTelemetry (spans non échantillonnés, contexte, métriques) | 3 à 8 % | section 3 |
| Logger | 1 à 3 % | `ms-social` 3,5 % pour environ 10 lignes par seconde et par pod |
| Validation (DTO vide) | 1 à 2 % | `ms-event` 4,2 % avec des DTO plus riches |
| Déchiffrement email, mapping, transformers | moins de 1 % chacun | AES-GCM sur une trentaine d'octets et quelques objets |

**Le déchiffrement des PII n'est pas un poste significatif pour `GetUser`** (un seul champ, AES-GCM natif, pas de KDF lente). Il le devient pour les listes (`findByIds` jusqu'à 100 utilisateurs : 100 `deriveKey` et 100 `createDecipheriv` par appel), qui ne sont pas dans le mélange.

**Base `ms-user-db` (INFERENCE)** : 86 à 130m pour 40 à 55 `GetUser`/s, soit 80 à 110 requêtes SQL par seconde, environ 1 ms de CPU de base par requête. C'est élevé pour une lecture par clé primaire ; la requête `DISTINCT` sur sous-requête jointe, la planification à chaque appel (TypeORM n'utilise pas d'instruction préparée nommée) et la largeur des lignes (`password_hash`, `description`) en sont les candidats. Le poller `outbox-user` (`OUTBOX_BATCH_INTERVAL_MS` 500, `OUTBOX_MAX_IDLE_INTERVAL_MS` 5000, `deploy/apps/base/ms-user/deployment-outbox.yaml:87-92`) ajoute au plus 0,2 à 2 requêtes par seconde au repos (INFERENCE).

---

## 3. Coût fixe par appel, hors métier

| Élément | FAIT | Remarque |
| :--- | :--- | :--- |
| Vérification du jeton interne | RS256, `jose.jwtVerify` à chaque appel (`jwt.service.ts:167`) | Le jeton est unique par requête de gateway (`setJti(crypto.randomUUID())`, `jwt.service.ts:155`) : un cache des jetons vérifiés côté ms-user ne sert à rien tant que la gateway ne réutilise pas ses jetons (phase C3 du plan) |
| Garde | Par méthode, pas en `APP_GUARD` (`app.module.ts` n'en déclare pas). Log `debug` en cas de succès (`grpc-internal.guard.ts:34`), donc filtré en production (`LOGGER_LEVEL=info`, `deployment.yaml`) | |
| Pipe | Global, `transform: true`, `whitelist: true`, `enableImplicitConversion` (`grpc-validation.pipe.ts:11-17`) | Coût même sur un DTO vide |
| Intercepteurs | Aucun déclaré dans `ms-user/src/app.module.ts` | |
| OpenTelemetry | `getNodeAutoInstrumentations` avec seulement `fs` et `dns` désactivés (`packages/monitoring/src/tracing.ts:37-50, 75-77`) ; échantillonnage 10 % (`deployment.yaml`, `OTEL_TRACES_SAMPLER_ARG=0.1`) ; export des métriques toutes les 15 s (`tracing.ts:65-68`) | Sont donc actifs dans ms-user : `grpc`, `pg`, `http`, `express`, `nestjs-core`, `net`, `generic-pool`, `undici`, `runtime-node` et une trentaine d'autres sans module cible (`auto-instrumentations-node/build/src/utils.js:92-107`). `nestjs-core` ajoute un span par handler en plus du span gRPC |
| Logs par RPC | 1 ligne `info` par `GetUser` (`user.query.controller.ts:50`) | Coût aussi dans l'agent Datadog (ingestion) |
| Sonde | `livenessProbe` TCP (`deployment.yaml`), aucune requête SQL de santé par sonde | |
| Deuxième `DataSource` | `PostgresBridgeModule.register` ouvre un second pool vers la même base, en plus de `TypeOrmModule.forRoot` (`ms-user/src/providers/database/database.module.ts:37-57`) | Mémoire et connexions, CPU négligeable (INFERENCE) |

---

## 4. Sources d'allocation (pression sur le ramasse-miettes)

FAIT pour la liste, INFERENCE pour le classement :

1. TypeORM : deux `SelectQueryBuilder` et un `clone()` de l'expression (`SelectQueryBuilder.js:2003-2006`), chaînes SQL, tableaux de lignes brutes avec toutes les colonnes jointes, entités intermédiaires `UserModel`, `UserBadgeModel`, `BadgeModel`.
2. Décodage protobufjs avec `defaults: true` : chaque champ absent est matérialisé (`grpc.helpers.ts:120`).
3. `jose` : décodage base64url, `JSON.parse` de l'en-tête et de la charge, promesses WebCrypto.
4. Spans OpenTelemetry non échantillonnés et objets de contexte, à chaque appel gRPC, `pg` et handler Nest.
5. Logger : chaîne du message, 3 `replace` par expression régulière, objet de charge, `JSON.stringify`, `BigInt`.
6. Mapping en trois étapes du même utilisateur : `UserModel`, `UserEntity` (`mapper.service.ts:61`), `UserDTO` (`user.transformer.ts:46`), plus un `BadgeEntity` et un `BadgeDTO` par badge.
7. Déchiffrement : 4 `Buffer` et un tableau `split` par appel (`cipher.ts:48-63`), plus `Buffer.from(secret)` dans `deriveKey` (`kdf.ts:10`).

`NODE_OPTIONS=--max-semi-space-size=16` est déjà posé sur ms-user (`deploy/apps/base/ms-user/deployment.yaml`, variable `NODE_OPTIONS`) ; le plan (`05-plan-vers-300.md`, phase B) visait 32 pour les `ms-*`.

---

## 5. Cache et second réplica

### Cache du profil (proposition P2)

- **Où** : dans ms-user, autour de la lecture de `GetUser` uniquement (clé = `user.id` issu du jeton vérifié, jamais d'un champ du message). Pas de changement de `npm-packages`.
- **Taux de réussite attendu (INFERENCE)** : sur la rampe, 200 acteurs et 40 `me`/s à 200 req/s, chaque acteur appelle `me` environ toutes les 5 s. TTL de 10 s : environ 50 à 65 % de réussite ; 30 s : environ 85 %. Sur le trafic réel (un `me` à l'ouverture de l'application), nettement moins : le gain de la rampe est une borne haute, comme pour les caches de la phase 2.
- **Invalidation** : locale sur les écritures qui passent par ms-user (`UpdateUser`, `DeleteUser`, `AdminUpdateUser`, `AdminDeleteUser`, `AddBadgeToUser`, `RemoveBadgeFromUser`, `IncrementImpactScore`). **Mais la base `users` est aussi écrite hors de ms-user** : `find_dependents("@volontariapp/domain-user", granularity: "package")` montre `post-processor-user` (dont `BadgeEvaluator`, `post-processors-runner/post-processor-user/src/core/services/badge-evaluator.service.ts:47`) et `worker-user` (`workers-runners/worker-user/src/app.module.ts:44`). Badges attribués, score d'impact et `finalizeDeletion` échappent donc à l'invalidation locale : seul le TTL borne l'écart.
- **Sécurité** :
  - Après `DeleteUser`, l'invalidation locale suffit sur un réplica unique ; avec deux réplicas, l'autre pod peut servir le profil jusqu'au TTL. Le contrôle `PENDING_DELETION` (`user.query.controller.ts:52`) doit porter sur la valeur en cache, et le TTL rester court (5 à 10 s).
  - PII : garder en cache la ligne avec l'email **chiffré** et déchiffrer à la lecture (coût de moins de 1 %), plutôt que le DTO en clair, pour ne pas allonger la durée de vie de l'email en clair dans le tas (vidages mémoire).
  - Taille bornée (LRU) : 256Mi de limite mémoire.
- **Variante à la gateway** : économiserait aussi la signature du jeton interne, le client gRPC et le réseau, donc plus de CPU de nœud, mais l'invalidation entre 5 pods de gateway est plus difficile. Même décision produit que C2 (délai acceptable de propagation).

### Second réplica

- FAIT : la gateway, `ms-event`, `ms-post` et `ms-ranking` visent déjà `ms-user-headless:3000` (`deploy`, `MS_USER_URL`) et `round_robin` est actif côté client (`grpc.helpers.ts:93-98`). Un second réplica serait donc réparti sans autre changement.
- **Recommandation : non, pour le CPU.** Un réplica ne baisse pas le coût par requête, il ajoute un coût fixe (CPU au repos, environ 150 à 200Mi) sur un nœud qui est la limite (`04-resultats.md`, 4.3). ms-user est à environ 350m sur 800m, donc une boucle d'événements occupée à environ 35 % : pas de file d'attente (INFERENCE). À reconsidérer pour la disponibilité, ou si ms-user dépasse 60 % d'occupation au profil.

---

## 6. Propositions

| # | Quoi | Où (`origin/main`) | Nature | Gain CPU ms-user estimé | Gain `ms-user-db` | Effort | Risque | STOP / migration |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| P1 | Lire l'utilisateur et ses badges en **une** requête SQL : `repository.find({ where, relations })` puis premier élément, ou `createQueryBuilder().leftJoinAndSelect(...).where('id = :id').getOne()` sans `take` (la clé primaire garantit une ligne `users`) | `packages/domain-user/src/repositories/postgres-user.repository.ts:64-66` ; cause : `base.repository.ts:116-122` + `EntityManager.js:625` + `SelectQueryBuilder.js:1988-2050` | FAIT (2 requêtes), gain INFERENCE | 10 à 20 % | 35 à 50 % de la part `GetUser` | 2 h avec tests | Faible : même résultat ; tester l'ordre des badges et l'utilisateur absent | npm-packages (`domain-user`), règle du STOP. Pas de migration |
| P2 | Cache du profil dans ms-user, TTL 5 à 10 s, ligne chiffrée, LRU borné, invalidation locale sur les écritures ms-user | `ms-user/src/modules/user/controllers/queries/user.query.controller.ts:44-56` (nouveau service local) | INFERENCE | 25 à 45 % sur la rampe (borne haute), faible en trafic réel | 50 à 80 % sur la rampe | 0,5 à 1 jour | Moyen : profil périmé jusqu'au TTL après une écriture de `post-processor-user` ; suppression sur 2 réplicas | ms-user seul. Décision de Victor sur le TTL |
| P3 | Passer la ligne `gRPC: Getting user with id` en `debug` (phase 2.4 du plan) | `user.query.controller.ts:50` | FAIT (1 ligne par appel), gain INFERENCE | 1 à 3 %, plus l'ingestion de l'agent Datadog | 0 | 15 min | Faible ; contre-argument : la règle de traçabilité (AGENTS.md section 6). Les traces à 10 % et les logs d'erreur restent | ms-user seul |
| P4 | Restreindre les instrumentations OpenTelemetry par variable d'environnement : `OTEL_NODE_ENABLED_INSTRUMENTATIONS=grpc,pg,runtime-node` (ou `OTEL_NODE_DISABLED_INSTRUMENTATIONS=nestjs-core,express,http,net,generic-pool,undici`) | `deploy/apps/base/ms-user/deployment.yaml` ; lecture des variables : `auto-instrumentations-node/build/src/utils.js:118-127, 135-157` | FAIT (mécanisme), gain INFERENCE | 2 à 6 % | 0 | 15 min | Faible : perte des spans Nest, redondants avec le span gRPC ; vérifier une trace dans Datadog après | deploy seul |
| P5 | Jeton interne réutilisé par la gateway et cache des jetons vérifiés dans les `ms-*` (phase C3) | `packages/auth/src/services/jwt.service.ts:118-127, 151-177`, `guards/grpc-internal.guard.ts:30` | INFERENCE (analogie `ms-social` 4,5 %) | 3 à 5 % (plus la signature RS256 à la gateway, plus coûteuse) | 0 | 1 jour | Moyen : durée de vie d'un jeton rejouable ; revue de sécurité | npm-packages (`auth`), STOP |
| P6 | Zone jeune à 32 Mo au lieu de 16 (phase B du plan) après relevé mémoire | `deploy/apps/base/ms-user/deployment.yaml` (`NODE_OPTIONS`) | INFERENCE | 3 à 8 % si le GC pèse 13 à 15 % comme ailleurs | 0 | 15 min | Faible : quelques dizaines de Mo, limite 256Mi | deploy seul |
| P7 | Ne plus lire `password_hash` et `phone` dans les lectures de profil (`select: false` sur la colonne, les lectures du hash ont déjà un `select` explicite) | `packages/domain-user/src/models/user.model.ts:13-14, 22-23` ; lectures du hash : `postgres-user.repository.ts:212-226` | INFERENCE | moins de 2 % | 5 à 10 % | 1 h | Faible à moyen : vérifier `createWithHashedPassword` et `update` (lignes 204-210, 279-295) | npm-packages, STOP. Pas de migration |
| P8 | Dériver la clé de chiffrement une fois (constructeur du repository) au lieu de `deriveKey` à chaque `decrypt` | `cipher.ts:45-46`, `kdf.ts:4-15`, `postgres-user.repository.ts:37-41` | FAIT (dérivation par appel), gain INFERENCE | moins de 1 % pour `GetUser` ; utile pour `findByIds` (100 lignes) | 0 | 1 h | Faible | npm-packages (`crypto` ou `domain-user`), STOP |
| P9 | Supprimer le second pool (`PostgresBridgeModule`) si rien ne l'utilise | `ms-user/src/providers/database/database.module.ts:37-46` | FAIT (deux pools), usage NON VERIFIE | négligeable | quelques connexions inactives | 1 h | Moyen : vérifier qui injecte `NestPostgresProvider` (santé ?) | ms-user seul |

Écartés : la validation d'un DTO vide (1 à 2 %, contourner le pipe global affaiblirait la défense en profondeur) ; un second réplica (section 5).

### Constat de sécurité hors sujet, à signaler

FAIT : `ListUsers` n'a pas `@UseGuards(GrpcInternalGuard)` (`ms-user/src/modules/user/controllers/queries/user.query.controller.ts:75-91`), alors que toutes les autres lectures l'ont, et renvoie des `UserDTO` avec l'email déchiffré. AGENTS.md section 6 exige un rejet `UNAUTHENTICATED` sans jeton interne. Les NetworkPolicies limitent l'exposition (non relues). À corriger indépendamment de la performance.

---

## 7. Procédure de profil pour confirmer

Procédure de la skill `volontariapp-load-ramp`, section « Profil CPU d'un pod Node », appliquée à ms-user. `kubectl exec` en production peut être refusé par le classificateur : ne pas le contourner, c'est à Victor de le lancer.

1. **Coût fixe au repos** (avant toute charge) : `kubectl -n prod top pod -l app=ms-user` toutes les 10 s pendant 2 min. Si le repos dépasse 50m, le coût par appel est surestimé dans ce document.
2. **Charge isolée sur ms-user** : `LOAD_MIX="me:100" LOAD_STEPS="100" LOAD_STEP_SECONDS=120` (variables lues par `traffic-simulator/src/load/load-config.ts:121-131`), soit 100 `GetUser`/s, presque deux fois le pic du mélange à 275 req/s.
3. Activer l'inspecteur et capturer 30 s après 20 s de chauffe :

```bash
POD=$(kubectl -n prod get pods -l app=ms-user -o name | head -1)
kubectl -n prod exec "$POD" -c ms-user -- sh -c 'kill -USR1 1'
kubectl -n prod port-forward "$POD" 9229:9229 &
node .agents/skills/volontariapp-load-ramp/scripts/capture-cpu-profile.mjs 30 ms-user-me.cpuprofile
node .agents/skills/volontariapp-load-ramp/scripts/analyze-cpuprofile.mjs ms-user-me.cpuprofile 25
```

4. Nettoyer : arrêter le `port-forward`, supprimer le pod profilé.
5. **Lecture attendue** : chercher dans le top des fonctions `executeEntitiesAndRawResults`, `createOrderByCombinedWithSelectExpression`, `clone`, `RawSqlResultsToEntityTransformer` (TypeORM, P1), `jwtVerify` (P5), `maskString` et `print` (P3), les modules `@opentelemetry` (P4), le ramasse-miettes (P6), `decrypt` et `deriveKey` (P8). Diviser le CPU du pod par 100 donne le coût réel d'un `GetUser`.
6. **Base** : ne pas interroger la base de production depuis un agent. Sur une base locale (`ci-tools` docker-compose) avec le schéma migré, journaliser les requêtes TypeORM (`logging: ['query']`) pour voir les deux requêtes, puis `EXPLAIN (ANALYZE, BUFFERS)` de chacune. En production, si Victor le souhaite, `pg_stat_statements` sur `ms-user-db` pendant le palier de l'étape 2 donne le temps par requête et confirme le gain de P1.
7. Après chaque PR : rejouer l'étape 2 et comparer le CPU de ms-user et de `ms-user-db` (règle « une phase, une mesure » du plan).

---

## 8. Classement et ordre des PR

### Top 5 (gain attendu rapporté à l'effort)

1. **P1, une requête SQL au lieu de deux** : plus gros gain certain sur la base et réel sur ms-user, risque faible. STOP `npm-packages`.
2. **P2, cache du profil** : plus gros gain potentiel sur la rampe, mais dépend du trafic réel et d'une décision de Victor (TTL, suppression). ms-user seul.
3. **P4, instrumentations OpenTelemetry restreintes** : 15 min, deploy seul, s'étend aux autres services s'il se confirme.
4. **P6, zone jeune à 32 Mo** : 15 min, deploy seul, déjà dans le plan, mesure de la porte de la phase B.
5. **P3, ligne `info` en `debug`** : 15 min, ms-user seul, gain aussi sur l'agent Datadog.

P5 (jeton interne) a un gain système supérieur à P3 et P6, mais il est déjà porté par la phase C3 du plan pour tous les services.

### Ordre de PR proposé

1. **Mesure d'abord** : repos et profil `me:100` (section 7, étapes 1 à 5). Si TypeORM ne dépasse pas 15 % du temps occupé, descendre P1 dans la liste.
2. **PR `deploy`** : P4 et P6 ensemble ou séparés selon la règle « une phase, une mesure » (séparés de préférence, chacun 15 min).
3. **PR `ms-user`** : P3 (et P9 si l'usage du second pool est vérifié).
4. **PR `npm-packages`** : P1 (et P7 dans le même bump de `domain-user`), changeset, puis **STOP** jusqu'à la publication par la CI, puis `yarn up @volontariapp/domain-user` dans ms-user, `post-processors-runner` et `workers-runners`. Pas de migration.
5. **PR `ms-user`** : P2, après la décision de Victor sur le TTL et seulement si le profil après P1 montre encore la lecture comme premier poste.
6. Séparément, **PR `ms-user`** de sécurité : garde interne sur `ListUsers`.

Le poids de ms-user dans le nœud reste faible (environ 3 %, `02-analyses.md` section 1) : même l'ensemble P1 à P6 ne rapporte qu'environ 1 à 2 % du CPU du nœud (INFERENCE : 150 à 200m sur 11 à 12 vCPU au pic). Ces gains aident le chemin vers 300 req/s, sans le décider ; les postes `ms-social`, `ms-event` et gateway restent prioritaires.
