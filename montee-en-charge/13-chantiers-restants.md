# 13 - Chantiers restants : ce qui est fait, ce qui reste, comment le faire

État au 2026-11-10 vers 18:00 (UTC). Ce document remplace la liste « Reste à faire » des chapitres [10](10-suites.md) et [11](11-passation.md) : il donne, chantier par chantier, l'état exact, les étapes dans l'ordre, les fichiers, les commandes et le critère d'acceptation. Il est écrit pour qu'un agent ou un membre de l'équipe puisse reprendre un chantier sans relire toute la session.

Deux numérotations coexistent et ne se recoupent pas :
- **R1 à R8** : les lots de la rampe réaliste (chapitre 10, section 2) ; ils s'appellent L1 à L8 dans ce chapitre 10.
- **E0 à E12** : les lots d'optimisation des écritures (dossier [`optimisation-ecritures/`](../optimisation-ecritures/README.md), chapitre 03) ; ils s'appellent L0 à L12 dans ce dossier.

## 0. Vue d'ensemble

| # | Chantier | État | Bloqué par | Charge estimée |
| :--- | :--- | :--- | :--- | :--- |
| 1 | Fin du correctif des E2E aléatoires | en cours (2 PR ouvertes ou à ouvrir) | rien | 30 min |
| 2 | Les 6 `event.finished` bloqués du 2026-11-07 | décision à prendre | rien | 10 min |
| 3 | Rampe R8, puis rampe réaliste vers 300 req/s | à faire | 1 conseillé | 3 h |
| 4 | E9 phase 2 : ms-social « Postgres d'abord » en `async` | à faire | rien | 2 à 3 sessions |
| 5 | E5 : outbox par lot | à faire | rien (E3, E4 en prod) | 3 h |
| 6 | E11 : écriture à la lecture de ms-ranking | décidé (B puis A), à faire | rien | 3 h |
| 7 | E6 et E7 : socle `update()` / `create()`, créations sans relecture | à faire | rien | 2 PR de 3 h |
| 8 | E8 : saga et succès de job par lot | à faire | rien | 2 h |
| 9 | E10 : taille réelle du pool de connexions | à faire | rien | 2 h |
| 10 | E12 : compteurs de badges et concurrence des workers | à faire quand la mesure le justifie | 3 | 2 h |
| 11 | Skills `meta` : leçons du 2026-11-10 | à faire | rien | 45 min |
| 12 | Dettes et vérifications avant lancement | à suivre | rien | variable |

Ordre conseillé : 1, 2, 3 (elle donne la mesure de référence), puis 5 et 6 en parallèle (packages différents : `database`/`outbox` et `domain-ranking`), puis 4, puis 7 à 10.

## Règles valables pour tous les chantiers

- **Règle du STOP** (`AGENTS.md`, section 1) : tout changement dans `npm-packages` se fait seul dans sa PR, puis arrêt jusqu'à la publication par la CI (`npm view @volontariapp/<paquet>@<version> version --prefer-online` doit répondre), puis `release` du verrou par le Lead Dev, puis les consommateurs dans une PR par dépôt. Un agent qui édite `npm-packages` pose le verrou pour **toute la session** : ne pas lancer en parallèle un agent sur un consommateur.
- **Fusions** : c'est Victor qui fusionne (`gh pr merge <n> --repo Volontariapp/<repo> --squash --delete-branch --admin`). La protection de branche exige une revue ; l'auteur ne peut pas s'approuver.
- **CI** : poser le label `docker-and-e2e` pour construire l'image et lancer les E2E, puis relancer la CI avec `scripts/pr-retrigger.sh <repo>#<n>` (le label seul ne relance rien ; fermer et rouvrir la PR marche aussi mais notifie tout le monde). Aucune E2E en local.
- **Poste de Victor** : jest avec `--no-watchman` ; dans un worktree, eslint et jest depuis la racine du worktree ; supprimer les worktrees fusionnés (un `node_modules` par worktree, le disque a saturé le 2026-11-10).
- **Prod** : pas de vrais utilisateurs (décision du 2026-11-10, à revérifier avant le lancement). Éviter les minutes :00, :15, :30, :45 (`ms-storage-purge`). Les requêtes SQL d'écriture en prod sont faites par Victor ; le classifieur de permissions refuse aussi certaines lectures SQL et `requeue --apply` à l'agent.
- **Modèle d'agent** : Haiku pour les montées de version et l'exploitation (`yarn up`, déploiement, vérifications) ; Sonnet pour le code de concurrence ou de cohérence.

---

## 1. Fin du correctif des E2E aléatoires

**Cause (diagnostic du 2026-11-10)** : sur le runner CI partagé, les lectures Neo4j de ms-social dépassent deux limites de prod. Le délai gRPC de la gateway (2 s) donne des 504 ; le timeout de transaction Neo4j (1,8 s, `domain-social` 0.20.0) donne des 500 `transaction has not completed within the timeout`.

**Fait** :
- ci-tools#77 (fusionnée) : `GRPC_READ_DEADLINE_MS: "15000"` sur `api-gateway` dans `docker-compose.yml`. Les 3 dépôts runners pointent sur ce commit (`43070bf`).
- npm-packages#323 (fusionnée, publiée) : `domain-social` 0.22.0 lit `NEO4J_READ_TRANSACTION_TIMEOUT_MS` à chaque lecture (défaut 1800 ms, prod inchangée). `READ_TRANSACTION_CONFIG` est remplacé par `readTransactionConfig()` (aucun importeur trouvé, mesh-mcp sur toutes les racines et `git grep` dans 12 dépôts).

**Reste** (un agent Haiku a été lancé le 2026-11-10 vers 18:00 ; vérifier ses PR) :
1. **ms-social** : `yarn up @volontariapp/domain-social@0.22.0`, label `docker-and-e2e`, CI verte, fusion. L'image `ms-social:latest` est reconstruite par la CI de `main` ; c'est elle que le compose E2E tire.
2. **ci-tools** : `NEO4J_READ_TRANSACTION_TIMEOUT_MS: "10000"` dans l'`environment` du service `ms-social` de `docker-compose.yml` (vers la ligne 576), avec un commentaire comme celui de `GRPC_READ_DEADLINE_MS`. Valider par `docker compose -f docker-compose.yml config`. Fusion **après** le point 1.

**Acceptation** : 5 runs E2E de suite verts dans les dépôts runners, sans `transaction has not completed within the timeout` dans l'artifact `e2e-diagnostics` (`gh run download <id> --repo Volontariapp/<repo>`).

**Non expliqué** : un 500 sur `POST participate` (outbox-runners#49), qui est une écriture. Si le symptôme revient après le point 2, lire le journal de ms-social dans l'artifact de ce run.

## 2. Les 6 `event.finished` bloqués du 2026-11-07

**Fait** : 131 des 137 lignes bloquées (statut `PROCESSING` ou `FAILED`, créées avant 2026-11-07 16:00) ont été rejouées avec `requeue` et traitées : `post.liked` 35, `user.created` 53, `event.created` 8, `post.created` 15, `event.changed` 14, `ranking:job:outbox:success` 6. Aucune erreur des consommateurs, sauf un timeout de 5 s du géocodage OpenStreetMap dans `post-processor-event` (non suivi).

**Reste** : 6 lignes `event.finished` dans la base de ms-event. Leurs consommateurs : `post-processor-ranking`, les badges et le score d'impact de `post-processor-user`. Risque : si un consommateur les avait déjà traitées avant le blocage, le rejeu crédite une deuxième fois (l'idempotence E3 ne le voit pas : avant 3.7.0, la clé était l'id du message Redis). Les points sont désactivés en prod (mémoire du 2026-11-06) : seul le badge est en jeu, sur des comptes du simulateur.

Décision de Victor : les rejouer ou les laisser. Les laisser est sans effet : elles ont plus de 15 min, la reprise automatique ne les touchera jamais.

```bash
kubectl -n prod exec deploy/outbox-event -- node node_modules/@volontariapp/database/dist/cli/requeue.js --table event_queue --status PROCESSING,FAILED --created-before 2026-11-07T16:00:00Z --type event.finished
kubectl -n prod exec deploy/outbox-event -- node node_modules/@volontariapp/database/dist/cli/requeue.js --table event_queue --status PROCESSING,FAILED --created-before 2026-11-07T16:00:00Z --type event.finished --apply --reason "replay 2026-11-07 incident"
```

Piège : lancer un `kubectl exec` à la fois. Enchaînés dans une boucle, ils ont échoué au hasard (`failed to start exec`) le 2026-11-10.

## 3. Rampe R8, puis rampe réaliste vers 300 req/s

**Fait** : R1 à R7 fusionnés (traffic-simulator#11 à #16, meta#61) ; mode `app` validé à 10 req/s en lecture seule (0 erreur, 16 routes). Skill `volontariapp-load-ramp` à jour (scripts `record-ramp.sh`, `async-recorder.sh`, accéléré par meta#63).

**Ce que la rampe prouve** : que la gateway encaisse N requêtes HTTP par seconde avec un mélange proche de l'application (88 % de lectures sur 16 routes, environ 11 % d'écritures), et que les effets asynchrones suivent (délai écriture vers WebSocket, p95 sous 30 s, moins de 2 % perdus). Exclus : connexions WebSocket, position, création d'événement, upload.

**Étapes** :
1. Préparation : simulateur de fond à 0 réplica (`kubectl -n prod scale deploy/traffic-simulator --replicas=0`, et ne pas fusionner deploy#66 avant la fin), `yarn --cwd traffic-simulator load:setup`, lancer `record-ramp.sh` et `async-recorder.sh` (dossier `.agents/skills/volontariapp-load-ramp/scripts/` de meta). Prévenir ou mettre en sourdine les monitors Datadog.
2. **R8** : paliers de 10, 25 puis 50 req/s, avec les écritures qui produisent un message WebSocket, sinon la sonde ne mesure rien :
   ```bash
   LOAD_MODE=app LOAD_WRITES=default,like-toggle,comment-cycle LOAD_STEPS="10,25,50" LOAD_STEP_SECONDS=90 LOAD_RAMP_UP_SECONDS=10 LOAD_WARMUP_SECONDS=10 LOAD_CONFIRM=false yarn --cwd traffic-simulator load
   ```
   À lancer avec les variables de `nativapp/.env` (`set -a && source nativapp/.env && set +a`, `LOAD_BASE_URL="$API_GATEWAY_URL"`, `ulimit -n 10240`), sans afficher les secrets.
3. Après R8 : `yarn --cwd traffic-simulator load:cleanup`, puis `load:cleanup --dry-run` doit compter 0. `async.log` : 0 entrée de DLQ, retard revenu à 0.
4. **Rampe vers 300** :
   ```bash
   LOAD_MODE=app LOAD_WRITES=default,like-toggle,comment-cycle LOAD_STEPS="100,150,200,250,275,300" LOAD_STEP_SECONDS=90 LOAD_RAMP_UP_SECONDS=10 LOAD_WARMUP_SECONDS=10 LOAD_ONSET_SECONDS=10 LOAD_CONFIRM=false yarn --cwd traffic-simulator load
   ```
   Entre deux paliers, attendre un retard asynchrone nul (une écriture lente remplit l'outbox après la fin du palier).
5. Relever `pg_stat_statements` (en prod depuis E0) avant et après la rampe, base par base : c'est la mesure de référence des lots E5 à E12. Requête dans `optimisation-ecritures/02-mesure.md`, section 2.
6. Écrire les résultats dans un chapitre 14 de ce dossier. Ne pas les comparer aux chiffres du chapitre 08 (mélange de 4 routes, autre charge).

**Acceptation de R8** : 0 erreur HTTP, sonde WebSocket p95 sous 30 s et 0 perdu, nettoyage à 0, DLQ vide.

**Pièges** : les comptes neufs reçoivent un 206 du ranking et déclenchent un calcul (chauffer les listes avant de mesurer) ; ws-service diffuse chaque like à tous les clients connectés (`broadcastExcept`) ; les comptes `load.NNNN` gagnent des badges et apparaissent au classement (pas de marqueur « compte synthétique », dette 12).

## 4. E9 phase 2 : ms-social « Postgres d'abord » en `async`

**Fait (phase 1, en prod le 2026-11-10)** : paquets npm-packages#321 (`messaging` 2.35.0, `outbox` 0.11.0, `database` 3.14.0, `domain-social` 0.21.0) ; ms-social#78 (migration `social_edge`, double écriture en `sync` après chaque écriture Neo4j, nettoyage par `DeleteUserNode`, `DeletePostNode`, `DeleteEventNode`) ; backfill de 135 810 lignes, relecture à vide à 0 manquante ; worker-social (workers-runners#65, handler `SOCIAL_EDGE_APPLY`, concurrence 4, 100 jobs/s) ; outbox-runners#49 (options de livraison par type de job : 12 tentatives pour `SOCIAL_EDGE_APPLY`).

**Étape 4.1, paquet `domain-social` (STOP)** : le ticket du [chapitre 12](12-ticket-l9-prerequis-async.md), en entier :
- nettoyer `social_edge` dans `SocialUserService.purgeUser`, `ParticipationService.deleteEventsBatch` et `PublicationService.deletePosts` (6 appelants dans `post-processor-social`, compensations comprises ; refaire la recherche avec `analyze_impact` sur `user.deleted`, `event.deleted`, `post.deleted` sur toutes les racines) ;
- supprimer les cinq `catch` qui avalent l'erreur d'outbox (`interaction.service.ts` : `likePost`, `unlikePost` ; `participation.service.ts` : `wishEvent`, `unwishEvent`, `pushAttendanceSet`) ;
- copier la migration `CreateSocialEdge` dans `packages/domain-social/src/test/migrations/domain/`.

**Étape 4.2, consommateurs** : `yarn up @volontariapp/domain-social` dans `post-processors-runner/post-processor-social` et dans ms-social.

**Étape 4.3, ms-social, recâblage derrière le réglage** : quand `socialWriteMode` vaut `async`, les contrôleurs de commande (`interaction`, `relationship`, `participation`) appellent `SocialEdgeIntentService` (`likePost`, `unlikePost`, `followUser`, `unfollowUser`, `wishEvent`, `unwishEvent`, `participateEvent`, `leaveEvent`) au lieu des services Neo4j et du miroir. Aujourd'hui, `async` ne fait que journaliser un avertissement (ms-social#78). Le blocage (`PostBlockUser`) reste synchrone. Les erreurs à garder identiques côté gRPC : 409 si le lien existe, 404 si le post ou l'événement n'existe pas (chapitre 06 d'`optimisation-ecritures`, section 2).

**Étape 4.4, nativapp** : rien d'obligatoire avec la variante retenue (l'événement part après Neo4j, écrit par le worker). Vérifier sur appareil qu'un like ne « clignote » pas (`likedByMe` repasse à faux puis à vrai) : `useNotificationHandlers.ts` invalide `likes-summary` à la réception de `POST_LIKED`.

**Étape 4.5, bascule** : `SOCIAL_WRITE_MODE=async` dans `deploy` (variable déjà liée dans `ms-social/config/custom-env-vars.json`), en dehors d'une rampe. Retour arrière : repasser à `sync` ; la table et le graphe restent justes, les jobs en vol convergent.

**Étape 4.6, contract** : une fois `async` stable une semaine, supprimer le chemin `sync`, `SocialEdgeMirrorService` et l'ancien code d'écriture Neo4j des contrôleurs.

**Acceptation** :
- like : 0 session Neo4j sur le chemin synchrone, 3 requêtes SQL (BEGIN, INSERT, COMMIT) ;
- `SOCIAL_EDGE_APPLY` : file BullMQ vide après une rampe, 0 en DLQ ;
- `post.liked` reçu par la sonde WebSocket de la rampe, p95 sous 30 s ;
- après suppression d'un utilisateur, d'un post ou d'un événement, plus aucune ligne de `social_edge` ne le cite.

**Non vérifié** : `SetEventAttendance` sur une participation pas encore appliquée (fenêtre de quelques secondes, INFERENCE) ; `event.finished` lit les participants dans Neo4j (`badge-evaluator.service.ts:173-181`) et peut manquer une participation de dernière seconde.

## 5. E5 : outbox par lot

**Fait** : prérequis en prod. E3 (idempotence sur l'id de l'événement, `post-processors` 3.7.0) et E4 (reprise des lignes bloquées, `database` 3.15.0, `config` 3.6.0, dans les 7 `outbox-*` depuis outbox-runners#49).

**À faire** (spec complète : `optimisation-ecritures/03-plan-d-implementation.md`, section L5) :
1. `npm-packages`, packages `database` et `outbox` (STOP) :
   - `OutboxPusher.pushBulkElement` renvoie un résultat par entité (`{ id, error?: Error }[]`) au lieu de lever à la première erreur. Événements : lire chaque résultat de `pipeline.exec()` (un ou plusieurs XADD par entité selon `targetServices`). Jobs : `addBulk` par file, un échec de file marque toutes ses entités.
   - `processItems` (`packages/database/src/outbox/consumers/outbox.consumer.ts`) : un seul `pushBulkElement(items)`, puis un `UPDATE ... SET status = 'COMPLETED' ... WHERE id = ANY($1) AND status = 'PROCESSING'` pour les réussites et un pour les échecs (`attempts = attempts + 1`, colonne `"lastError"` entre guillemets).
   - Traces : `runBatchInTraceContext` au lieu de `runInTraceContext` par ligne.
   - Garder l'ordre `created_at, id` du lot.
   - **Attention à E4** : le correctif de `markAsCompleted` / `markAsFailed` d'E4 (l'entité n'est modifiée qu'après l'UPDATE réussi) doit rester vrai dans la version par lot.
2. Consommateurs : `yarn up @volontariapp/database @volontariapp/outbox` dans les 7 `outbox-*` (un `yarn.lock` par runner ; vérifier une seule version de `database`, `config`, `messaging`, `bridge`, `health-check` dans chaque lock).

**Tests** : intégration. Un lot de 50 fait 1 `exec` Redis et 4 requêtes SQL (compteur sur `QueryRunner.prototype.query`) ; un pipeline dont le 10e XADD échoue marque 49 `COMPLETED` et 1 `FAILED` ; l'ordre des XADD suit `created_at`.

**Acceptation** : `pg_stat_statements` : `calls` des requêtes d'`event_queue` par ligne poussée passe d'environ 6 à moins de 0,2 ; `xact_commit` de la base de ms-ranking baisse pendant une rampe à débit égal.

**Risque** : si le runner meurt entre le pipeline et l'UPDATE, tout le lot (jusqu'à 50 lignes) est repoussé par la reprise E4 : doublons absorbés par E3. Retour arrière : version précédente des paquets dans les runners.

## 6. E11 : l'écriture à la lecture de ms-ranking

**Décision prise** (vaut décision de Victor, chapitre 11) : option **B puis A** du chapitre 07 d'`optimisation-ecritures`.
- **B** : pour la raison `STALE_REFRESH` seulement, une lecture ne réécrit pas une demande ouverte : `ON CONFLICT ... DO UPDATE ... WHERE r.job_enqueued_at <= now() - ttl`, sinon `DO NOTHING`. Les raisons de données (`IMMEDIATE_REASONS`, événements) gardent la réécriture.
- **A** : la demande et son job en une requête, `WITH r AS (INSERT INTO ranking_request ... ON CONFLICT ... RETURNING ...) INSERT INTO jobs_outbox (...) SELECT ... FROM r WHERE r.needs_job RETURNING id`, en autocommit (1 aller-retour au lieu de 3 à 5).

**Étapes** :
1. Avant de coder, relire dans ms-ranking la liste exacte de `IMMEDIATE_REASONS` et des raisons émises par les post-processors de ranking (non vérifié par le chapitre 07), et `completeRequest` (`request-sql.js`) qui compare `startedAt` et `requested_at`.
2. `npm-packages`, package `domain-ranking` (STOP) : `packages/domain-ranking/src/repositories/postgres-ranking-request.repository.ts`. N'oublier aucune colonne NOT NULL de `jobs_outbox` (`scheduled_at` est NOT NULL, piège trouvé sur E9).
3. ms-ranking : `yarn up`, adapter `ranking-job.service.ts` et `ranking-read.service.ts`.

**Tests** : intégration du repository. 1 requête ; `needsJob` identique à l'ancien chemin pour une nouvelle demande, une demande récente et `force` ; une lecture périmée pendant un calcul ouvert ne crée ni UPDATE ni job.

**Acceptation** : pendant une rampe de lecture, `n_tup_upd` de `ranking_request` par lecture périmée et le nombre de jobs de suivi (`markFollowUpSql`) baissent à débit égal, sans hausse du délai de fraîcheur des listes (mesure à définir avec `docs/matching`, chapitres 13 et 14). Mesure de départ : 5,3 millions d'UPDATE pour 67 000 lignes.

## 7. E6 et E7 : socle `update()` / `create()`, créations sans relecture

Spec : `optimisation-ecritures/03-plan-d-implementation.md`, sections L6 et L7. Deux PR `npm-packages` (ou une seule si le temps le permet), STOP.

**E6, package `database`** :
- `updateColumns(id, data): Promise<boolean>` : un `UPDATE` direct, sans transaction.
- `update(id, data)` : `UPDATE ... RETURNING *` quand `data` n'a pas de relation (2 allers-retours au lieu de 6 ; 1 si l'entité n'a pas de relation) ; chemin `save` gardé si `data` contient une relation.
- `create(data)` : `repository.insert` quand l'entité porte un id et aucune relation.
- `fromReturning(raw)` : conversion d'une ligne `RETURNING *` en modèle par `metadata.columns` (pas la conversion naïve de `outbox.consumer.ts`, fausse pour `"emitterId"`).
- **Piège principal** : un `UPDATE` direct déclenche toujours les triggers, alors que `save` ne faisait rien sans changement (`events_event_queue_trigger` émet `event.changed` à chaque UPDATE de `events`). Ajouter `IS DISTINCT FROM` sur les colonnes modifiées dans le `WHERE`.
- **Second piège** : `create()` faisait un upsert implicite sur un id existant ; `insert` lève `23505`. Chercher les appelants qui en dépendent (`find_dependents` sur `BaseRepository`, puis lecture).

**E7, packages `domain-post` et `domain-event`** :
- Post : construire l'entité depuis `insertedRows[0]` (via `fromReturning`) et supprimer la relecture.
- Événement : INSERT multi-lignes dans `event_tags` (`"eventsId"`, `"tagsId"`) et `event_requirements` au lieu de `manager.save(fullModel)`, puis supprimer la relecture.
- Commentaires : même schéma.

**Acceptation** : `POST /posts` sans média en 4 requêtes SQL ; événement sans tag en 4, avec 2 tags et 1 exigence en 6 ; la requête `SELECT COUNT(DISTINCT(...))` d'`exists()` sort des 20 premières de `pg_stat_statements`.

**Consommateurs** : `@volontariapp/database` est importé presque partout (`find_dependents` granularité `package` pour la liste exacte) : prévoir une PR par dépôt, idéalement par un agent Haiku par dépôt.

## 8. E8 : saga et succès de job par lot

Spec : section L8 du plan. `npm-packages` (`domain-event`, `post-processors`, STOP), puis `post-processors-runner`.
- `updateSagaStatusMany(ids, status)` : `UPDATE events SET saga_status = $2 WHERE id = ANY($1) AND saga_status IS DISTINCT FROM $2` (une requête par lot, pas d'`event.changed` inutile). Filtrer et journaliser les ids qui ne sont pas des uuid avant la requête.
- Succès de job (`job-outbox-success.post-processor.ts`) : supprimer le `exists()` ; le `DELETE` et son `affected` disent déjà si la ligne existait.
- Acceptation : pour 10 événements créés, 1 UPDATE de saga au lieu de 10 × 6 requêtes.

## 9. E10 : taille réelle du pool de connexions

Spec : section L10 du plan. `npm-packages` (`bridge`, STOP), puis les 6 `ms-*`, puis `deploy`.
- `PostgresProvider` (`packages/bridge/src/providers/postgres.provider.ts`) passe `poolSize: options.maxPoolSize` à TypeORM ; chaque `TypeOrmModule.forRoot` des `ms-*` aussi.
- Écrire dans `deploy` le budget par base : somme des `replicas × poolSize` des clients sous 80 connexions sur 100.
- Acceptation : `DB_MAX_POOL_SIZE=5` sur un service se lit dans `pg_stat_activity` (au plus 5 connexions par pod) pendant une rampe.

## 10. E12 : compteurs de badges et concurrence des workers

Spec : section L12 du plan. Pas de STOP. À faire seulement si la rampe du chantier 3 montre une file BullMQ qui monte ou des compteurs de badges en conflit.
- `incrementCounter` en un `INSERT ... ON CONFLICT (user_id, metric) DO UPDATE SET value = badge_progress.value + 1 RETURNING value` (vérifier d'abord la contrainte unique dans la migration de `badge_progress` de ms-user).
- Concurrence des workers par variable, défaut 1, puis 2 à 4 worker par worker dans `deploy`, après lecture des handlers (ordre des jobs d'un même utilisateur). worker-social l'a déjà (`SOCIAL_WORKER_CONCURRENCY`, workers-runners#65).

## 11. Skills `meta` : leçons du 2026-11-10

Les leçons sont écrites dans le chapitre 11, section 4, mais pas encore dans les skills. Une PR `meta`, par `evolve.py learn` (skill `volontariapp-skill-evolution`) :

| Skill | Leçon |
| :--- | :--- |
| `volontariapp-shared-npm-package-change` | `yarn install` après l'ajout d'un `bin` (sinon `--immutable` échoue en CI) ; la CI de `npm-packages` ne démarre pas toujours au push : `scripts/pr-retrigger.sh` ; eslint et jest depuis la racine du worktree ; jest `--no-watchman` |
| `volontariapp-implement-async-job-flow` | `jobs_outbox.scheduled_at` est NOT NULL ; les options de livraison par type de job vivent dans `messaging` (`JOB_DELIVERY_OPTIONS`) et sont appliquées par le pusher d'`outbox` (il faut monter `outbox` dans les runners) ; signature de `IJobHandler` changée par workers-runners#65 |
| `volontariapp-pr-tools` | le label `docker-and-e2e` ne relance pas la CI d'une PR existante |
| `volontariapp-deploy-gitops` | une PR qui touche plusieurs bases est déployée d'un coup par ArgoCD (7 bases redémarrées ensemble pour E0) ; échecs de tirage d'image passagers vers ghcr.io (DNS, IPv6) : Kubernetes réessaie, les anciens pods restent |
| `volontariapp-async-remediation` | la commande `requeue` d'E4 (lecture seule par défaut, `--type` et `--created-before` obligatoires, `--reason` avec `--apply`), et la méthode : lister les types par base, lire leurs consommateurs avec `analyze_impact`, rejouer dans l'ordre de dépendance (utilisateurs, puis événements et posts) |
| `volontariapp-load-ramp` | test à froid : attendre `kubectl wait --for=condition=Ready pod/neo4j-0` avant les 30 s |

Relancer ensuite `evolve.py plan` : il signale aussi deux non-conformités anciennes (`volontariapp-grpc-microservice` : source `ms-social/src/providers/database/neo4j-schema.initializer.ts` introuvable ; `volontariapp-load-ramp` : `traffic-simulator/src/load-admin.ts` introuvable).

## 12. Dettes et vérifications avant lancement

| Point | Où | Quoi faire |
| :--- | :--- | :--- |
| Vrais utilisateurs | prod | **Avant le lancement public**, revérifier : les rampes avec écritures, les rejeux et les redémarrages ne seront plus libres |
| Marqueur « compte synthétique » | ranking, classement, badges | Les comptes `load.NNNN` et du simulateur gagnent des badges et apparaissent au classement |
| `broadcastExcept` | ws-service | Chaque like et commentaire est diffusé à tous les clients connectés |
| Registre d'arrêt copié 6 fois | post-processors-runner | Le remonter dans un paquet coûte un cycle STOP |
| Secret de la base de ws-service | `deploy/apps/overlays/prod/ws-service/db-postgres/kustomization.yaml` | Utilise la clé `ms-user-password` : copier-coller probable, à vérifier |
| Tests absents | outbox-runners | Le script `test` existe mais jest n'est pas installé et il n'y a aucun test |
| Lint local | post-processors-runner, ws-service, `domain-social` | Erreurs anciennes en local (Prettier dans une migration de `post-processor-event`, `src/test` exclu du tsconfig de ws-service, 34 erreurs dans les services de `domain-social`) alors que la CI est verte |
| Ballon Proxmox | VM 101 | 16 Go fixes au prochain démarrage ; pire cas de l'hôte 32 Go pour 31,8 Go physiques |
| Simulateur de fond | deploy#66 | À fusionner une fois les rampes finies |
| Géocodage | post-processor-event | Timeout de 5 s d'OpenStreetMap vu pendant un rejeu : vérifier le repli et la DLQ de `event.created` |
| Worktrees gardés | poste de Victor | 95 gardés le 2026-11-10 (PR ouvertes, modifications non commitées, `gw-*` refusés par git à cause des sous-modules) ; inventaire dans le scratchpad de la session |

## Références

- Chapitres [09](09-demarrage-a-froid.md) (démarrage à froid, terminé), [10](10-suites.md), [11](11-passation.md), [12](12-ticket-l9-prerequis-async.md).
- `optimisation-ecritures/` : 02 (mesure, `pg_stat_statements`), 03 (spec des lots), 04 (risques de cohérence), 06 (conception de L9), 07 (options de L11).
- PR du 2026-11-10 : deploy#77 et #78 ; ms-social#77 et #78 ; npm-packages#320, #321, #322, #323 ; post-processors-runner#77 ; ws-service#61 ; workers-runners#65 ; outbox-runners#49 ; ci-tools#77 ; docs#24, #25, #26 ; meta#62 et #63.
