# 03 - Plan d'implémentation

Treize lots, chacun de 3 h au plus pour un agent qui connaît le projet. Chaque lot donne le dépôt, les fichiers, le changement, les tests, la règle du STOP, les risques et le retour arrière, et un critère d'acceptation mesurable. Les numéros de ligne sont ceux d'`origin/main` le 2026-11-10 : relire le fichier avant d'éditer.

## Règles communes

- **Règle du STOP** (`AGENTS.md`, section 1) pour tout lot marqué `npm-packages` : `yarn build` et `yarn test` du package, `yarn changeset add` puis `yarn changeset version` une fois par branche, une PR, **arrêt**. Les consommateurs ne sont touchés qu'après la publication par la CI (`npm view @volontariapp/<package>@<version> version --prefer-online` répond), avec `yarn up`, dans une PR par dépôt consommateur. Aucun `as unknown as`, aucun `any`.
- **Tests** : mocks dans `*.mock.ts`, données dans `*.factory.ts`, `jest.spyOn` et `restoreAllMocks()` (`AGENTS.md`, section 3). Les tests d'intégration du package `database` tournent sur la base de test (`yarn db:up`, `packages/database/package.json`).
- **Compter les requêtes dans les tests** : un test d'intégration par lot installe un `logger` TypeORM (ou un `jest.spyOn` sur `QueryRunner.prototype.query`) et vérifie le nombre exact de requêtes d'une opération. C'est le garde-fou contre une régression silencieuse.
- **Aucune E2E en local** : pousser et lire le job CI `e2e / Run End-to-End Tests`.
- **Mesure avant et après** : chaque critère d'acceptation se lit avec les outils du chapitre 02.

---

## L0 - Mesure : `pg_stat_statements`

- **Dépôt** : `deploy`, plus une action du Lead Dev sur le cluster.
- **Fichiers** : `apps/overlays/prod/{ms-post,ms-event,ms-social,ms-user,ms-storage,ms-ranking,ws-service}/db-postgres/kustomization.yaml` (NON VERIFIE : le chemin exact de ws-service ; lister `apps/overlays/prod/*/db-postgres`).
- **Changement** : arguments `-c shared_preload_libraries=pg_stat_statements -c pg_stat_statements.track=top -c pg_stat_statements.max=5000 -c track_io_timing=on` (chapitre 02, section 2). D'abord vérifier que `primary.args` est rendu par `kustomize build --enable-helm`.
- **Tests** : `kustomize build --enable-helm` de chaque overlay, puis `SHOW shared_preload_libraries` après déploiement.
- **STOP** : non concerné.
- **Risques, retour arrière** : redémarrage de chaque base (quelques secondes de coupure), mémoire de la VM. Déployer base par base, hors rampe. Retour : retirer les arguments.
- **Acceptation** : `SELECT count(*) FROM pg_stat_statements` répond dans les sept bases ; `SHOW track_io_timing` vaut `on`.
- **Action du Lead Dev** : `CREATE EXTENSION IF NOT EXISTS pg_stat_statements;` dans chaque base (écriture, interdite aux agents en prod).

## L1 - Rampe d'écriture (besoin)

- **Dépôt** : `traffic-simulator` (refonte en cours, lots L1 à L8 de la rampe, mode `app`, comptes `load.NNNN`).
- **Changement** : les routes, poids et exigences du chapitre 02, section 4. Ce dossier ne prescrit pas le code.
- **Acceptation** : un rapport de rampe donne, par route d'écriture, le débit tenu, le p95 HTTP et le délai bout en bout d'un like ; la base est revenue à son état initial (likes, participations) à la fin.

## L2 - Réveil plus rapide de l'outbox

- **Dépôt** : `deploy`.
- **Fichiers** : `apps/base/{ms-post,ms-event,ms-social,ms-user,ms-storage,ms-ranking}/deployment-outbox.yaml` et `apps/base/ws-service/deployment-outbox.yaml`, variable `OUTBOX_MAX_IDLE_INTERVAL_MS` (`:89-90`, `:71-72` pour ws-service).
- **Changement** : `5000` vers `1000`. Coût : au repos, 14 boucles (événements et jobs dans 7 runners) font au plus 1 claim par seconde, soit 14 transactions par seconde réparties sur 7 bases (INFERENCE, 3 RT chacune).
- **Tests** : aucun test de code ; vérifier le rendu Kustomize.
- **STOP** : non concerné.
- **Risques, retour arrière** : charge de fond un peu plus haute ; remettre `5000`.
- **Acceptation** : p95 du délai de l'outbox (chapitre 02) sous 1,1 s sur ms-ranking (1,63 s mesuré), à trafic comparable. Une version plus fine (LISTEN/NOTIFY sur `event_queue`) est possible plus tard, mais demande une connexion dédiée par runner et un trigger : ne la faire que si la mesure le justifie.

## L3 - Idempotence sur l'id de l'événement (prérequis de L4 et L5)

- **Dépôt** : `npm-packages`, package `post-processors`. **STOP.**
- **Fichiers** : `packages/post-processors/src/core/helpers/redis-stream.helper.ts:108-137`, `core/processors/batch.post-processor.ts:17-110` et `:238-255`, `core/processors/single.post-processor.ts:38-71` et `:183-190`.
- **Changement** :
  1. Clé : `idempotency:post-processor:<groupName>:<eventId>`, où `eventId` est le champ `id` du message (`fields.id`, posé par `outbox/src/pushers/event-queue.pusher.ts:57`, c'est l'id de la ligne `event_queue`). Si `fields.id` est absent ou vide, garder l'id du message Redis.
  2. Deux états au lieu d'un : `SET key processing NX EX <claimMinIdleTimeMs / 1000>` avant le traitement, puis `SET key done EX <idempotencyTtlSeconds>` après le succès, dans le même pipeline que le nettoyage des retries et le XACK. Quand le `SET NX` échoue : si la valeur est `done`, acquitter et sauter (comportement actuel) ; si elle est `processing`, **ne pas acquitter** et ne pas traiter : le message reste en attente et sera repris par le claim une fois le verrou expiré.
  3. Lot : poser les verrous du lot en un seul pipeline (un `SET NX` par entrée), puis lire les réponses ; garder l'ordre des entrées.
  4. Transition : pendant `idempotencyTtlSeconds` (24 h), lire aussi l'ancienne clé (id du message Redis) avant de traiter, pour ne pas retraiter un message déjà traité sous l'ancienne version. Retirer cette lecture dans une version suivante.
- **Tests** : unitaires (mocks Redis dans `redis-call.mock.ts`) : clé sur `fields.id` ; repli sur l'id du message ; `done` acquitte ; `processing` n'acquitte pas ; un lot de 10 fait un seul `exec` de pipeline pour les verrous. Intégration (`redis-stream.helper.int.spec.ts`) : deux messages Redis portant le même `fields.id` ne sont traités qu'une fois ; un verrou `processing` expiré laisse retraiter.
- **Consommateurs après publication** : `yarn up @volontariapp/post-processors` dans les six `post-processor-*` et dans `ws-service`.
- **Risques, retour arrière** : un `processing` trop court laisse deux consommateurs traiter le même message si un traitement dure plus de 60 s (INFERENCE : aucun traitement mesuré si long, géocodage compris ; à vérifier dans Datadog). Retour : revenir à la version précédente du package.
- **Acceptation** : en test d'intégration, 0 double traitement sur 100 messages dupliqués, et 0 message acquitté sans traitement après la mort simulée d'un consommateur ; en prod, les allers-retours Redis de la pose des verrous passent de 10 à 1 par lot de 10 (compteur `cmdstat_set` stable par message, nombre d'appels réseau lu dans les spans Redis de Datadog).

## L4 - Reprise des lignes bloquées et correction de `markAsFailed`

- **Dépôt** : `npm-packages`, packages `database` et `config`. **STOP.** Prérequis : L3 publié et déployé chez tous les post-processors.
- **Fichiers** : `packages/database/src/outbox/runners/outbox.runner.ts` (nouvelle boucle à côté de la purge, `:77-80`, `:114-135`), nouveau `packages/database/src/outbox/reapers/outbox.reaper.ts`, `packages/database/src/outbox/dispatchers/outbox.dispatcher.ts:35-71`, `packages/config/src/...` (type `OutboxRunnerConfig` : relire où il est défini).
- **Changement** :
  1. Reprise, toutes les `reapIntervalMs` (défaut 60 000) :
     ```sql
     UPDATE <table> SET status = 'PENDING', updated_at = NOW()
     WHERE id IN (SELECT id FROM <table>
                  WHERE (status = 'PROCESSING' AND updated_at < NOW() - make_interval(secs => $1))
                     OR (status = 'FAILED' AND attempts < $2 AND updated_at < NOW() - make_interval(secs => $3 * power(2, attempts)))
                  ORDER BY created_at, id LIMIT $4 FOR UPDATE SKIP LOCKED)
     ```
     avec `stuckAfterSeconds` 300, `maxAttempts` 5, `retryBaseSeconds` 30, `limit` 500 (configurables, `OUTBOX_STUCK_AFTER_MS`, `OUTBOX_MAX_ATTEMPTS`). Le claim pose déjà `updated_at = NOW()` (`outbox.consumer.ts:36`). Log `warn` avec le nombre de lignes reprises.
  2. `markAsCompleted` ne modifie l'entité qu'après l'UPDATE réussi ; `markAsFailed` accepte une entité `PROCESSING` ou `COMPLETED` non écrite. Plus simple : `processItems` garde le statut d'origine et passe l'erreur à `markAsFailed` sans dépendre de l'état en mémoire.
  3. Une erreur sur une ligne ne sort plus de la boucle (`outbox.consumer.ts:130-136`) : chaque `markAsFailed` a son propre `try`.
- **Tests** : intégration sur la base de test : une ligne `PROCESSING` vieille de 10 min revient `PENDING` ; une `PROCESSING` de 1 min non ; une `FAILED` avec `attempts = 1` revient après le délai, `attempts = 5` non ; un échec de l'UPDATE de `markAsCompleted` (spy qui lève) laisse les lignes suivantes du lot traitées.
- **Consommateurs** : `yarn up @volontariapp/database @volontariapp/config` dans les sept `outbox-*`, puis les variables dans `deploy` si les défauts ne conviennent pas.
- **Décision du Lead Dev avant le déploiement** : les 147 lignes du 2026-11-07 seront reprises au premier passage. Elles portent des événements vieux de trois jours (`user.created`, `post.created`, `post.liked`, `event.*`). Choisir : les laisser repartir (les post-processors sont censés être idempotents, mais `user.created` refait le nœud Neo4j et le classement), ou les passer à la main en `FAILED` avec `attempts = 99` avant le déploiement. Recommandation : les laisser repartir après lecture de chaque consommateur concerné (`analyze_impact` sur chaque type).
- **Risques, retour arrière** : livraison « au moins une fois » : un message peut être poussé deux fois, d'où L3. Retour : version précédente du package dans les runners.
- **Acceptation** : 0 ligne `PROCESSING` de plus de 5 min et 0 `FAILED` avec `attempts < 5` dans les sept bases, 10 min après le déploiement ; monitor Datadog en place (chapitre 02, section 3).

## L5 - Outbox par lot

- **Dépôt** : `npm-packages`, packages `database` et `outbox`. **STOP.** Prérequis : L3 et L4.
- **Fichiers** : `packages/database/src/outbox/consumers/outbox.consumer.ts:112-149`, `packages/database/src/outbox/dispatchers/outbox.dispatcher.ts`, `packages/database/src/outbox/pushers/outbox.pusher.ts`, `packages/outbox/src/pushers/event-queue.pusher.ts:118-165`, `packages/outbox/src/pushers/jobs-outbox.pusher.ts:67-112`.
- **Changement** :
  1. `OutboxPusher.pushBulkElement` renvoie le résultat par entité (`{ id, error?: Error }[]`) au lieu de lever à la première erreur : pour les événements, lire chaque résultat de `pipeline.exec()` (un ou plusieurs XADD par entité selon `targetServices`) ; pour les jobs, `addBulk` par file (un échec de file marque toutes ses entités).
  2. `processItems` : un seul `pushBulkElement(items)`, puis `UPDATE <table> SET status = 'COMPLETED', updated_at = NOW() WHERE id = ANY($1) AND status = 'PROCESSING'` pour les réussites, et `UPDATE ... SET status = 'FAILED', attempts = attempts + 1, "lastError" = $2 ... WHERE id = ANY($1)` pour les échecs (attention : la colonne s'appelle `"lastError"` en base, chapitre 02).
  3. Traces : `runInTraceContext` est aujourd'hui par ligne (`outbox.consumer.ts:117-129`) ; utiliser `runBatchInTraceContext` (déjà utilisé par `batch.post-processor.ts:122`) pour garder un span par ligne rattaché à sa trace.
  4. Ordre : garder l'ordre `created_at, id` du lot dans le pipeline (`sortByCreation`, `:77-80`).
- **Tests** : intégration : un lot de 50 fait 1 `exec` Redis et 4 requêtes SQL (compteur de requêtes) ; un pipeline où le 10e XADD échoue marque 49 `COMPLETED` et 1 `FAILED` ; l'ordre des XADD suit `created_at`.
- **Consommateurs** : `yarn up @volontariapp/database @volontariapp/outbox` dans les sept `outbox-*`.
- **Risques, retour arrière** : si le runner meurt entre le pipeline et l'UPDATE, tout le lot (jusqu'à 50) est repoussé par L4 au lieu d'une ligne : doublons absorbés par L3 (chapitre 04, section 3). Retour : version précédente.
- **Acceptation** : `pg_stat_statements` : `calls` des requêtes d'`event_queue` par ligne poussée passe d'environ 6 à moins de 0,2 ; `xact_commit` de la base ms-ranking baisse pendant une rampe d'écriture à débit égal.

## L6 - `update()` et `create()` du socle

- **Dépôt** : `npm-packages`, package `database`. **STOP.**
- **Fichiers** : `packages/database/src/core/base.repository.ts:135-166`, tests dans `packages/database/src/test/`.
- **Changement** :
  1. Nouvelle méthode `updateColumns(id, data): Promise<boolean>` : `UPDATE ... SET <colonnes> WHERE <pk> = :id` en une requête, sans transaction, colonnes de relation retirées (comme `updateWhere`, `:168-178`). Renvoie `affected > 0`.
  2. `update(id, data)` garde son contrat (entité avec relations, ou `null`) mais : si `data` ne contient aucune relation, `UPDATE ... RETURNING *` (1 RT) ; 0 ligne : `null` ; sinon relecture avec relations seulement si l'entité en a (`metadata.relations.length > 0`), soit 2 RT au lieu de 6. Si `data` contient une relation (tags d'un événement), garder l'ancien chemin `save`.
  3. `create(data)` : si l'entité porte un id et aucune valeur de relation, `repository.insert(model)` (INSERT `RETURNING` des colonnes générées, 1 RT, pas de transaction) puis `toEntity` du modèle complété ; sinon `save` comme aujourd'hui.
  4. Une aide `fromReturning(raw)` qui convertit une ligne `RETURNING *` (noms de colonnes SQL) en modèle grâce à `metadata.columns` (`databaseName` vers `propertyPath`), réutilisée par L7. Ne pas réutiliser la conversion naïve de `outbox.consumer.ts:82-101`, fausse pour une colonne nommée explicitement (`"emitterId"`).
- **Tests** : intégration : `update()` d'une colonne fait 2 requêtes (1 si l'entité n'a pas de relation) ; `update()` d'un id absent renvoie `null` ; `update()` avec une relation passe par `save` ; `create()` avec id fait 1 requête et lève `23505` sur un id existant ; `updateColumns()` fait 1 requête.
- **Consommateurs** : `yarn up @volontariapp/database` partout (`find_dependents` sur `@volontariapp/database`, granularité `package`, pour la liste).
- **Risques, retour arrière** :
  - `save` ne faisait rien si rien n'avait changé ; un `UPDATE` direct écrit toujours, et **déclenche les triggers** (`events_event_queue_trigger` émet `event.changed` à chaque UPDATE de `events`, chapitre 01, N5). Ajouter à la clause `WHERE` une comparaison `IS DISTINCT FROM` sur les colonnes modifiées, ou documenter que l'appelant ne doit appeler `update()` que s'il change quelque chose. Recommandation : la comparaison.
  - `create()` faisait un upsert implicite si l'id existait ; avec `insert`, il lève. Chercher les appelants qui comptent sur ce comportement (`find_dependents` sur `BaseRepository`, puis lecture). INFERENCE : aucun pour `event_queue` (ids aléatoires).
  - Retour : version précédente du package.
- **Acceptation** : `pg_stat_statements` : la requête `SELECT COUNT(DISTINCT(...))` d'`exists()` disparaît des 20 premières en appels ; une création de post passe de 6 à 4 requêtes en test d'intégration (avec L7).

## L7 - Créations de post et d'événement sans relecture

- **Dépôt** : `npm-packages`, packages `domain-post` et `domain-event`. **STOP.** Peut partir dans la même PR que L6 si le temps le permet, sinon après sa publication.
- **Fichiers** : `packages/domain-post/src/repositories/postgres-post.repository.ts:197-308` ; `packages/domain-event/src/repositories/postgres-event.repository.ts:76-149` ; `packages/domain-post/src/repositories/postgres-comment.repository.ts:48-78` (même schéma, `manager.save` du commentaire puis outbox).
- **Changement** :
  1. Post : construire l'entité depuis `insertedRows[0]` (via `fromReturning` de L6) et les médias insérés (les valeurs sont en main, `:262-268`), supprimer la relecture `:277-280`. L'outbox passe par `create()` de L6 (INSERT direct).
  2. Événement : remplacer `manager.save(fullModel)` (`:112-119`) par un INSERT multi-lignes dans `event_tags` (`"eventsId"`, `"tagsId"`, schéma dans `ms-event/src/migrations/domain/1776008237420-InitialSchema.ts:25`) et dans `event_requirements` (relire le schéma dans la même migration). Construire l'entité depuis `RETURNING` et les tags validés (`event.service.ts:88-90` les a déjà lus), supprimer la relecture `:121-124`.
  3. Le chemin d'idempotence (`insertedRows.length === 0`) garde sa lecture : il est rare.
- **Tests** : intégration dans chaque package : nombre de requêtes d'une création (post sans média : 4 ; événement sans tag : 4 ; avec 2 tags et 1 exigence : 6) ; l'entité renvoyée est égale à celle d'une lecture (`findById` avec relations) ; les triggers `event_tags` ont bien écrit 2 lignes `event_queue`.
- **Consommateurs** : `yarn up` dans `ms-post`, `ms-event`, et les post-processors qui importent ces domaines (`find_dependents` granularité `package`).
- **Risques, retour arrière** : une colonne calculée par la base absente de l'entité construite (valeurs par défaut) : `RETURNING *` les contient, c'est pourquoi on part de lui. Retour : version précédente.
- **Acceptation** : `POST /posts` sans média : 4 requêtes SQL (pg_stat_statements pendant une rampe, ou test d'intégration) ; p95 de `CreatePost` côté ms-post en baisse dans Datadog à débit égal.

## L8 - Saga et succès de job par lot

- **Dépôts** : `npm-packages` (`domain-event`, `post-processors`) **STOP**, puis `post-processors-runner`.
- **Fichiers** : nouvelle méthode `updateSagaStatusMany(ids, status)` dans `packages/domain-event/src/repositories/postgres-event.repository.ts` ; `post-processor-event/src/post-processors/event-creation-successfull.post-processor.ts:39-76` et `event-creation-failed.post-processor.ts` ; `packages/post-processors/src/common/job-outbox-success.post-processor.ts:51-58` (et `job-outbox-failed.post-processor.ts`, même schéma à vérifier).
- **Changement** :
  1. `UPDATE events SET saga_status = $2 WHERE id = ANY($1) AND saga_status IS DISTINCT FROM $2` : une requête par lot, et pas d'`event.changed` inutile pour un événement déjà au bon statut.
  2. Succès de job : supprimer le `exists()` (COUNT) ; le `DELETE` et son `affected` (`:80-88`) disent déjà si la ligne existait. Garder le log d'erreur quand `affected === 0`.
  3. NON VERIFIE à trancher en lisant le code : `job-outbox-success` traite les messages d'un lot en `Promise.all`, chacun avec sa transaction ; un échec fait rejouer tout le lot. C'est acceptable avec L3, mais à noter.
- **Tests** : unitaires (spies sur le repository) : un lot de 10 fait un seul appel ; intégration : un événement déjà `DONE` ne produit pas de `event.changed`.
- **Risques, retour arrière** : un `eventId` invalide dans le lot fait échouer la requête entière (uuid mal formé) : filtrer les ids non uuid avant, et les journaliser. Retour : versions précédentes.
- **Acceptation** : pour 10 événements créés, `pg_stat_statements` montre 1 UPDATE de saga au lieu de 10 × 6 requêtes.

## L9 - ms-social : une requête Cypher et l'outbox atomique

- **Dépôt** : `npm-packages`, package `domain-social`. **STOP.** Consommateur : `ms-social`.
- **Fichiers** : `packages/domain-social/src/services/interaction.service.ts:41-127`, `services/participation.service.ts:163-330` (participation, départ, souhait, retrait), `services/relationship.service.ts:26-60`, `repositories/neo4j-interaction.repository.ts`, `repositories/neo4j-participation.repository.ts`, `repositories/neo4j-relationship.repository.ts`, `repositories/base/neo4j-base.repository.ts:58-67` (une variante `writeReturning` qui renvoie les enregistrements).
- **Changement** :
  1. Like en une requête, qui dit si elle a créé :
     ```cypher
     MATCH (u:SocialUser {userId: $userId})
     MATCH (p:SocialPost {postId: $postId})
     MERGE (u)-[r:LIKE]->(p)
     ON CREATE SET r.createdAt = $now
     RETURN r.createdAt = $now AS created
     ```
     Aucune ligne : l'utilisateur ou le post n'existe pas dans le graphe (aujourd'hui le `MERGE` ne fait rien et `post.liked` part quand même). `created = false` : `SOCIAL_RELATIONSHIP_ALREADY_EXISTS`. Même schéma pour l'unlike (`DELETE r RETURN count(r)`), le follow, le souhait, la participation (une requête qui vérifie l'événement, supprime le souhait éventuel et crée la participation, et renvoie ce qu'elle a trouvé).
  2. Atomicité (chapitre 04, section 2) : ouvrir la transaction Postgres, insérer la ligne `event_queue`, faire l'écriture Neo4j, puis `COMMIT`. Si Neo4j échoue ou renvoie `created = false` : `ROLLBACK`. Si le `COMMIT` échoue après Neo4j : compenser (supprimer le like dans Neo4j), journaliser en `error`, renvoyer l'erreur. Supprimer les `catch` qui avalent l'erreur d'outbox (`interaction.service.ts:70-74`, `:114-118`, `participation.service.ts:293-297` et le retrait du souhait).
- **Tests** : unitaires avec mocks Neo4j et repository (`*.mock.ts`) : like créé, déjà existant, nœud absent ; Postgres en échec avant Neo4j (aucune écriture Neo4j) ; Neo4j en échec (rollback, aucune ligne `event_queue`) ; commit en échec (compensation appelée). Intégration avec Neo4j de test si le package en a une (NON VERIFIE).
- **Risques, retour arrière** : la compensation peut elle-même échouer (fenêtre très courte, journalisée) ; la transaction Postgres reste ouverte pendant l'appel Neo4j (quelques ms, INFERENCE) et tient une connexion du pool. Retour : version précédente.
- **Acceptation** : like : 1 session Neo4j et 3 requêtes SQL (BEGIN, INSERT, COMMIT) ; participation : 1 session ; aucun `warn` « Failed to push POST_LIKED » possible (le code n'existe plus) ; en test, 0 like sans ligne `event_queue` sur 1 000 essais avec des pannes injectées.

## L10 - Pool de connexions

- **Dépôts** : `npm-packages` (`bridge`, peut-être `config`) **STOP**, puis les six `ms-*`, puis `deploy`.
- **Fichiers** : `packages/bridge/src/providers/postgres.provider.ts:13-18` ; dans chaque `ms-*`, `src/providers/database/database.module.ts` (`TypeOrmModule.forRoot`).
- **Changement** :
  1. `PostgresProvider` passe `poolSize: options.maxPoolSize` à TypeORM (T4, chapitre 01) et retire `maxPoolSize` des options transmises.
  2. Chaque `TypeOrmModule.forRoot` passe `poolSize: dbConfig.maxPoolSize`.
  3. Le DataSource du health-check (`PostgresBridgeModule.register`) prend `poolSize: 1`, ou le health-check lit le DataSource de TypeORM (plus propre, mais change `health-check-nest` : NON VERIFIE).
  4. Budget, à écrire dans le dossier `deploy` : pour chaque base, somme des `replicas × poolSize` des clients (ms, outbox, post-processor, worker) inférieure à 80 sur 100 (`max_connections`). Exemple ms-event aujourd'hui : 2 pods × (10 + 1) + 10 + 10 + 10 = 52 (INFERENCE sur les pools des runners, qui passent aussi par `PostgresProvider`).
- **Tests** : unitaire du provider : `poolSize` transmis ; en prod, `SELECT count(*) FROM pg_stat_activity` sous rampe ne dépasse pas le budget.
- **Risques, retour arrière** : un pool trop petit fait attendre les requêtes sous charge ; garder 10 par défaut, ne changer que par variable `DB_MAX_POOL_SIZE` (déjà déclarée, `ms-event/config/custom-env-vars.json:8`). Retour : version précédente.
- **Acceptation** : `DB_MAX_POOL_SIZE=5` sur un service se lit dans `pg_stat_activity` (au plus 5 connexions de ce pod) pendant une rampe.

## L11 - L'écriture à la lecture de ms-ranking

- **Dépôts** : `npm-packages` (`domain-ranking`) **STOP**, puis `ms-ranking`.
- **Fichiers** : `packages/domain-ranking/src/repositories/postgres-ranking-request.repository.ts:35-60` ; `ms-ranking/src/modules/ranking/services/ranking-job.service.ts:31-72` ; `ranking-read.service.ts:120-133`.
- **Changement** :
  1. Une seule requête pour la demande et son job : un `WITH r AS (INSERT INTO ranking_request ... ON CONFLICT ... RETURNING ...) INSERT INTO jobs_outbox (...) SELECT ... FROM r WHERE r.needs_job RETURNING id`, en autocommit : 1 RT au lieu de 3 à 5.
  2. **Décision à prendre avant** : une lecture périmée doit-elle réécrire `requested_at` à chaque fois ? `completeRequest` compare `startedAt` et `requested_at` pour décider d'un calcul de suivi (`request-sql.js`, à relire). Option : ne réécrire que si `requested_at` a plus de N secondes (`ON CONFLICT ... DO UPDATE ... WHERE r.requested_at < EXCLUDED.requested_at - interval`), ce qui supprime la plupart des 5,3 millions d'UPDATE. Risque : manquer une demande arrivée pendant un calcul. À trancher par le Lead Dev, avec `docs/matching`.
- **Tests** : intégration du repository : nombre de requêtes (1), `needsJob` identique à l'ancien chemin sur les cas existants (nouvelle demande, demande récente, `force`).
- **Acceptation** : `n_tup_upd` de `ranking_request` par lecture de liste périmée mesuré pendant une rampe, avant et après.

## L12 - Compteurs de badges et concurrence des workers

- **Dépôts** : `post-processors-runner` (`post-processor-user`), `workers-runners`, `deploy`. Pas de STOP (aucun package partagé), sauf si l'équipe décide de déplacer `BadgeEvaluator` dans un domaine.
- **Fichiers** : `post-processor-user/src/core/services/badge-evaluator.service.ts:408-429` ; `worker-{event,user,social,post,storage}/src/workers/*.worker.ts` (`@Processor(...)`).
- **Changement** :
  1. `incrementCounter` : `INSERT INTO badge_progress (user_id, metric, value) VALUES ($1, $2, 1) ON CONFLICT (user_id, metric) DO UPDATE SET value = badge_progress.value + 1 RETURNING value` (NON VERIFIE : la contrainte unique `(user_id, metric)` existe ; lire la migration de `badge_progress` dans `ms-user`).
  2. Workers : `@Processor(Queue.X, { concurrency: config.worker.concurrency })`, variable par worker, défaut 1 (aucun changement de comportement), puis monter à 2 ou 4 dans `deploy` worker par worker, après lecture des handlers (ordre des jobs d'un même utilisateur, verrous).
- **Tests** : intégration du compteur (deux incréments simultanés donnent 2) ; unitaire de la lecture de la concurrence.
- **Acceptation** : compteur : 1 requête au lieu de 3 ; workers : file BullMQ vidée plus vite sous rampe (`waiting` dans Redis), sans hausse des `FAILED` de `job_audit`.
