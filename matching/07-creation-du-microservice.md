# 07 - Création du microservice : inventaire exhaustif

Liste de tout ce qu'il faut créer ou modifier, dépôt par dépôt, avec le modèle existant à copier. Les chemins des modèles sont vérifiés. Les noms de fichiers à créer sont des propositions alignées sur ces modèles.

Respecter pour chaque dépôt les règles d'or d'`AGENTS.md` : `kebab-case`, typage strict (aucun `any` ni `as unknown as`), mocks dans `*.mock.ts`, factories dans `*.factory.ts`, `jest.spyOn()` avec `restoreAllMocks()`.

## A. `proto-registry` (premier STOP)

Skill : `volontariapp-proto-contract-evolution`.

| Fichier | Action |
| :--- | :--- |
| `proto/volontariapp/affinity/affinity.proto` | créer (paquet `volontariapp.affinity`) |
| `.../affinity.query.proto`, `affinity.command.proto`, `affinity.responses.proto`, `affinity.services.proto` | créer ([06](06-lecture-et-206.md)) |
| `proto/volontariapp/social/social.query.proto` | ajouter `AdminGetRecommendedEventIdsQuery { user_id, filtres, pagination }` |
| `proto/volontariapp/social/social.services.proto` | ajouter `rpc AdminGetRecommendedEventIds(...)` à `ParticipationQueryService` (à côté de la ligne 96) |

Vérifications : `buf lint` et `buf breaking --against '.git#branch=main'`. Les ajouts de RPC et de messages sont rétrocompatibles sur le format filaire. Vérifier avec `analyze_grpc` (paramètre `base`).

**STOP.** La CI ouvre une PR dans `npm-packages` pour régénérer `@volontariapp/contracts` et `contracts-nest`. Attendre le merge et la publication.

## B. `npm-packages` (second STOP)

Skills : `volontariapp-shared-npm-package-change`, `volontariapp-implement-async-job-flow`.

| Paquet | Action |
| :--- | :--- |
| `packages/messaging/src/jobs/affinity/{payloads,queue}.ts` | créer ([04](04-flux-asynchrone.md)) |
| `packages/messaging/src/jobs/index.ts` | enregistrer dans `JobRegistry` et `JobMessagingType` |
| `packages/shared/src/enums/streams.enum.ts` | ajouter `AffinityStream`, l'inclure dans `Streams` et dans le type union |
| `packages/messaging/src/websockets/events/mapping.ts` et enums associées | **indispensable pour la notification de fin de calcul** : valeur `EventEventMessagingType` (ex. `AFFINITY_READY`), entrée dans `JOB_TO_EVENT_MAPPING` pour `affinity.compute_user_affinity`, entrée dans `EVENT_EVENT_TO_WS_EVENT_MAPPING`, valeur `EventWebsocketMessagingType`. Sans cela `JobOutboxSuccessPostProcessor` n'émet rien et `ws-service` ne notifie personne ([04](04-flux-asynchrone.md) section 9) |
| `packages/domain-affinity/` | **nouveau paquet** : entités `AffinityScoreEntity`, `AffinityRunEntity`, modèles TypeORM, `AffinityRepository`, services de score structurel, port `AffinityScorer`, `NoopAffinityScorer`, migrations, `index.ts` ; modèle : `packages/domain-social/` |
| `packages/domain-affinity/src/test/migrations/{common,domain}/` | migrations de test (communes copiées) ; modèle : `domain-social/src/test/migrations/` |
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

## D. `ms-affinity` (nouveau dépôt)

Skills : `volontariapp-grpc-microservice`. Modèle : `ms-social/`.

| Chemin | Contenu |
| :--- | :--- |
| `src/app.module.ts`, `main.ts`, `tracing.ts` | amorçage, port gRPC 3000, OpenTelemetry avant l'initialisation |
| `src/config/*` | schéma Joi, `AppConfigModule/Service`, constantes (modèle `ms-social/src/config/`) |
| `config/{default,development,local,production,test}.config.json`, `custom-env-vars.json` | base PostgreSQL, gRPC, variables `AFFINITY_*` |
| `src/providers/database/postgres/` | fournisseur TypeORM (modèle `ms-social/src/providers/database/`) ; **pas de Neo4j** |
| `src/migrations/` | migrations communes (synchronisées) + `CreateAffinityTables` |
| `src/modules/affinity/{controllers,dto,mappers}` | `affinity.query.controller.ts` (`GetAffinityEvents`), `affinity.command.controller.ts` (`RequestAffinityRefresh`), DTO implémentant les interfaces du contrat, `GrpcValidationPipe`, `GrpcInternalGuard` |
| `src/common/` | filtre d'exceptions gRPC, pipe de validation |
| `src/config/data-source.ts` | source de données TypeORM référençant les migrations, **exigée par `sync-migrations.sh`** (modèle `ms-social/src/config/data-source.ts`) |
| `Dockerfile`, `eslint.config.mjs`, `jest.config.js`, `jest.setup.js`, `tsconfig*.json`, `nest-cli.json`, `package.json`, `.prettierrc`, `.yarnrc.yml`, `LICENSE` | modèle `ms-social/` |
| `.gitmodules` (sous-module `../ci-tools.git`), `.github/` (workflows), `.husky/` (hooks), `.claudignore`, `.ai-knowledge.md`, `.editorconfig`, `.dockerignore`, `.gitignore`, `certs/` | fichiers de dépôt présents dans les microservices existants |
| `e2e-matrix.json` | **chaque dépôt liste tous les autres** (ex. `api-gateway/e2e-matrix.json` liste `ms-post`, `ms-user`, `ms-event`, `ms-social`, `ms-storage`) : ajouter `ms-affinity` à la matrice de `api-gateway` et de chaque `ms-*` concerné, et créer celle de `ms-affinity` |
| `service.datadog.yaml` | supervision, modèle `ms-social/service.datadog.yaml` |
| `README.md`, `ARCHITECTURE.md` | description, schéma de flux |

Dépendances `@volontariapp/*` : `domain-affinity`, `messaging`, `database`, `outbox`, `shared`, `errors`, `errors-nest`, `auth`, `logger`, `config`, `bridge`, `bridge-nest`, `contracts-nest`. **Pas** de `domain-social` ni `domain-event`.

## E. `outbox-affinity`

Dossier dans le dépôt existant `outbox-runners/`. **Utiliser le script de génération `outbox-runners/scripts/create-outbox.sh`**, puis comparer avec le modèle `outbox-runners/outbox-social/` (`src/{config,providers,repositories,runners}`, `Dockerfile`). Surveille `jobs_outbox` (files `affinity-queue` et `fallback-affinity-queue`) et `event_queue` (streams `affinity:job:outbox:*`). Pas de dépendance à `domain-affinity` (le modèle `outbox-social` n'en a aucune sur `domain-social`). Ajouter une entrée au `README.md` et à `ARCHITECTURE.md` d'`outbox-runners`.

**À confirmer** : que `outbox-runners` supporte l'ajout d'un domaine sans changement de code partagé (la skill dit « 100 % transparent »), en lisant `command.sh` et les workflows du dépôt.

## F. `worker-affinity`

Skill : `volontariapp-implement-async-job-flow`. Modèle : `workers-runners/worker-social/` (`app.module.ts` montre BullMQ, Redis, Postgres, `JobAuditRepository`).

| Fichier | Contenu |
| :--- | :--- |
| `src/workers/affinity.worker.ts` et `src/workers/fallback-affinity.worker.ts` | **deux classes** `BaseWorker` : `@Processor(queue)` est par classe, et `worker-event` en a deux (`event.worker.ts`, `fallback-event.worker.ts`). Passer `{ concurrency }` à `@Processor` : le champ existe dans `workers/src/interfaces/worker-app-config.interface.ts:5` mais aucun worker existant ne le règle (défaut BullMQ : 1) |
| `src/workers/job-handler.interface.ts` | `IJobHandler` locale. **Copier le contrat de retour de `worker-event` (`{ originalPayload }`)**, pas celui de `worker-social` (`Promise<void>`). Aucun worker existant ne lit `job.data.payload` de façon cohérente (`FollowUserHandler` lit `job.data` directement) : s'en tenir à la forme de la skill job-flow |
| `src/workers/handlers/compute-user-affinity.handler.ts` | calcul ([04](04-flux-asynchrone.md) section 5) |
| `src/workers/handlers/fanout-affinity.handler.ts` | fan-out |
| `certs/` et `auth.internalPrivateKeyPath` dans `config/default.config.json` | le worker doit disposer de la clé privée de signature interne pour `signInternal` (SealedSecret ou volume en déploiement) |
| `src/clients/social-admin.client.ts` | client gRPC vers `ms-social` avec jeton interne en cache 4 min (modèle `post-processor-user/.../social-interaction.client.ts`) |
| `src/clients/event-query.client.ts` | client gRPC vers `ms-event` (lecture seule) |
| `src/scoring/jev-affinity-scorer.ts` | adaptateur HTTP Jev ([05](05-scoring-et-jev.md)) |
| `src/providers/{redis,database}.provider.ts` | modèles `worker-social/src/providers/` |
| `config/*.json` | Redis (BullMQ), base, `AFFINITY_*`, `TYPESAFE_API_KEY` |

Note : `worker-social` n'a aujourd'hui **aucun** client gRPC sortant. `worker-affinity` en aura deux (`ms-social`, `ms-event`) et un accès HTTP sortant (Jev).

## G. `post-processor-affinity`

Skill : `volontariapp-implement-async-event-flow`. Modèle : `post-processors-runner/post-processor-social/` (`src/{post-processors,providers,infrastructure,domain}`, `post-processors.module.ts`).

Dossier dans le dépôt existant `post-processors-runner/`. Six post-processors ([04](04-flux-asynchrone.md), section 4), chacun avec son fichier d'options (`options/*.options.ts`) précisant le stream, le **groupe de consommateurs propre à ce domaine** et la taille des lots :

- quatre post-processors métier (inscription via `social:user`, souhait, événement créé, événement terminé) ;
- **les deux post-processors communs `JobOutboxSuccessPostProcessor` et `JobOutboxFailedPostProcessor`**, enregistrés dans `post-processors.module.ts` comme dans `post-processor-social` (lignes 9-10 et 48-80) avec des options sur `AffinityStream.AFFINITY_JOB_OUTBOX_SUCCESS`/`FAILURE`. Sans eux, les lignes `jobs_outbox` ne sont jamais supprimées et aucune notification n'est émise.

Prérequis : `post-processor-affinity` doit se connecter à la base de `ms-affinity` (`jobs_outbox`, `event_queue`, `affinity_request`) comme `post-processor-social` écrit dans la sienne. Éléments propres au dossier (modèle `post-processor-social`) : `config/`, `tests/`, `jest.config.js`, `Dockerfile`, `.yarnrc.yml`. Le `tsconfig.eslint.json` n'existe pas dans le modèle outbox.

## H. `api-gateway`

Skill : `volontariapp-api-gateway`.

| Fichier | Action |
| :--- | :--- |
| `src/modules/affinity/` | module **séparé** (pas dans `src/modules/event/`) : client gRPC `AffinityQueryService`/`AffinityCommandService`, contrôleur `@Controller('affinity')` avec `GET /affinity/events` et `POST /affinity/refresh` (un chemin sous `/events` serait capté par `@Get(':id')` de `EventQueryController`), DTO de requête (`toQuery()`) et de réponse |
| `src/grpc/` | token `AFFINITY_PACKAGE` et options du client |
| tests | contrôleur : 200, 206 propagé, réordonnancement, ID absents ignorés, **non-régression de routage** (`/affinity/events` ne doit jamais atteindre `getEvent`), pagination explicite vers `ms-event` |

## I. `deploy` (GitOps)

Skill : `volontariapp-deploy-gitops`. Modèle : `deploy/apps/base/ms-social/` et `deploy/infrastructure/databases/ms-social/`.

| Chemin | Action |
| :--- | :--- |
| `apps/base/ms-affinity/{deployment,deployment-outbox,deployment-worker,deployment-post-processor,service,kustomization}.yaml` | créer ; images épinglées par sha ; PSA Restricted |
| `apps/overlays/` (production) | overlay de `ms-affinity` |
| `infrastructure/databases/ms-affinity/` | PostgreSQL dédié |
| `infrastructure/security/` | SealedSecrets : identifiants de base, clé de signature des jetons internes, `TYPESAFE_API_KEY` (**jamais en clair dans Git**) |
| `prod-policies.yaml` et NetworkPolicies | voir ci-dessous |
| `infrastructure/argocd/` | application ArgoCD |
| `submodules/` | `deploy/` contient aussi des copies par service sous `submodules/` (vu pour `post-processors-runner`). **Non vérifié** : ce que ces sous-modules exigent pour un nouveau service ; lire `deploy/README.md` avant de créer les manifestes |
| `infrastructure/network-policies/` | dossier dédié existant en plus de `prod-policies.yaml` (racine de `deploy/`) |

NetworkPolicies à définir (moindre privilège, `AGENTS.md` section 6) :

| Source | Destination | Raison |
| :--- | :--- | :--- |
| `api-gateway` | `ms-affinity:3000` | seule entrée |
| `worker-affinity` | `ms-social:3000`, `ms-event:3000` | candidats, historique, texte |
| `worker-affinity` | `api.typesafe.ai:443` | **seule sortie vers Internet** du domaine |
| tous les pods du domaine | PostgreSQL et Redis du domaine/partagé | données et files |
| tout le reste | refusé | défaut |

## J. `ci-tools` et outillage racine

| Fichier | Action |
| :--- | :--- |
| `ci-tools/docker-compose.yml` | ajouter la base PostgreSQL d'`ms-affinity` pour le développement local |
| `ci-tools/.github/workflows` | vérifier que les workflows réutilisables couvrent les nouveaux dépôts ; ajouter les dépôts à la matrice e2e (`e2e-matrix.json`) |
| `sync-migrations.sh` | ajouter `"affinity"` à `SERVICES=(...)` |
| `.gitignore` (racine `meta`) | ajouter les nouveaux dépôts clonés |
| `volontariapp.code-workspace`, `show_repo_status.sh`, `root.sh`, `README.md`, `AGENTS.md`, `AGENT.md` | référencer les nouveaux dépôts (tableaux de la carte des repos) |
| `.agents/mesh-mcp.toml` | ajouter les nouvelles racines à l'index `mesh-mcp` |
| skills `volontariapp-*` | ajouter les `paths` des nouveaux dépôts aux skills concernées ; créer une skill `volontariapp-affinity` si le sujet le justifie (`evolve.py new ...`) ; installer les hooks pre-commit (`./scripts/install-skill-hooks.sh`) |

## K. `nativapp`

| Fichier | Action |
| :--- | :--- |
| hook React Query | `useAffinityEvents` (TanStack Query, **exclusivement**, `AGENTS.md` section 5) : appelle `GET /affinity/events`, **discrimine le corps d'un 206** (`data.code === 'FALLBACK_ACTIVATED'`, car axios résout les 2xx : `nativapp/src/api/client.ts:55`), bascule sur la recherche d'événements classique en attendant |
| `src/hooks/useNotificationHandlers.ts` | handler de la notification de fin de job d'affinité (invalide la requête) |
| écran liste d'événements | bascule liste normale / recommandée, affichage du score et de la source |
| composants | respecter le Design System custom (section 3 d'`AGENTS.md`), navigation custom |

## K bis. Feed de posts : ajouts à l'inventaire

Le détail est en [12](12-feed-plan-et-risques.md) section 1. En résumé, en plus des sections A à K :

- **A** (`proto-registry`) : `ListRecentPostsByAuthors`, `ListPostsByIds`, `ListCommentsByAuthor` (paquet `post`), `GetAffinityPosts`, `list_kind` dans `RequestAffinityRefresh`, `AFFINITY_SOURCE_COLD_START`.
- **B** (`npm-packages`) : `COMPUTE_USER_FEED`, `AffinityQueue.FEED`, second mapping WebSocket ; `domain-affinity` : `AffinityLikeLog`, `AffinityPostScore`.
- **`ms-post`** (dépôt supplémentaire modifié) : trois handlers, migration d'index `("authorId", "createdAt" DESC)`, tests, `e2e-matrix`.
- **F** (`worker-affinity`) : `compute-user-feed.handler.ts`, `src/clients/post-query.client.ts` (gRPC vers `ms-post`), troisième file `affinity-feed-queue` (donc une classe `@Processor` de plus).
- **G** (`post-processor-affinity`) : post-processors `POST_CREATED`, `POST_LIKED`, `POST_UNLIKED` en plus des quatre métier et des deux communs ; `UserCreated` écrit deux demandes dans une seule transaction.
- **H** (`api-gateway`) : `GET /affinity/feed`, client `ms-post`.
- **I** (`deploy`) : NetworkPolicy `worker-affinity` vers `ms-post:3000`, CronJob de purge.

## L. Récapitulatif chiffré

| Catégorie | Nombre |
| :--- | :--- |
| Nouveau dépôt git | 1 (`ms-affinity`) |
| Nouveaux dossiers dans des dépôts existants | 3 (`outbox-runners/outbox-affinity`, `workers-runners/worker-affinity`, `post-processors-runner/post-processor-affinity`) |
| Nouveaux paquets ou contrats | 2 (`npm-packages/packages/domain-affinity`, `proto-registry/proto/volontariapp/affinity/`) |
| Dépôts existants modifiés | `proto-registry`, `npm-packages` (`messaging`, `shared`, éventuellement `domain-user`), `ms-social`, `api-gateway` (+ `e2e-matrix` des `ms-*`), `deploy`, `ci-tools`, `nativapp`, racine `meta` |
| Étapes bloquantes (STOP) | 2, et une 3e si la suppression de compte est traitée (`domain-user`) |
