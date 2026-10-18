# 07 - Création du microservice : inventaire exhaustif

Liste de tout ce qu'il faut créer ou modifier, dépôt par dépôt, avec le modèle existant à copier. Les chemins des modèles sont vérifiés. Les noms de fichiers à créer sont des propositions alignées sur ces modèles.

Respecter pour chaque dépôt les règles d'or d'`AGENTS.md` : `kebab-case`, typage strict (aucun `any` ni `as unknown as`), mocks dans `*.mock.ts`, factories dans `*.factory.ts`, `jest.spyOn()` avec `restoreAllMocks()`.

## A. `proto-registry` (premier STOP)

Skill : `volontariapp-proto-contract-evolution`.

| Fichier | Action |
| :--- | :--- |
| `proto/volontariapp/ranking/ranking.proto` | créer (paquet `volontariapp.ranking`) |
| `.../ranking.query.proto`, `ranking.command.proto`, `ranking.responses.proto`, `ranking.services.proto` | créer ([06](06-lecture-et-206.md)) |
| `proto/volontariapp/social/social.query.proto` | ajouter `AdminGetRecommendedEventIdsQuery { user_id, filtres, pagination }` |
| `proto/volontariapp/social/social.services.proto` | ajouter `rpc AdminGetRecommendedEventIds(...)` à `ParticipationQueryService` (à côté de la ligne 96) |

Vérifications : `buf lint` et `buf breaking --against '.git#branch=main'`. Les ajouts de RPC et de messages sont rétrocompatibles sur le format filaire. Vérifier avec `analyze_grpc` (paramètre `base`).

**STOP.** La CI ouvre une PR dans `npm-packages` pour régénérer `@volontariapp/contracts` et `contracts-nest`. Attendre le merge et la publication.

## B. `npm-packages` (second STOP)

Skills : `volontariapp-shared-npm-package-change`, `volontariapp-implement-async-job-flow`.

| Paquet | Action |
| :--- | :--- |
| `packages/messaging/src/jobs/ranking/{payloads,queue}.ts` | créer ([04](04-flux-asynchrone.md)) |
| `packages/messaging/src/jobs/index.ts` | enregistrer dans `JobRegistry` et `JobMessagingType` |
| `packages/shared/src/enums/streams.enum.ts` | ajouter `RankingStream`, l'inclure dans `Streams` et dans le type union |
| `packages/messaging/src/websockets/events/mapping.ts` et enums associées | **indispensable pour la notification de fin de calcul** : valeur `EventEventMessagingType` (ex. `RANKING_READY`), entrée dans `JOB_TO_EVENT_MAPPING` pour `ranking.compute_user_ranking`, entrée dans `EVENT_EVENT_TO_WS_EVENT_MAPPING`, valeur `EventWebsocketMessagingType`. Sans cela `JobOutboxSuccessPostProcessor` n'émet rien et `ws-service` ne notifie personne ([04](04-flux-asynchrone.md) section 9) |
| `packages/domain-ranking/` | **nouveau paquet** : entités `RankingScoreEntity`, `RankingRunEntity`, modèles TypeORM, `RankingRepository`, services de score structurel, port `RankingScorer`, `NoopRankingScorer`, migrations, `index.ts` ; modèle : `packages/domain-social/` |
| `packages/domain-ranking/src/test/migrations/{common,domain}/` | migrations de test (communes copiées) ; modèle : `domain-social/src/test/migrations/` |
| `packages/domain-social/` | ajouter `AdminGetRecommendedEventIds` au service participation si nécessaire (le repository `getRecommendedEventIds` existe déjà et prend un `userId`) |
| `packages/errors-nest` | aucun changement attendu (`FALLBACK_ACTIVATED` existe) |

Vérifications : `yarn build`, `yarn test`, `yarn changeset add`, `yarn changeset version` (une seule fois par branche ; la CI vérifie que `CHANGELOG.md` contient la version de `package.json`).

**STOP.** Passer la main au Lead Dev pour la PR et la publication CI (`<version>-snap-<sha court>` sous le tag `next`, ou version définitive sur `main`). Seulement après : `yarn up @volontariapp/<paquet>` dans les consommateurs.

## C. `ms-social`

Skill : `volontariapp-grpc-microservice`.

| Fichier | Action |
| :--- | :--- |
| `src/modules/participation/dto/participation.query.dto.ts` | `AdminGetRecommendedEventIdsQueryDTO` (`userId`, filtres booléens optionnels, pagination), sur le modèle de `AdminGetUserEventQueryDTO` (ligne 86) |
| `src/modules/participation/controllers/participation.query.controller.ts` | handler `@GrpcMethod(..., ADMIN_GET_RECOMMENDED_EVENT_IDS)` sans `@CurrentUser`, appelant `service.getRecommendedEventIds` |
| `src/modules/participation/mappers/participation.mapper.ts` | `toAdminGetRecommendedEventIdsParams`, sur le modèle de `toGetRecommendedEventIdsParams` |
| `__tests__/` | tests du contrôleur (jeton `ADMIN` accepté, `userId` obligatoire) |

**Constat de la revue (vérifié)** : les RPC `adminGetUser*` (`participation.query.controller.ts:101-141`) n'ont **aucun contrôle de rôle**. Seul le `GrpcInternalGuard` global (`ms-social/src/app.module.ts:45`) tourne : il vérifie la signature du jeton et pose `user`, sans regarder le rôle. `ms-event` est identique (`app.module.ts:51`). Le futur `AdminGetRecommendedEventIds` hériterait de la même faille : tout jeton interne valide, y compris celui d'un utilisateur, pourrait l'appeler pour un `userId` arbitraire (IDOR latent, **préexistant**). Le test « jeton `ADMIN` accepté » prévu n'a donc pas de sens tel quel. À signaler au Lead Dev ; un garde de rôle pour les `Admin*` est un chantier séparé de ce dossier.

## D. `ms-ranking` (nouveau dépôt)

Skills : `volontariapp-grpc-microservice`. Modèle : `ms-social/` pour la structure d'un microservice ; `ms-storage/` est le domaine le plus récent et sert de référence pour le traitement de `user.deleted` (`post-processor-storage`).

| Chemin | Contenu |
| :--- | :--- |
| `src/app.module.ts`, `main.ts`, `tracing.ts` | amorçage, port gRPC 3000, OpenTelemetry avant l'initialisation |
| `src/config/*` | schéma Joi, `AppConfigModule/Service`, constantes (modèle `ms-social/src/config/`) |
| `config/{default,development,local,production,test}.config.json`, `custom-env-vars.json` | base PostgreSQL, gRPC, variables `RANKING_*` |
| `src/providers/database/postgres/` | fournisseur TypeORM (modèle `ms-social/src/providers/database/`) ; **pas de Neo4j** |
| `src/migrations/` | migrations communes (synchronisées) + `CreateRankingTables` |
| `src/modules/ranking/{controllers,dto,mappers}` | `ranking.query.controller.ts` (`GetRankingEvents`), `ranking.command.controller.ts` (`RequestRankingRefresh`), DTO implémentant les interfaces du contrat, `GrpcValidationPipe`, `GrpcInternalGuard` |
| `src/common/` | filtre d'exceptions gRPC, pipe de validation |
| `src/config/data-source.ts` | source de données TypeORM référençant les migrations, **exigée par `sync-migrations.sh`** (modèle `ms-social/src/config/data-source.ts`) |
| `Dockerfile`, `eslint.config.mjs`, `jest.config.js`, `jest.setup.js`, `tsconfig*.json`, `nest-cli.json`, `package.json`, `.prettierrc`, `.yarnrc.yml`, `LICENSE` | modèle `ms-social/` |
| `.gitmodules` (sous-module `../ci-tools.git`), `.github/` (workflows), `.husky/` (hooks), `.claudignore`, `.ai-knowledge.md`, `.editorconfig`, `.dockerignore`, `.gitignore`, `certs/` | fichiers de dépôt présents dans les microservices existants |
| `e2e-matrix.json` | **chaque dépôt liste tous les autres** (ex. `api-gateway/e2e-matrix.json` liste `ms-post`, `ms-user`, `ms-event`, `ms-social`, `ms-storage`) : ajouter `ms-ranking` à la matrice de `api-gateway` et de chaque `ms-*` concerné, et créer celle de `ms-ranking` |
| `service.datadog.yaml` | supervision, modèle `ms-social/service.datadog.yaml` |
| `README.md`, `ARCHITECTURE.md` | description, schéma de flux |

Dépendances `@volontariapp/*` : `domain-ranking`, `messaging`, `database`, `outbox`, `shared`, `errors`, `errors-nest`, `auth`, `logger`, `config`, `bridge`, `bridge-nest`, `contracts-nest`. **Pas** de `domain-social` ni `domain-event`.

## E. `outbox-ranking`

Dossier dans le dépôt existant `outbox-runners/`. **Utiliser le script de génération `outbox-runners/scripts/create-outbox.sh`**, puis comparer avec le modèle `outbox-runners/outbox-social/` (`src/{config,providers,repositories,runners}`, `Dockerfile`). Surveille `jobs_outbox` (files `ranking-queue` et `fallback-ranking-queue`) et `event_queue` (streams `ranking:job:outbox:*`). Pas de dépendance à `domain-ranking` (le modèle `outbox-social` n'en a aucune sur `domain-social`). Ajouter une entrée au `README.md` et à `ARCHITECTURE.md` d'`outbox-runners`.

**À confirmer** : que `outbox-runners` supporte l'ajout d'un domaine sans changement de code partagé (la skill dit « 100 % transparent »), en lisant `command.sh` et les workflows du dépôt.

## F. `worker-ranking`

Skill : `volontariapp-implement-async-job-flow`. Modèle : `workers-runners/worker-social/` (`app.module.ts` montre BullMQ, Redis, Postgres, `JobAuditRepository`).

| Fichier | Contenu |
| :--- | :--- |
| `src/workers/ranking.worker.ts` et `src/workers/fallback-ranking.worker.ts` | **deux classes** `BaseWorker` : `@Processor(queue)` est par classe, et `worker-event` en a deux (`event.worker.ts`, `fallback-event.worker.ts`). Passer `{ concurrency }` à `@Processor` : le champ existe dans `workers/src/interfaces/worker-app-config.interface.ts:5` mais aucun worker existant ne le règle (défaut BullMQ : 1) |
| `src/workers/job-handler.interface.ts` | `IJobHandler` locale. **Copier le contrat de retour de `worker-event` (`{ originalPayload }`)**, pas celui de `worker-social` (`Promise<void>`). Aucun worker existant ne lit `job.data.payload` de façon cohérente (`FollowUserHandler` lit `job.data` directement) : s'en tenir à la forme de la skill job-flow |
| `src/workers/handlers/compute-user-ranking.handler.ts` | calcul ([04](04-flux-asynchrone.md) section 5) |
| `src/workers/handlers/fanout-ranking.handler.ts` | fan-out |
| `certs/` et `auth.internalPrivateKeyPath` dans `config/default.config.json` | le worker doit disposer de la clé privée de signature interne pour `signInternal` (SealedSecret ou volume en déploiement) |
| `src/clients/social-admin.client.ts` | client gRPC vers `ms-social` avec jeton interne en cache 4 min (modèle `post-processor-user/.../social-interaction.client.ts`) |
| `src/clients/event-query.client.ts` | client gRPC vers `ms-event` (lecture seule) |
| `src/scoring/jev-ranking-scorer.ts` | adaptateur HTTP Jev ([05](05-scoring-et-jev.md)) |
| `src/providers/{redis,database}.provider.ts` | modèles `worker-social/src/providers/` |
| `config/*.json` | Redis (BullMQ), base, `RANKING_*`, `TYPESAFE_API_KEY` |

Note : `worker-social` n'a aujourd'hui **aucun** client gRPC sortant. `worker-ranking` en aura deux (`ms-social`, `ms-event`) et un accès HTTP sortant (Jev).

## G. `post-processor-ranking`

Skill : `volontariapp-implement-async-event-flow`. Modèle : `post-processors-runner/post-processor-social/` (`src/{post-processors,providers,infrastructure,domain}`, `post-processors.module.ts`).

Dossier dans le dépôt existant `post-processors-runner/`. Six post-processors ([04](04-flux-asynchrone.md), section 4), chacun avec son fichier d'options (`options/*.options.ts`) précisant le stream, le **groupe de consommateurs propre à ce domaine** et la taille des lots :

- quatre post-processors métier (inscription via `social:user`, souhait, événement créé, événement terminé) ;
- **les deux post-processors communs `JobOutboxSuccessPostProcessor` et `JobOutboxFailedPostProcessor`**, enregistrés dans `post-processors.module.ts` comme dans `post-processor-social` (lignes 9-10 et 48-80) avec des options sur `RankingStream.RANKING_JOB_OUTBOX_SUCCESS`/`FAILURE`. Sans eux, les lignes `jobs_outbox` ne sont jamais supprimées et aucune notification n'est émise.

Prérequis : `post-processor-ranking` doit se connecter à la base de `ms-ranking` (`jobs_outbox`, `event_queue`, `ranking_request`) comme `post-processor-social` écrit dans la sienne. Éléments propres au dossier (modèle `post-processor-social`) : `config/`, `tests/`, `jest.config.js`, `Dockerfile`, `.yarnrc.yml`. Le `tsconfig.eslint.json` n'existe pas dans le modèle outbox.

## H. `api-gateway`

Skill : `volontariapp-api-gateway`.

| Fichier | Action |
| :--- | :--- |
| `src/modules/ranking/` | module **séparé** (pas dans `src/modules/event/`) : client gRPC `RankingQueryService`/`RankingCommandService`, contrôleur `@Controller('ranking')` avec `GET /ranking/events` et `POST /ranking/refresh` (un chemin sous `/events` serait capté par `@Get(':id')` de `EventQueryController`), DTO de requête (`toQuery()`) et de réponse |
| `src/grpc/` | token `RANKING_PACKAGE` et options du client |
| tests | contrôleur : 200, 206 propagé, réordonnancement, ID absents ignorés, **non-régression de routage** (`/ranking/events` ne doit jamais atteindre `getEvent`), pagination explicite vers `ms-event` |

## I. `deploy` (GitOps)

Skill : `volontariapp-deploy-gitops`. Modèle : `deploy/apps/base/ms-social/` et `deploy/infrastructure/databases/ms-social/`.

| Chemin | Action |
| :--- | :--- |
| `apps/base/ms-ranking/{deployment,deployment-outbox,deployment-worker,deployment-post-processor,service,kustomization}.yaml` | créer ; images épinglées par sha ; PSA Restricted |
| `apps/overlays/` (production) | overlay de `ms-ranking` |
| `infrastructure/databases/ms-ranking/` | PostgreSQL dédié |
| `infrastructure/security/` | SealedSecrets : identifiants de base, clé de signature des jetons internes, `TYPESAFE_API_KEY` (**jamais en clair dans Git**) |
| `prod-policies.yaml` et NetworkPolicies | voir ci-dessous |
| `infrastructure/argocd/` | application ArgoCD |
| `submodules/` | `deploy/` contient aussi des copies par service sous `submodules/` (vu pour `post-processors-runner`). **Non vérifié** : ce que ces sous-modules exigent pour un nouveau service ; lire `deploy/README.md` avant de créer les manifestes |
| `infrastructure/network-policies/` | dossier dédié existant en plus de `prod-policies.yaml` (racine de `deploy/`) |

NetworkPolicies à définir (moindre privilège, `AGENTS.md` section 6) :

| Source | Destination | Raison |
| :--- | :--- | :--- |
| `api-gateway` | `ms-ranking:3000` | seule entrée |
| `worker-ranking` | `ms-social:3000`, `ms-event:3000` | candidats, historique, texte |
| `worker-ranking` | `api.typesafe.ai:443` | **seule sortie vers Internet** du domaine |
| tous les pods du domaine | PostgreSQL et Redis du domaine/partagé | données et files |
| tout le reste | refusé | défaut |

## J. `ci-tools` et outillage racine

| Fichier | Action |
| :--- | :--- |
| `ci-tools/docker-compose.yml` | ajouter la base PostgreSQL d'`ms-ranking` pour le développement local |
| `ci-tools/.github/workflows` | vérifier que les workflows réutilisables couvrent les nouveaux dépôts ; ajouter les dépôts à la matrice e2e (`e2e-matrix.json`) |
| `sync-migrations.sh` | ajouter `"ranking"` à `SERVICES=(...)` |
| `.gitignore` (racine `meta`) | ajouter les nouveaux dépôts clonés |
| `volontariapp.code-workspace`, `show_repo_status.sh`, `root.sh`, `README.md`, `AGENTS.md`, `AGENT.md` | référencer les nouveaux dépôts (tableaux de la carte des repos) |
| `.agents/mesh-mcp.toml` | ajouter les nouvelles racines à l'index `mesh-mcp` |
| skills `volontariapp-*` | ajouter les `paths` des nouveaux dépôts aux skills concernées ; créer une skill `volontariapp-ranking` si le sujet le justifie (`evolve.py new ...`) ; installer les hooks pre-commit (`./scripts/install-skill-hooks.sh`) |

## K. `nativapp`

| Fichier | Action |
| :--- | :--- |
| hook React Query | `useRankingEvents` (TanStack Query, **exclusivement**, `AGENTS.md` section 5) : appelle `GET /ranking/events`, **discrimine le corps d'un 206** (`data.code === 'FALLBACK_ACTIVATED'`, car axios résout les 2xx : `nativapp/src/api/client.ts:55`), bascule sur la recherche d'événements classique en attendant |
| `src/hooks/useNotificationHandlers.ts` | handler de la notification de fin de job de ranking (invalide la requête) |
| écran liste d'événements | bascule liste normale / recommandée, affichage du score et de la source |
| composants | respecter le Design System custom (section 3 d'`AGENTS.md`), navigation custom |

## K bis. Feed de posts : ajouts à l'inventaire

Le détail est en [12](12-feed-plan-et-risques.md) section 1. En résumé, en plus des sections A à K :

- **A** (`proto-registry`) : `ListRecentPostsByAuthors`, `ListPostsByIds`, `ListCommentsByAuthor` (paquet `post`), `GetRankingFeed`, `list_kind` dans `RequestRankingRefresh`, `RANKING_SOURCE_COLD_START`.
- **B** (`npm-packages`) : `COMPUTE_USER_FEED`, `RankingQueue.FEED`, second mapping WebSocket ; `domain-ranking` : `RankingLikeLog`, `RankingPostScore`.
- **`ms-post`** (dépôt supplémentaire modifié) : trois handlers, migration d'index `("authorId", "createdAt" DESC)`, tests, `e2e-matrix`.
- **F** (`worker-ranking`) : `compute-user-feed.handler.ts`, `src/clients/post-query.client.ts` (gRPC vers `ms-post`), troisième file `ranking-feed-queue` (donc une classe `@Processor` de plus).
- **G** (`post-processor-ranking`) : post-processors `POST_CREATED` (fan-out et `ranking_event_mention`), `POST_LIKED` et `POST_UNLIKED` (journal `ranking_like_log`), `POST_DELETED` (suppression de la mention) en plus des quatre métier et des deux communs ; `UserCreated` écrit deux demandes dans une seule transaction.
- **H** (`api-gateway`) : `GET /ranking/feed`, client `ms-post`.
- **I** (`deploy`) : NetworkPolicy `worker-ranking` vers `ms-post:3000`, CronJob de purge.

## L. Récapitulatif chiffré

| Catégorie | Nombre |
| :--- | :--- |
| Nouveau dépôt git | 1 (`ms-ranking`) |
| Nouveaux dossiers dans des dépôts existants | 3 (`outbox-runners/outbox-ranking`, `workers-runners/worker-ranking`, `post-processors-runner/post-processor-ranking`) |
| Nouveaux paquets ou contrats | 2 (`npm-packages/packages/domain-ranking`, `proto-registry/proto/volontariapp/ranking/`) |
| Dépôts existants modifiés | `proto-registry`, `npm-packages` (`messaging`, `shared`, éventuellement `domain-user`), `ms-social`, `api-gateway` (+ `e2e-matrix` des `ms-*`), `deploy`, `ci-tools`, `nativapp`, racine `meta` |
| Étapes bloquantes (STOP) | 2 ; la modification de `domain-user` (`user:deleted:ranking`) est décidée en V1 ([13](13-decisions-v1.md)) |
