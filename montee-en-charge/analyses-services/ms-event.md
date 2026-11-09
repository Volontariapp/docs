# ms-event : réduire le CPU par requête (pod et ms-event-db)

Analyse du 2026-11-09, lecture seule. Aucun dépôt modifié, aucune base de production interrogée.

Conventions (AGENTS.md, section 2 quinquies) :
- **FAIT** : ligne lue ce tour-ci (`fichier:ligne` sur `origin/main`) ou sortie d'outil.
- **INFERENCE** : déduction, non vérifiée.
- **NON VERIFIE** : dépend de la production (EXPLAIN, volumes, profil) qu'il faut mesurer.

Versions lues : `ms-event` `origin/main` = `a62fef8` (l'image déployée est `sha-a62fef8`, `deploy/apps/base/ms-event/deployment.yaml:43`). `npm-packages` `origin/main` = `fff2319f`. `ms-event/yarn.lock` résout `@volontariapp/domain-event` 3.16.9, `typeorm` 0.3.30, `pg` 8.23.1, `class-validator` 0.15.1, `jose` 6.2.16, `@opentelemetry/auto-instrumentations-node` 0.75.0, `@opentelemetry/instrumentation-pg` 0.69.0. Base : `postgis/postgis:16-3.4`, 800m / 256Mi (`deploy/apps/overlays/prod/ms-event/db-postgres/kustomization.yaml`).

---

## 0. Le profil CPU fourni n'est pas exploitable

**FAIT** : `ms-event-225.cpuprofile` (modifié le 2026-11-09 à 11:06:46) contient 125 nœuds. `analyze-cpuprofile.mjs` donne 42 % d'occupation, dont 98,2 % dans `_kill`, plus `callAppShutdownHook`, `onApplicationShutdown` (TypeORM) et `shutdown` (OpenTelemetry). Aucune frame applicative. Le fichier a enregistré l'**arrêt du processus**, pas le palier à 225 req/s. `gateway-225.cpuprofile` et `ms-social-225.cpuprofile`, écrits à la même seconde, ont le même défaut (`_kill` dominant).

Ce rapport s'appuie donc sur :
1. le résumé du profil donné dans la demande (GC 13,3 %, hydratation TypeORM environ 6 %, validation 4,2 % dans `isUUID`, `addFields` / `parseDate` de `pg`, instrumentation pg, écritures natives). Je l'ai pris tel quel, sans pouvoir le relire ;
2. la lecture du code déployé ;
3. des micro-benchmarks jetables (`scratchpad/bench/src/bench.ts`, `scratchpad/bench/uuid.js`), lancés avec les `node_modules` de ms-event (mêmes versions de typeorm, class-validator, pg et jose que le lockfile) sur la machine locale (Node 24.2, Apple Silicon). Il faut s'attendre à des valeurs 1,2 à 2 fois plus élevées sur un vCPU de la VM (INFERENCE).

**Action préalable recommandée** : refaire le profil en vérifiant que la fenêtre de capture se ferme avant tout redémarrage du pod (le `_kill` laisse penser que le pod a reçu SIGTERM pendant la capture, peut-être un rollout ou un `kubectl delete`). Toutes les estimations ci-dessous sont à confirmer avec ce nouveau profil.

---

## 1. Ce que ms-event reçoit dans le mélange de charge

| Route du mélange | Appel vers ms-event | Source |
| :--- | :--- | :--- |
| `events-list-app` (40 %) | `SearchEvents`, avec `excludedIds` et `excludedOrganizerIds` | FAIT : `api-gateway/src/modules/event/controllers/queries/event/event.query-controller.ts:59-72` ; `traffic-simulator/src/load/load-request.ts:13-20,43` (`page` 1 à 3, `limit=20`, 4 drapeaux `exclude*`, ni zone géographique, ni `statuses`, ni dates) |
| `posts-list` (30 %) | `GetEventsByIds`, seulement pour les ids absents du cache de la gateway (30 s par pod, 5 pods) | FAIT : `api-gateway/src/modules/event/services/event-lookup.service.ts:47-66` |
| `me` (20 %) | aucun : ms-user seulement | FAIT : `api-gateway/src/modules/user/controllers/queries/user/user.query-controller.ts:36-45` |
| `is-following` (10 %) | aucun (ms-social) | INFERENCE (route sociale, non relue) |

Clients gRPC de `SearchEvents`, sorties `analyze_grpc` : `api-gateway` `listEvents` (event.query-controller.ts:69), `api-gateway` `RankedEventsService.read` (ranked-events.service.ts:52) et un client de service dans `workers-runners/worker-ranking/src/clients/event-ranking.client.ts:29`. Pour `GetEventsByIds` : `api-gateway` `listPosts` (post.query-controller.ts:75) et le même client de `worker-ranking`. Seul le chemin de la gateway fait partie du mélange.

**Ordre de grandeur (INFERENCE)** : à 250 req/s, environ 100 `SearchEvents` par seconde, soit 50 par pod, et 0 à 37 `GetEventsByIds` par pod selon le taux de réussite du cache de la gateway (non mesuré, `04-resultats.md` section 5). À 480m par pod, cela fait 5 à 9 ms de CPU par RPC.

**Comment les listes arrivent** (FAIT) : la gateway filtre les ids avec `isUUID` et les coupe à 1 000 (`api-gateway/src/modules/event/services/event-social-filter.service.ts:128-140`). Elle envoie au plus **1 000 `excludedIds` (événements créés, participés ou souhaités, fusionnés par ms-social) et 1 000 `excludedOrganizerIds` (utilisateurs bloqués)**, soit au plus 2 000 ids par recherche, pas 4 000 (`event-social-filter.service.ts:62-73`).

**Taille réelle des listes pendant la rampe** : NON VERIFIE. INFERENCE : le résumé du profil attribue 4,2 % du temps occupé à `isUUID`. 4,2 % de 580m, c'est environ 24 ms/s. Pour environ 45 recherches/s par pod à 225 req/s, cela donne environ 0,5 ms de validation par recherche, ce que mon banc mesure pour **2 x 1 000 ids** (0,43 ms, section 3.3). Les listes étaient donc probablement proches du plafond pendant la rampe.

---

## 2. SearchEvents : du contrôleur au SQL

### 2.1 Le chemin

1. `GrpcInternalGuard` vérifie un JWT RS256 (`npm-packages/packages/auth/src/guards/grpc-internal.guard.ts:30`, `jwt.service.ts:167`, `jose.jwtVerify`).
2. Le `GrpcValidationPipe` global (`ms-event/src/app.module.ts:40-49`) recopie tout le message avec `processData` (`npm-packages/packages/validation-nest/src/pipes/grpc-validation.pipe.ts:34-72`, un `map` récursif, y compris sur les tableaux de 1 000 chaînes). `ValidationPipe` enchaîne ensuite `plainToInstance` (`transform: true`, `enableImplicitConversion`, pipe.ts:11-18) et class-validator : `@IsUUID('all', { each: true })` sur `ids`, `excludedIds` et `excludedOrganizerIds` (`ms-event/src/modules/event/dto/request/query/search-events.query.dto.ts:59-76`).
3. Le contrôleur écrit deux lignes `info`, dont un `JSON.stringify` (`ms-event/src/modules/event/controllers/queries/event.query.controller.ts:70` et `:79-81`), puis construit `SearchAdvancedVO` (`:83-105`).
4. `PostgresEventRepository.searchAdvanced` (`npm-packages/packages/domain-event/src/repositories/postgres-event.repository.ts:377-460`) construit la requête, puis appelle `getManyAndCount()` (`:452`).
5. `toEntity` par ligne (databaseMapper), puis `toEventDTO` (`ms-event/src/modules/event/transformers/event.transformer.ts:135-170`) et l'encodage protobuf.

### 2.2 Le SQL produit, reconstruit (FAIT : sortie de `getQueryAndParameters()` du banc, même EventModel)

Requête de page, pour le cas de la rampe (pas de zone, pas de tag) :

```sql
SELECT "event"."id" AS "event_id", "event"."name" AS "event_name", "event"."description" AS "event_description",
       "event"."startAt" AS "event_startAt", "event"."endAt" AS "event_endAt",
       ST_AsGeoJSON("event"."location")::json AS "event_location",
       "event"."type", "event"."state", "event"."saga_status", "event"."awardedImpactScore",
       "event"."maxParticipants", "event"."scoring_version", "event"."cover_file_id", "event"."cover_status",
       "event"."organizerId", "event"."localisationName", "event"."createdAt", "event"."updatedAt"
FROM "events" "event"
WHERE "event"."id" NOT IN ($1, $2, ..., $1000)
  AND "event"."organizerId" NOT IN ($1001, ..., $2000)
ORDER BY "event"."createdAt" DESC, "event"."id" DESC
LIMIT 20 OFFSET 0|20|40
```

Requête de total, construite par `executeCountQuery` (FAIT : `typeorm/query-builder/SelectQueryBuilder.js:1738-1752`, `computeCountExpression` :1671-1681 donne `COUNT(1)` quand il n'y a pas de jointure) :

```sql
SELECT COUNT(1) AS "cnt" FROM "events" "event"
WHERE "event"."id" NOT IN ($1, ..., $1000) AND "event"."organizerId" NOT IN ($1001, ..., $2000)
```

Points FAIT :
- **Les listes deviennent 2 000 paramètres positionnels** (`:...excludedIds`, repository.ts:431-439). `PostgresDriver.escapeQueryWithParameters` les déplie un par un (`typeorm/driver/postgres/PostgresDriver.js:648-662`). Mesuré : le SQL passe de 901 à **13 855 caractères** avec 2 x 1 000 ids.
- **Le texte et les 2 000 valeurs partent deux fois** : la requête de total reprend le même `WHERE` (`SelectQueryBuilder.js:1740-1750`). Elle n'est sautée que si la première page n'est pas pleine (`lazyCount`, :830). Pour les pages 1 à 3 d'une table de plus de 60 événements visibles, elle part à chaque appel.
- Les deux requêtes partent **l'une après l'autre** sur le même `queryRunner` (`SelectQueryBuilder.js:828-838`).
- Toutes les colonnes de `events` sont lues, y compris `description` (`text`) et `location` via `ST_AsGeoJSON(...)::json`, que `pg` reparse en JSON. Le DTO utilise toutes les colonnes sauf `saga_status` (`event.transformer.ts:135-170`). Réduire les colonnes rapporte donc peu.
- Géographie (absente de la rampe) : `ST_DWithin(event.location::geography, ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography, :radius)` et `ORDER BY ST_Distance(...)` (repository.ts:380-387). Les coordonnées sont **interpolées dans le texte SQL** : le texte change à chaque position, ce qui empêche tout cache de plan. Il existe un index GIST sur `location` (`ms-event/src/migrations/domain/1780000000000-AddLatLongToEvent.ts:6`) : comme la colonne est déjà `geography`, le cast `::geography` ne devrait pas empêcher l'index (INFERENCE, à confirmer par EXPLAIN).
- `tagSlugs` ajoute un `LEFT JOIN event_tags/tags` sans `DISTINCT` (repository.ts:441-444). Avec une jointure, TypeORM passe en `COUNT(DISTINCT("event"."id"))` et en pagination à deux requêtes (sous-requête d'ids distincts). Ce cas est absent de la rampe ; c'est aussi un risque de doublons quand un événement porte deux des tags demandés (INFERENCE).

### 2.3 Index déclarés (FAIT, migrations ; NON VERIFIE en production)

| Index | Migration |
| :--- | :--- |
| `idx_events_created_at_desc ("createdAt" DESC)` | `domain/1792300000000-AddEventSearchIndexes.ts:24` |
| `idx_events_state_start_at ("state", "startAt")` | même fichier :20 |
| `idx_events_organizer_id ("organizerId")` | même fichier :16 |
| `idx_events_location GIST ("location")` | `domain/1780000000000-AddLatLongToEvent.ts:6` |
| `IDX_events_saga_status` | `domain/1780932284627-AddSagaStatusToEvent.ts:13` |
| `event_tags (eventsId)`, `(tagsId)`, `event_requirements (eventsId)`, `(requirementsId)` | `domain/1776008237420-InitialSchema.ts:28-40` |

La migration indique elle-même « EXPLAIN non exécuté » (AddEventSearchIndexes.ts:4-5).

INFERENCE sur les plans :
- **Page** : `ORDER BY createdAt DESC, id DESC LIMIT 20 OFFSET 40`. L'index ne couvre que `createdAt` : PostgreSQL 16 peut lire l'index puis faire un *Incremental Sort* sur `id`, avec le `NOT IN` en filtre, et s'arrêter après environ 60 lignes. Si le planificateur juge le `NOT IN` très sélectif ou la table petite, il peut aussi choisir *Seq Scan + top-N sort*. Les deux plans sont plausibles : NON VERIFIE.
- **Total** : `COUNT(1)` sans `LIMIT` doit parcourir **toutes** les lignes de `events` (seq scan ou index scan complet) et tester chaque ligne contre les deux listes. Depuis PostgreSQL 15, un `NOT IN` sur une liste de constantes est évalué par table de hachage, donc le coût par ligne reste faible, mais il porte sur toute la table, à environ 100 recherches par seconde.
- **Préparation** : `pg` envoie des requêtes non nommées, analysées et planifiées à chaque exécution. Avec 2 000 paramètres : 2 000 nœuds `Param`, une `ArrayExpr`, puis une estimation de sélectivité par élément du tableau (`scalararraysel`), le tout deux fois par recherche. INFERENCE : 1 à 5 ms de CPU base par recherche ; à mesurer avec `EXPLAIN (ANALYZE, SUMMARY)` (*Planning Time*).

### 2.4 Coût côté Node, mesuré par le banc (FAIT local ; facteur VM non appliqué)

| Étape | 2 x 0 ids | 2 x 100 | 2 x 1 000 |
| :--- | ---: | ---: | ---: |
| `ValidationPipe` (transform + validate) sur le DTO de recherche | 17 µs | 49 µs | **427 µs** |
| dont `isUUID` x 2 000 seul | | | 270 à 287 µs |
| `getQueryAndParameters` page | 14 µs | 21 µs | 90 µs |
| clonage et construction de la requête de total | 7 µs | 16 µs | 86 µs |
| `pg-protocol serialize.bind` (2 000 valeurs texte), par requête | | | **306 µs** (x 2) |
| `serialize.bind` avec 2 tableaux littéraux, construction comprise | | | 92 µs |
| `getQueryAndParameters` en `<> ALL(:ids::uuid[])` | | | 12 µs (984 caractères) |
| hydratation TypeORM de 20 événements sans relation | 50 µs | | |
| `jose.jwtVerify` RS256 2048 | 40 µs | | |
| une ligne de log JSON (masque + stringify, sans écriture) | 3,7 µs | | |

**Lecture (INFERENCE)** : avec des listes pleines, ce qui dépend du nombre d'ids (validation, construction SQL x 2, Bind x 2) coûte environ **1,2 ms par recherche** en local, environ 1,5 ms sur la VM (facteur 1,25 déduit de la section 1). À 45 ou 50 recherches/s par pod, cela fait **60 à 75m par pod, environ 12 à 15 % du CPU de ms-event**, sans compter le GC que ces allocations provoquent : 2 x 80 Ko de tampons Bind, deux textes SQL de 14 Ko et leurs copies par `replacePropertyNamesForTheWholeQuery`, 3 copies de chaque tableau de 1 000 chaînes (décodage protobuf, `processData`, `plainToInstance`). Ce GC fait partie des 13,3 % mesurés. Le décodage protobuf de 2 000 chaînes n'a pas été mesuré.

---

## 3. GetEventsByIds et les autres RPC

- `getEventsByIds` (`event.query.controller.ts:54-63`) appelle `findEventsInOrder` (`utils/events-by-ids.util.ts:16-37`, une requête par tranche de 100), puis `EventService.findByIds`, dont les relations par défaut sont **`['requirements', 'tags']`** (`npm-packages/packages/domain-event/src/services/event.service.ts:52-58`), puis `repository.find({ where: { id: In(unique) }, relations })` (`postgres-event.repository.ts:49-60`).
- SQL produit (FAIT, banc) : une seule requête avec `LEFT JOIN event_tags`, `tags`, `event_requirements` et `requirements`. Elle renvoie **le produit cartésien tags x exigences** pour chaque événement : 20 événements avec 3 tags et 3 exigences donnent 180 lignes de 33 colonnes.
- Mesuré : hydratation de 180 lignes, **198 µs**, contre 50 µs pour 20 lignes sans relation. Côté base, les lignes et les octets transférés sont multipliés d'autant. Le nombre réel de tags et d'exigences par événement est NON VERIFIE.
- Le DTO de réponse contient bien `tags` et `requirements` (`event.transformer.ts:152-155`). Je n'ai pas vérifié si la liste des posts (gateway `EventDTO.fromResponse`, carte de post dans nativapp) affiche les exigences : **NON VERIFIE**.
- `getEvent` et `listRequirements` passent par `findById` avec les mêmes deux relations (`event.service.ts:33-35`) ; ils sont hors du mélange.
- `GetUserCreated/Participated/WishedEvents` (`event.query.controller.ts:132-193`) appellent ms-social puis `findEventsInOrder` ; ils sont hors du mélange.

---

## 4. Coût fixe par appel

| Élément | Où | Mesure ou estimation | Remarque |
| :--- | :--- | :--- | :--- |
| Vérification RS256 | `auth/src/guards/grpc-internal.guard.ts:30`, `jwt.service.ts:167` | 40 µs (FAIT local) ; environ 4m par pod à 90 RPC/s (INFERENCE) | Un cache par jeton ne sert que si la gateway réutilise ses jetons (levier 2.3 non livré, `04-resultats.md` section 2) : sinon presque aucune réussite |
| `processData` + `plainToInstance` + class-validator | `validation-nest/.../grpc-validation.pipe.ts:22-72` | 17 µs à vide, 427 µs avec 2 x 1 000 ids | Coût de base faible ; ce sont les listes qui coûtent |
| Logs `info` par RPC | `event.query.controller.ts:59`, `:70`, `:79-81` | environ 4 µs de formatage + une écriture synchrone sur stdout par ligne, soit 3 lignes par recherche avec la gateway | `console.log` sur un pipe est synchrone sous Linux : ce sont les « écritures natives » du profil. Chaque ligne coûte aussi du CPU à l'agent Datadog, sur le même nœud |
| OpenTelemetry | `monitoring/src/tracing.ts:70-78` : `getNodeAutoInstrumentations` active **toutes** les instrumentations sauf `fs` et `dns` (:37-50) | non mesuré | Échantillonnage `parentbased_traceidratio` 0.1 (`deployment.yaml:104-107`) : 90 % des spans ne sont pas enregistrés mais restent créés. `instrumentation-pg` 0.69 enregistre l'histogramme `db.client.operation.duration` à **chaque** requête, échantillonnée ou non (`instrumentation-pg/build/src/instrumentation.js:41,146-167,216`), et recopie la configuration de la requête (texte de 14 Ko compris) |
| Mapper entité | `database/src/core/mapper.service.ts:58-90` | environ 1 µs par événement (INFERENCE) | Négligeable |
| GC | `NODE_OPTIONS=--max-semi-space-size=16` (`deployment.yaml:110-111`) | 13,3 % (profil fourni) | Le levier est de réduire les allocations (sections 2.4 et 3) |

---

## 5. Pourquoi ms-event-db est la base la plus chargée (INFERENCE, à vérifier)

1. **Le `COUNT(1)` de chaque recherche parcourt toute la table `events`** et teste 2 x 1 000 valeurs (hachées) sur chaque ligne, pendant que la page s'arrête après environ 60 lignes. Il y a un précédent mesuré dans ce dépôt : sur `posts`, le total coûtait **12 ms contre 0,2 ms pour la page**, sur 29 000 lignes (commentaire FAIT dans `npm-packages/packages/domain-post/src/repositories/postgres-post.repository.ts:159-162`). C'est la cause la plus probable.
2. **Analyse et planification de deux requêtes à 2 000 paramètres** à chaque recherche, sans cache de plan.
3. Pour `GetEventsByIds` : le produit cartésien tags x exigences (section 3).
4. Bruit de fond : chaque outbox runner interroge `event_queue` et `jobs_outbox` toutes les 500 ms (`outbox-runners/outbox-event/config/default.config.json:16`), soit quelques requêtes par seconde. C'est négligeable et c'est pareil pour toutes les bases.

Ce que la base ms-event fait de plus que les autres : environ 100 recherches par seconde portant 2 000 paramètres et un comptage complet de la table. Volume de `events` en production : NON VERIFIE (requête refusée par la consigne). Pour trancher, le Lead Dev peut lancer sur une copie de dev ou de préproduction, avec 2 x 1 000 uuid réalistes :
`EXPLAIN (ANALYZE, BUFFERS, SUMMARY)` sur la requête de page et sur la requête de total, puis comparer *Planning Time* et *Execution Time*. `pg_stat_statements` n'est pas configuré dans le chart (FAIT : aucune valeur `shared_preload_libraries` dans `db-postgres/kustomization.yaml`).

---

## 6. Propositions

Notation du gain : part estimée du CPU de ms-event (pod) et de ms-event-db au mélange de la rampe, toutes INFERENCE tant qu'un nouveau profil et un EXPLAIN ne les confirment pas.

### P1. Supprimer le `COUNT` de chaque recherche

- **Quoi** : remplacer `getManyAndCount()` par la page seule et un total obtenu autrement. Deux variantes :
  - (a) **le motif `knownTotal` de domain-post** (déjà en place dans ms-post, `04-resultats.md` phase 2.2) : `searchAdvanced(params, { knownTotal })`, plus un cache borné de 10 s dans le contrôleur ms-event, avec une clé qui couvre le filtre complet. Les listes d'exclusion font partie du filtre : la clé doit inclure l'utilisateur et un hachage des listes. La réussite vient surtout des pages 2 et 3 d'une même session ;
  - (b) **lire `limit + 1` lignes** et ne compter que sur la page 1, ou borner le total : `SELECT COUNT(1) FROM (SELECT 1 ... LIMIT 1000) t`. nativapp ne se sert de `totalCount` que pour savoir s'il reste une page (FAIT : `nativapp/src/api/event/hooks/use-get-events.ts:33-38`), mais la gateway en tire `totalPages`. Changer le sens de `totalCount` est une décision de contrat, à trancher par le Lead Dev.
- Si un total reste nécessaire, le lancer en parallèle de la page (`Promise.all`, comme domain-post :172) : c'est un gain de latence, pas de CPU.
- **Où** : `npm-packages/packages/domain-event/src/repositories/postgres-event.repository.ts:446-459` ; `ms-event/src/modules/event/controllers/queries/event.query.controller.ts:107-114`.
- **Gain** : base, le plus gros levier probable, **30 à 60 % du CPU de ms-event-db** si le total domine comme pour les posts (INFERENCE, à confirmer par EXPLAIN). Pod : retire une construction SQL, un Bind de 2 000 valeurs, un aller-retour et un passage OTel, soit environ 0,4 ms par recherche avec listes pleines, **6 à 8 % du CPU de ms-event**.
- **Effort** : 2 à 3 h (même motif que ms-post). **Risque** : un total vieux de 10 s, déjà accepté pour les posts.
- **npm-packages** : oui (domain-event, règle du STOP, publication avant ms-event). Migration : non.

### P2. Passer les listes d'ids en tableau unique (`<> ALL($1::uuid[])`)

- **Quoi** : `event.id <> ALL(CAST(:excludedIds AS uuid[]))`, `event."organizerId" <> ALL(CAST(:excludedOrganizerIds AS uuid[]))` et `event.id = ANY(CAST(:ids AS uuid[]))`, sans `:...`. `pg` convertit alors un tableau JS en un seul littéral. La sémantique est la même que `NOT IN` (colonnes non nulles ; les tableaux vides sont déjà exclus par les `if`).
- **Où** : `postgres-event.repository.ts:427-439`.
- **Gain mesuré par requête** : construction SQL 90 µs → 12 µs ; Bind 306 µs → moins de 92 µs ; texte SQL 13 855 → 984 caractères. Cela fait moins de travail pour TypeORM (`replacePropertyNamesForTheWholeQuery`, `escapeQueryWithParameters`), pour l'instrumentation pg et pour le GC. Environ **0,3 ms par requête**, 0,6 ms par recherche tant que P1 n'est pas livré : **5 à 10 % du CPU de ms-event**. Côté base, l'analyse est plus légère (un paramètre au lieu de 2 000). L'estimation par élément reste probablement en place (INFERENCE) : gain faible à moyen.
- **Effort** : 1 h + tests du repository. **Risque** : faible. La forme `::uuid[]` passe le regex de paramètres de TypeORM (vérifié dans le banc) ; `CAST(... AS uuid[])` est plus lisible.
- **npm-packages** : oui (domain-event). Migration : non. Se livre avec P1 dans la même PR.

### P3. Arrêter la validation élément par élément des listes d'ids

- **Quoi** : sur `ids`, `excludedIds` et `excludedOrganizerIds`, remplacer `@IsUUID('all', { each: true })` par `@IsString({ each: true })` (un `typeof`), en gardant `@IsArray` et `@ArrayMaxSize(1000)`. Raisons : (1) la gateway filtre déjà chaque id avec `isUUID` (`event-social-filter.service.ts:129`) ; (2) PostgreSQL relit chaque valeur en `uuid` (`uuid_in`, en C) et rejette une valeur invalide (erreur 22P02). Sans cette annotation, il faut mapper 22P02 vers `INVALID_ARGUMENT` pour garder un 400 au lieu d'un `DATABASE_ERROR`. Une boucle `charCodeAt` écrite à la main n'est pas plus rapide en JS (347 µs contre 270 µs, mesuré) : il faut supprimer la vérification, pas l'optimiser.
- **Où** : `ms-event/src/modules/event/dto/request/query/search-events.query.dto.ts:59-76`. Le `processData` du pipe (copie complète) se trouve dans `npm-packages/packages/validation-nest/src/pipes/grpc-validation.pipe.ts:39-41` ; un raccourci pour les tableaux de chaînes serait une seconde étape, à prévoir dans npm-packages.
- **Gain** : environ 270 µs sur 427 µs par recherche avec listes pleines, **4 à 5 % du CPU de ms-event** (cohérent avec les 4,2 % de `isUUID` du profil), plus les allocations de validator.js.
- **Effort** : 1 h. **Risque** : une défense de moins pour un RPC interne protégé par `GrpcInternalGuard` ; c'est un choix de sécurité à faire valider par le Lead Dev. **npm-packages** : non (ms-event seul). Migration : non.

### P4. GetEventsByIds sans produit cartésien

- **Quoi** : `relationLoadStrategy: 'query'` dans `findByIds` (une requête par relation au lieu de deux `LEFT JOIN` croisés), ou ne pas charger `requirements` pour `GetEventsByIds` si la liste des posts ne s'en sert pas (à vérifier dans la gateway et nativapp : NON VERIFIE).
- **Où** : `postgres-event.repository.ts:55-58` ; relations par défaut dans `event.service.ts:52-55` ; appel dans `ms-event/src/modules/event/utils/events-by-ids.util.ts:25`.
- **Gain** : hydratation de 198 µs à environ 60 à 80 µs pour 20 événements x 3 x 3 (INFERENCE à partir des mesures de la section 3), et lignes transférées par la base divisées par environ (tags x exigences). Ne concerne que les ids absents du cache de la gateway : **1 à 4 % du pod**, gain faible à moyen pour la base. Le profil fourni place l'hydratation TypeORM à environ 6 %.
- **Effort** : 1 à 2 h. **Risque** : faible avec la stratégie `query`. Enlever `requirements` change la réponse : il faut alors une décision. **npm-packages** : oui (domain-event). Migration : non.

### P5. Logs par RPC en `debug`

- **Quoi** : passer en `debug` les lignes `event.query.controller.ts:59`, `:70`, `:79-81` (la dernière fait en plus un `JSON.stringify`), et les lignes semblables de `getEvent` (:49) et des RPC utilisateur. C'est le levier 2.4 du plan, resté non livré.
- **Gain** : pod faible (environ 10 à 20 µs par RPC avec l'écriture synchrone, **1 à 2 %**). Gain réel aussi sur le nœud entier : chaque ligne en moins décharge l'agent Datadog, et le plafond actuel est le CPU du nœud (`04-resultats.md` section 4.3).
- **Effort** : 30 min. **Risque** : moins de visibilité, compensée par les traces à 10 %. **npm-packages** : non. Migration : non.

### P6. Réduire les instrumentations OpenTelemetry

- **Quoi** : `OTEL_NODE_DISABLED_INSTRUMENTATIONS=net,nestjs-core,express,http` (lue par `auto-instrumentations-node` 0.75 : `build/src/utils.js:193-196`, FAIT), ou une liste blanche avec `OTEL_NODE_ENABLED_INSTRUMENTATIONS=grpc,pg,undici,runtime-node`. Il faut garder `grpc` et `pg` pour les traces utiles. Je n'ai pas vérifié si `http` sert à autre chose que la sonde de santé.
- **Où** : `deploy/apps/base/ms-event/deployment.yaml:101-119` (env). Pour l'appliquer à tous les services d'un coup, le faire dans `npm-packages/packages/monitoring/src/tracing.ts:37-51`.
- **Gain** : non mesuré, **2 à 5 %** (INFERENCE : le profil cite l'instrumentation pg ; `nestjs-core` et `net` ajoutent un span et un contexte par appel).
- **Effort** : 30 min (deploy seul). **Risque** : traces moins détaillées. **npm-packages** : non par la variable d'environnement, oui par le code. Migration : non.

### P7. Index composite pour le tri par défaut

- **Quoi** : `CREATE INDEX CONCURRENTLY idx_events_created_at_id_desc ON events ("createdAt" DESC, id DESC)`, pour que le tri `ORDER BY "createdAt" DESC, id DESC` (repository.ts:389-390) sorte entièrement de l'index, sans *Incremental Sort*. Pour le vrai écran de l'application (`statuses=[PUBLISHED]`, `startDateFrom=now`, FAIT `nativapp/src/screens/main/hooks/use-swipe-screen.ts:66-75`), un index partiel `WHERE state = <PUBLISHED>` serait peut-être plus utile.
- **Où** : nouvelle migration `ms-event/src/migrations/domain/`, en suivant `volontariapp-db-migration` (Expand). Comme la migration de 1792300000000 le rappelle (:7-9), `CONCURRENTLY` est refusé sous le mode de transaction par défaut : il faut une stratégie validée.
- **Gain** : faible pour la base tant que le `COUNT` domine. Après P1 : moyen, NON VERIFIE sans EXPLAIN. **Effort** : 2 h. **Risque** : écritures un peu plus lentes. **npm-packages** : non. **Migration** : oui.

### P8. Cache de `GetEventsByIds` dans ms-event

- **Quoi** : un cache borné de 30 s par id, comme `EventLookupService` à la gateway. Deux pods ms-event partageraient les ids manqués par cinq pods de gateway.
- **Invalidation** : ms-event connaît ses écritures (`update`, `changeState`, `updateCover`, `applyCoverResult`, `delete`). Il peut invalider sur le pod qui écrit, mais pas sur l'autre réplica sans bus : il faut donc accepter le même âge de 30 s que la gateway, déjà accepté (`event-lookup.service.ts:20-21`). `currentParticipants` vient de la gateway, pas de ms-event : il n'y a pas de risque sur les compteurs.
- **Gain** : dépend du taux de réussite actuel, non mesuré (`04-resultats.md` section 5) ; INFERENCE de 2 à 5 % du pod. À mesurer avant de construire (compteurs de réussite, étape 2 du plan).
- **Effort** : 2 h. **Risque** : une donnée de plus qui peut vieillir. **npm-packages** : non.

### P9. Mesures secondaires

- **Cache de jetons vérifiés** (clé : jeton, durée : son `exp`) dans `GrpcInternalGuard` : environ 1 % aujourd'hui, utile seulement après la réutilisation des jetons à la gateway. Demande npm-packages (`auth`) et une revue de sécurité.
- **`--max-semi-space-size=32`** au lieu de 16 (`deployment.yaml:110-111`) : moins de scavenges si les allocations restent élevées ; à tester par une mesure, avec une limite mémoire de 256Mi à surveiller. Deploy seul. Gain possible de 2 à 4 % sur les 13,3 % de GC ; P2 et P3 réduisent la source.
- **Requêtes brutes sans hydratation TypeORM** (`getRawMany` + mappage manuel) pour `searchAdvanced` : environ 40 µs pour 20 lignes, effort moyen, gain faible (1 à 2 %). À faire en dernier.
- **À long terme** : garder dans ms-event une projection locale « événements masqués pour un utilisateur », nourrie par les événements de ms-social, et filtrer par anti-jointure SQL. Cela supprime les 2 000 ids par recherche sur toute la chaîne (gateway, ms-social, ms-event, base). C'est un gros chantier d'architecture (données dupliquées, saga), à passer par `grill-me` avant toute décision.

---

## 7. Top 5 classé (gain attendu / effort)

| Rang | Proposition | Gain pod ms-event | Gain ms-event-db | Effort | npm-packages / migration |
| ---: | :--- | :--- | :--- | :--- | :--- |
| 1 | **P1** supprimer le `COUNT` (motif `knownTotal` ou `limit + 1`) | 6 à 8 % | **30 à 60 %** (le plus gros, à confirmer par EXPLAIN) | 2 à 3 h | domain-event (STOP), puis ms-event |
| 2 | **P2** listes en `uuid[]` (`<> ALL`, `= ANY`) | 5 à 10 % (avec le GC) | faible à moyen (analyse) | 1 h | domain-event, même PR que P1 |
| 3 | **P3** retirer `@IsUUID each` sur les listes | 4 à 5 % | aucun | 1 h | ms-event seul |
| 4 | **P4** `GetEventsByIds` sans produit cartésien | 1 à 4 % | faible à moyen | 1 à 2 h | domain-event |
| 5 | **P5 + P6** logs en `debug` et instrumentations OTel réduites | 3 à 7 % au total, plus l'agent Datadog | aucun | 1 h | ms-event + deploy |

Total INFERENCE du top 5 : **environ 20 à 30 % du CPU de ms-event** avec les listes pleines de la rampe, et une baisse forte du CPU de ms-event-db portée par P1. À confirmer avec un vrai profil et un EXPLAIN. Le gain diminue si les listes réelles sont petites : à 2 x 100 ids, P2 et P3 ne rapportent presque plus rien et seul P1 compte.

## 8. Ordre des PR proposé

1. **Mesure** (aucun code) : refaire le profil de ms-event à 225 req/s (section 0) et lancer un EXPLAIN des deux requêtes de la section 2.2 sur une copie de la base avec 2 x 1 000 uuid. Cela confirme ou infirme P1 avant d'écrire du code.
2. **`ms-event` (PR A)** : P3 et P5. Aucune dépendance, livrable tout de suite, puis une mesure.
3. **`deploy` (PR B)** : P6 (`OTEL_NODE_DISABLED_INSTRUMENTATIONS`) pour ms-event seul, puis une mesure avant d'étendre aux autres services.
4. **`npm-packages` (PR C)** : domain-event avec P1 (option `knownTotal` + total en parallèle), P2 et P4 (`relationLoadStrategy: 'query'`), avec changeset. **STOP** : attendre la publication par la CI avant toute modification des consommateurs.
5. **`ms-event` (PR D)** : `yarn up @volontariapp/domain-event`, cache borné du total dans le contrôleur (10 s, clé filtre + utilisateur + hachage des listes), comme ms-post. Puis une mesure.
6. **`ms-event` (PR E, optionnelle)** : migration P7 si l'EXPLAIN d'après P1 montre un tri ou un parcours coûteux ; P8 si les compteurs de réussite du cache de la gateway montrent beaucoup d'ids manqués.

Une mesure par PR (règle « une phase, une mesure » non tenue lors des phases 1 à 3, `04-resultats.md` section 5).

---

## 9. Couverture et limites

- Appelants de `SearchEvents` et `GetEventsByIds` : `analyze_grpc` sur tout le workspace indexé (3 appelants chacun, listés en section 1). Je n'ai pas vérifié les appels construits à l'exécution au-delà du client de service de `worker-ranking`.
- `me` n'appelle pas ms-event : vérifié en lisant `getMe` (`user.query-controller.ts:36-45`), qui n'appelle que `userService.getUser`.
- `is-following` : non relu.
- Taille des listes d'exclusion pendant la rampe, volume de `events`, nombre de tags et d'exigences par événement, plans réels : NON VERIFIE.
- Le banc tourne sur Apple Silicon : les valeurs absolues sont plus basses que sur la VM. Ce sont les rapports qui comptent.
- Scripts jetables : `/private/tmp/claude-501/-Users-victoragahi-Developer-meta/a9f40403-efe3-4c69-84c2-d4eb6c9db0a0/scratchpad/bench/src/bench.ts` et `/private/tmp/claude-501/-Users-victoragahi-Developer-meta/a9f40403-efe3-4c69-84c2-d4eb6c9db0a0/scratchpad/bench/uuid.js` (le dossier `bench/node_modules` est un lien symbolique vers `ms-event/node_modules`).
