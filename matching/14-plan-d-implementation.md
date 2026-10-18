# 14 - Plan d'implémentation : l'ordre des choses

Ce fichier est la source des tickets. Chaque ligne `RK-xx` devient un ticket Notion. Il dit **quoi faire, dans quel dépôt, dans quel ordre, avec quelle skill, et comment savoir que c'est fini**. Les décisions sont dans [13](13-decisions-v1.md) (elles priment), le détail technique dans 02 à 12.

## 1. Règles qui s'appliquent à tout

1. **Règle du STOP** (`AGENTS.md` section 1). Après toute modification de `proto-registry` ou de `npm-packages` : build et tests locaux, changeset (`yarn changeset add` puis `yarn changeset version`, une fois par branche), **arrêt**, le Lead Dev pousse la PR, la CI publie, **ensuite seulement** on met à jour les consommateurs (`yarn up`). Aucun contournement par `as unknown as` ou `any`. Le hook `.claude/hooks/stop-rule-guard.sh` bloque les éditions de consommateurs ; seul le Lead Dev lance `release`.
2. **Portes humaines** : G1 (merge `proto-registry`, PR automatique dans `npm-packages`), G2 (publication `npm-packages`), G3 (secrets scellés `kubeseal`), G4 (déploiement, en deux vagues pour le gather, voir RK-16).
3. **Tests d'abord** (skill `tdd`) : mocks dans `*.mock.ts`, factories dans `*.factory.ts`, `jest.spyOn` avec `restoreAllMocks()`. Pas de `any`.
4. **Avant de terminer** : `python3 .agents/skills/volontariapp-skill-evolution/scripts/evolve.py plan`, puis relire les skills listées.
5. **Pas de grep à la racine** : utiliser `mesh-mcp` (`analyze_grpc`, `analyze_impact`, `find_dependents`, `smart_search` avec `scope`).
6. **`ms-ranking` n'appelle aucun autre service dans le chemin de lecture** ; tous ses appels sortants sont faits par `worker-ranking`.

## 2. Vue d'ensemble en une page

```text
Phase 1  proto-registry ........ RK-01 RK-02 RK-03        -> G1 (merge) -> PR auto npm-packages
Phase 2  npm-packages .......... RK-04 .. RK-09           -> G2 (publication CI)
Phase 3  ms-social, ms-post .... RK-10 RK-11              (yarn up des paquets publiés)
Phase 4  nouveau domaine ....... RK-12 RK-12b RK-13 .. RK-16
Phase 5  api-gateway ........... RK-17
Phase 6  deploy, secrets ....... RK-18a .. RK-18d         -> G3, G4 (deux vagues)
Phase 7  nativapp .............. RK-19                    (en dernier ; la carte n'est pas touchée)
Phase 8  qualité, Jev .......... RK-20 RK-20b RK-21 RK-22 RK-23
```

Correspondance avec les tranches de [09](09-plan-de-livraison.md) : T0 = RK-12 à RK-16 (squelettes, purge de compte, notification) ; T1 = logique de RK-15 sans Jev + RK-17 ; T2 = RK-21 ; T3 = déclencheurs et popularité de RK-14/RK-15 ; T4 = rafraîchissement et seaux de débit ; T5 = événements de participation et de follow (hors V1) ; T6 = RK-19.

## 3. Phase 1 : contrats (`proto-registry`)

Skill : `volontariapp-proto-contract-evolution`. Vérifier `buf lint` et `buf breaking --against '.git#branch=main'`, puis **STOP (G1)**. La CI ouvre ensuite une PR dans `npm-packages` qui régénère `@volontariapp/contracts` et `contracts-nest` (tout sauf `contracts/src/gateway/`, écrit à la main : RK-09).

| ID | Livrable | Fait quand |
| :--- | :--- | :--- |
| RK-01 | Package `proto/volontariapp/ranking/ranking.{proto,command,query,responses,services}.proto`, schéma complet dans [06](06-lecture-et-206.md) section 2 : `RankingQueryService` (`GetRankingEvents`, `GetRankingFeed`, curseur opaque, `list_version`, `version_changed`, `reasons`) et `RankingCommandService` (`RequestRankingRefresh(list_kind)`, `UpdateUserLocation`, `RecordEventFeedback`, 50 éléments au plus) ; enums `RankingListKind`, `RankingSource`, `RankingReason`, `FeedbackAction` | `buf lint` et `buf breaking` verts ; chaque enum a une valeur 0 `UNSPECIFIED` et ses valeurs préfixées par le nom de l'enum ; aucun champ renuméroté |
| RK-02 | `social` : RPC `AdminGetRecommendedEventIds` (même corps que `GetRecommendedEventIds` plus `user_id` explicite) | idem ; voir [04](04-flux-asynchrone.md) étape 5 |
| RK-03 | `post` : `ListPostsByIds` (100 identifiants au plus, absents ignorés), `ListRecentPostsByAuthors`, `ListCommentsByAuthor` | idem ; messages décrits en [11](11-feed-conception.md) section 4 |

RK-01 à RK-03 partent dans **une seule PR** pour ne passer qu'une fois par le STOP.

## 4. Phase 2 : paquets partagés (`npm-packages`)

Skill : `volontariapp-shared-npm-package-change`. Une seule branche, un seul changeset, puis **STOP (G2)** : la CI publie une version snapshot `-snap-<sha>` listée dans la PR.

| ID | Paquet | Livrable | Fait quand |
| :--- | :--- | :--- | :--- |
| RK-04 | `shared` | `Streams` : `RANKING_JOB_OUTBOX_SUCCESS` (`ranking:job:outbox:success`), `RANKING_JOB_OUTBOX_FAILURE`, `USER_DELETED_RANKING` (`user:deleted:ranking`), ajoutés à l'union de types | build et tests verts |
| RK-05 | `messaging` | **Définition unique** des types de job de [04](04-flux-asynchrone.md) section 3 (`COMPUTE_USER_RANKING`, `COMPUTE_USER_FEED`, `FANOUT_RANKING`, `RankingComputeReason` avec `POST_PUBLISHED`, `RankingQueue` avec `FEED`) dans `src/jobs/ranking/{payloads,queue}.ts`, enregistrée dans `src/jobs/index.ts` ; événements `USER_RANKING_DELETED` et `USER_RANKING_DELETION_FAILED` ; notification WebSocket `RANKING_READY` (un seul type pour les événements et les posts, dans un enum dédié `ranking` si `JOB_TO_EVENT_MAPPING` l'accepte, sinon `EventEventMessagingType`) ajoutée aux deux mappings ([04](04-flux-asynchrone.md) section 9) | un test de mapping couvre `getEventForJob('ranking.compute_user_ranking')` et `getEventForJob('ranking.compute_user_feed')` |
| RK-06 | `domain-user` | `requestDeletionWithUserDeleted` ajoute `Streams.USER_DELETED_RANKING` aux `targetServices` (`postgres-user.repository.ts:110`) ; test d'intégration `user-deletion.int.spec.ts` mis à jour | le test liste le nouveau stream |
| RK-07 | `domain-ranking` (nouveau) | Entités et modèles de [03](03-modele-de-donnees.md) ; repositories TypeORM ; services purs : score événement ([05](05-scoring-et-jev.md)), popularité, score post ([11](11-feed-conception.md) section 5), codes d'explication, coalescence, **curseur opaque `(listVersion, lastRank)`** et pénalités `PASS` sur les rangs non servis ; requête de demande avec `needs_job` ([03](03-modele-de-donnees.md) section 2) ; **seaux à jetons** `REFRESH` (5/min, partagé) et `LOCATION` (1/min) avec les `::numeric` ([13](13-decisions-v1.md) section 3 bis) ; chiffrement de la position (`v1\|userId\|lat\|lng`) ; port `RankingScorer` et `NoopRankingScorer` ; migrations de test copiées par `sync-migrations.sh`. **Le journal de likes n'est pas chiffré** (décision 30) | services testés sans infrastructure ; tests d'intégration sur un vrai PostgreSQL : recharge d'un jeton après 12 s, sixième appel refusé, demande après `started_at` => second calcul, demande pendant le débounce => un seul job, job périmé => nouveau job |
| RK-08 | `domain-post` | Implémentation des trois lectures de RK-03 | tests d'intégration sur plafond par auteur et identifiants absents |
| RK-09 | `contracts` | DTO web du ranking écrits **à la main** dans `src/gateway/ranking/{request,response}/` (types `*Request` et `*WebResponse` partagés par la gateway et l'application), sur le modèle de `src/gateway/social/request/feed.request.ts`. Le reste de `contracts` est généré par la CI : ne pas y toucher | types exportés par l'index ; build vert |

`domain-social` ne change pas : `getRecommendedEventIds(userId, filters, pagination)` prend déjà un `userId` ([01](01-etat-des-lieux.md) section 1).

## 5. Phase 3 : services dépendants

Après G2 : `yarn up` des paquets publiés dans chaque dépôt.

| ID | Dépôt | Livrable | Fait quand |
| :--- | :--- | :--- | :--- |
| RK-10 | `ms-social` | Handler `AdminGetRecommendedEventIds` (contrôleur, DTO, mapper, `GrpcInternalGuard`) ; skill `volontariapp-grpc-microservice` | `analyze_grpc AdminGetRecommendedEventIds` montre contrat, handler et test ; wire-format sans rupture |
| RK-11 | `ms-post` | Handlers des 3 RPC de RK-03 ; migration domaine `CREATE INDEX ... ON posts ("authorId","createdAt" DESC)` ; resynchronisation par `sync-migrations.sh` | tri `createdAt DESC, id DESC`, plafond par auteur par `ROW_NUMBER()`, aucune erreur pour un identifiant absent |

## 6. Phase 4 : le domaine `ranking`

Skills : `volontariapp-scaffold-microservice` (séquence), `volontariapp-implement-async-job-flow`, `volontariapp-implement-async-event-flow`. Modèle de structure : `ms-social` ; modèle pour `user.deleted` : `ms-storage` et `post-processor-storage`. Inventaire des fichiers : [07](07-creation-du-microservice.md).

| ID | Dépôt | Livrable | Fait quand |
| :--- | :--- | :--- | :--- |
| RK-12 | `ms-ranking` (**nouveau dépôt**) | Amorçage, base PostgreSQL, `data-source.ts`, migrations communes + `CreateRankingTables` ; contrôleurs query (`GetRankingEvents`, `GetRankingFeed`, avec `list_kind`) et command (`RequestRankingRefresh`, `UpdateUserLocation` limité par le seau `LOCATION`, `RecordEventFeedback` plafonné à 50 éléments par `@ArrayMaxSize(50)`) ; lecture avec `FALLBACK_ACTIVATED` si aucune liste ([06](06-lecture-et-206.md)) ; seau `REFRESH` | `yarn test` vert ; la lecture sans liste écrit le job hors transaction puis lève le 206 ; le sixième rafraîchissement d'une minute renvoie `refreshThrottled` ; un lot de 51 `PASS` est refusé |
| RK-12b | `ms-ranking`, `worker-ranking`, `post-processor-ranking` | Configuration par environnement : `config/{default,development,local,production,test}.config.json` et `custom-env-vars.json` avec les clés `RANKING_*` de [04](04-flux-asynchrone.md) section 11 ; `auth.internalPrivateKeyPath` et dossier `certs/` du worker ; `service.datadog.yaml` | un démarrage local lit la configuration de chaque environnement sans clé manquante |
| RK-13 | `outbox-runners/outbox-ranking` | Démon outbox (copie d'`outbox-social`, sans `domain-ranking`) | un job `PENDING` passe `COMPLETED` et arrive dans BullMQ |
| RK-14 | `post-processors-runner/post-processor-ranking` | Post-processors communs `JobOutboxSuccess` et `JobOutboxFailed` ; déclencheurs `social:user`, `EVENT_SOCIAL_WISHED` et `UNWISHED` (écrivent aussi `ranking_event_wish`), `EVENT_CREATED`, `EVENT_FINISHED` ; **feed : `POST_CREATED` (fan-out et `ranking_event_mention`), `POST_LIKED` et `POST_UNLIKED` (journal `ranking_like_log`), `POST_DELETED` (suppression de la mention)** ; **purge de compte** (`UserDeletedPostProcessor`) avec acquittement ou échec vers `ws:user-deleted-feedback`, sur la liste canonique de [13](13-decisions-v1.md) section 7 étape 4 | rejouer un message ne double aucune ligne ; après `user.deleted`, plus aucune ligne du compte dans aucune table `ranking_*` (test par table) |
| RK-15 | `workers-runners/worker-ranking` | **Trois** classes `BaseWorker` (`ranking.worker.ts`, `ranking-feed.worker.ts`, `fallback-ranking.worker.ts`) avec concurrence câblée ; handlers `ComputeUserRanking`, `ComputeUserFeed`, `FanoutRanking` ([04](04-flux-asynchrone.md) sections 5 à 7) ; `startedAt` lu par `clock_timestamp()` sur la base ; écriture finale avec job de suite si la demande survit ; clients gRPC `ms-social`, `ms-event`, `ms-post` avec jeton interne en cache 4 min ; popularité lue dans les tables locales | un calcul de bout en bout écrit la liste ; la coalescence saute un doublon ; une demande arrivée pendant le calcul déclenche un second calcul ; `NoopRankingScorer` donne `source = STRUCTURAL_ONLY` |
| RK-16 | `ws-service` | `USER_RANKING_DELETED` ajouté aux `expects` de `user.deleted` (`config/default.config.json`) ; post-processors et options de feedback (modèle `user-storage-deleted*`) ; notification `RANKING_READY` vers le client. **Le code s'écrit après G2 mais ne se déploie qu'en vague 2** | une suppression de compte de test réussit avec le gather à 5 acquittements ; elle échouait à 60 s si `ws-service` était déployé avant `post-processor-ranking` |

Ordre interne : RK-12 -> RK-12b -> RK-13 -> RK-14 ; RK-15 en parallèle de RK-14 après RK-12 ; RK-16 après RK-14 en production.

## 7. Phase 5 : gateway

| ID | Dépôt | Livrable | Fait quand |
| :--- | :--- | :--- | :--- |
| RK-17 | `api-gateway` | `@Controller('ranking')` : `GET /ranking/events`, `GET /ranking/feed`, `POST /ranking/refresh` (corps `{listKind}`), `POST /ranking/events/feedback`, `PUT /ranking/location` ; **pas de `?refresh=true`** ; orchestration : ordre de `ms-ranking`, contenu de `ms-event` (pagination explicite) ou `ms-post.ListPostsByIds`, réordonnancement, filtrage des événements commencés, terminés ou complets, **blocages appliqués à la lecture** (`GetMyBlocks`, `GetWhoBlockedMe`), propagation du 206 ; plafond de `limit` ; skill `volontariapp-api-gateway` | test de routage (pas de collision avec `@Get(':id')`) ; un auteur bloqué disparaît du feed sans recalcul ; Swagger à jour ; `e2e-matrix.json` mis à jour |

## 8. Phase 6 : déploiement

Skills : `volontariapp-deploy-gitops`, `volontariapp-sealed-secrets` (`volontariapp-ci-tools` reporté, décision 31).

| ID | Livrable | Fait quand |
| :--- | :--- | :--- |
| RK-18a | `deploy/apps/base/ms-ranking/` (4 déploiements : service, outbox, post-processor, worker), `service.yaml`, base PostgreSQL, NetworkPolicies default-deny, overlays, application ArgoCD | `kustomize build` valide ; les pods démarrent |
| RK-18b | Secrets scellés (**G3**, étape humaine : skill `wizard`) : `TYPESAFE_API_KEY`, `RANKING_LOCATION_KEY` (32 octets aléatoires), clé de signature interne | aucun secret en clair dans Git |
| RK-18c | Racine `meta` : `sync-migrations.sh` (ajouter `"ranking"`), `e2e-matrix.json` de `api-gateway` et de chaque `ms-*` concerné, `.gitignore`, `volontariapp.code-workspace`, configuration `mesh-mcp` | `./sync-migrations.sh` couvre `ms-ranking` ; la matrice e2e liste `ms-ranking` |
| RK-18d | Observabilité : métriques et alertes de [08](08-tests-observabilite-securite.md) (dont alertes sur `jobs_outbox` et `job_audit`), CronJob de purge des listes inactives si retenu | une alerte se déclenche sur un job `FAILED` de test |

**Déploiement en deux vagues (G4).** Vague 1 : tout `ms-ranking`, dont `post-processor-ranking`. Vague 2 : la configuration de `ws-service` (RK-16). Entre les deux, vérifier que `post-processor-ranking` consomme `user:deleted:ranking`.

## 9. Phase 7 : application

| ID | Livrable | Fait quand |
| :--- | :--- | :--- |
| RK-19 | Voir [15](15-nativapp.md) : couche API et hooks, écran de swipe branché sur `/ranking/events`, retour `PASS` en lot, synchronisation de la position, rafraîchissement par `POST /ranking/refresh`, handler `RANKING_READY`, feed de l'accueil. **La carte n'est pas modifiée.** Lire d'abord les skills de `nativapp/.agents/skills/` exigées par `nativapp/CLAUDE.md` | tests verts ; `useGetEvents` inchangé ; la carte et la recherche fonctionnent comme avant |

## 10. Phase 8 : qualité et scorer sémantique

| ID | Livrable | Fait quand |
| :--- | :--- | :--- |
| RK-20 | Jeu d'essai : faux utilisateurs avec historiques (en cours côté équipe) et 20 couples profil/événement étiquetés ; calibrage des poids ([13](13-decisions-v1.md) section 2) ; scénario de démonstration de [09](09-plan-de-livraison.md) section 6 | le classement respecte les étiquettes ; poids ajustés et `FORMULA_VERSION` incrémentée |
| RK-20b | Test de non-régression de la carte : dans `nativapp`, les tests existants de l'exploration, du sélecteur d'événement (`event-picker-modal.test.tsx`) et du profil public passent sans modification ; dans la gateway, `GET /events` répond comme avant | les deux suites vertes |
| RK-21 | Adaptateur Jev derrière `RankingScorer` ([05](05-scoring-et-jev.md), [16](16-jev-ou-embeddings.md)) : une requête, N questions `noul`, repli structurel, coupe-circuit. **Prérequis : politique de conservation de TypeSafe AI obtenue** (décision 33) | `source = FULL` ; erreurs 401, 422, 429, 529 traitées ; test de non-régression sur les champs interdits |
| RK-22 | **Optionnel, expérience** : adaptateur par embeddings ([16](16-jev-ou-embeddings.md)) et comparaison avec RK-21 sur le jeu d'essai | rapport de comparaison consigné dans `docs/` |
| RK-23 | Skills `volontariapp-*` resynchronisées (`evolve.py plan`, `sync`, `learn`), `docs/matching` relu | `evolve.py plan` ne liste plus rien |

## 11. Définition de « terminé » pour la V1

- RK-01 à RK-19 et RK-20b livrés, tests verts en CI, STOP respectés.
- Un compte neuf obtient un 206 puis la liste via WebSocket ; un utilisateur avec historique obtient une liste classée avec `reasons`.
- Les swipes à gauche sont enregistrés et l'événement disparaît 30 jours.
- Une suppression de compte purge `ms-ranking` et finalise (`PENDING_DELETION` levé).
- La carte et la recherche d'événements fonctionnent comme avant.
- Limites connues documentées : `Admin*` sans contrôle de rôle, chemin d'échec des jobs ([04](04-flux-asynchrone.md) section 10), journal de likes non chiffré (décision 30).
