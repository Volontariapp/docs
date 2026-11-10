# 10 - Suites : rampe réaliste, arrêt des post-processors, écritures

État au 2026-11-10 au matin. Ce chapitre rassemble les chantiers ouverts le 2026-11-09 au soir, les décisions prises par Victor et l'ordre de mise en œuvre. Chaque chantier a été préparé par un sous-agent Claude Code, relu par l'orchestrateur, puis validé par Victor.

## 1. Vue d'ensemble

| Chantier | Où | État |
| :--- | :--- | :--- |
| Démarrage à froid (chapitre 09) | deploy#75, ms-social#75, npm-packages#318 | PR ouvertes, CI verte |
| Rampe réaliste, lots L1 à L8 | traffic-simulator | L1 fusionné (#11), L2 ouvert (#12), L3 à L8 à faire |
| Arrêt des post-processors (SIGTERM) | npm-packages puis ws-service et post-processors-runner | étape A en cours, étape B après publication |
| Optimisation des écritures | dossier `optimisation-ecritures/` du dépôt `docs` | analyse en cours |

## 2. La rampe réaliste

### 2.1 Pourquoi

La rampe actuelle envoie des lectures sur 4 routes, qui sont des replis de l'application (chapitre 08, section 6). Victor veut pouvoir dire que la plateforme tient 300 req/s sur **l'ensemble de l'application**, écritures comprises.

### 2.2 Les décisions de Victor (2026-11-09)

| Question | Décision |
| :--- | :--- |
| Écritures en production | oui, avec un pool de comptes `load.NNNN` isolé ; les actions ne visent que les objets du pool ; chaque like, wish, follow ou participation est défait dans la session ; `load:cleanup` à la fin |
| Marqueur « compte synthétique » dans ranking, leaderboard et badges | plus tard ; en attendant, les comptes load gagnent des badges et apparaissent au classement |
| Mélange | celui du plan (88 % de lectures, 12 % d'écritures, 26 routes déduites des écrans de nativapp), recalé ensuite avec les hits par route de Datadog |
| Relevé de l'asynchrone | autorisé en lecture seule : longueur des streams et des DLQ, files BullMQ, lignes `PENDING` de l'outbox |
| Définition de « 300 req/s » | requêtes HTTP reçues par la gateway ; connexions WebSocket comptées à part |
| Effets exclus par défaut | position, création d'événement (géocodage externe), upload et scan, présence |
| Seuil de l'asynchrone | p95 du délai entre l'écriture et la notification WebSocket sous 30 s |

### 2.3 Les lots

| Lot | Contenu | État |
| :--- | :--- | :--- |
| L1 | profil d'attaque (`LOAD_RAMP_UP_SECONDS`, `LOAD_WARMUP_SECONDS=0`) et lecture du début de palier (`LOAD_ONSET_SECONDS`) ; envoi multi-méthodes ; mode `routes` inchangé | fusionné, traffic-simulator#11 |
| L2 | mode `app` : les 16 lectures de nativapp (dont `/ranking/feed`, `/ranking/events`, `POST /social/likes-summary`), identifiants récoltés dans les listes | fusionné, traffic-simulator#12 (`65e1b3ad`) ; validé en prod le 2026-11-10 à 08:05 (UTC) à 10 req/s : 602 requêtes, 0 erreur, aucun 4xx, p95 348 ms, 26 réponses 206 du ranking, les 16 routes servies |
| L3 | pool `load.NNNN`, `load:setup` et `load:cleanup` idempotents, `--dry-run` | à faire |
| L4 | écritures en bascule sur les seuls objets du pool | à faire |
| L5 | sessions réalistes (chaîne de Markov par écran), rapport par type | à faire |
| L6 | sonde WebSocket (20 sockets d'auteurs), arrêts sur le délai asynchrone et sur toute entrée de DLQ | à faire |
| L7 | relevé `async.log`, mise à jour de la skill `volontariapp-load-ramp` | à faire |
| L8 | validation en prod à 10, 25 puis 50 req/s, nettoyage, DLQ vide | à faire |

Ce que la préparation de L3 et L4 a établi (FAIT, lecture du code sur `origin/main`, `analyze_impact` sur les 16 racines) :
- **Follow** : une écriture Neo4j seule. Le job `FOLLOW_USER` a un consommateur (`worker-social follow-user.handler.ts:11`) mais aucun producteur trouvé dans les 16 racines.
- **Participate** : une écriture Neo4j seule, qui retire le wish existant. Aucun événement émis. Seule l'existence du nœud social est contrôlée, pas l'état de l'événement.
- **Attendance** : `EVENT_SOCIAL_ATTENDANCE_SET` est consommé par ws-service (push WebSocket). Elle reste exclue.
- **Like** : ranking, badges (`post-processor-user`) et push WebSocket. **Wish** : ranking et badges.
- **Événements de fixture en DRAFT**, l'état par défaut : le ranking ne propose que les événements PUBLISHED, donc les vrais utilisateurs ne les voient pas, alors que wish et participate y fonctionnent.
- **Posts de fixture** : ils seraient visibles des vrais utilisateurs (`/ranking/feed`, `/posts`) pendant leur durée de vie, et rien ne permet de les masquer sans le marqueur « compte synthétique ». Décision de l'orchestrateur (Victor a demandé de ne pas lui poser de question) : un premier passage L8 **sans** like, commentaire ni création de post ; ces trois actions seront ajoutées ensuite, avec un contenu proche de celui du simulateur de fond et une suppression en fin d'essai.

Points d'attention :
- Les comptes neufs reçoivent un 206 du ranking et déclenchent un calcul : il faut chauffer les listes avant de mesurer.
- Une écriture lente remplit l'outbox après la fin du palier : il faut attendre un retard nul avant le palier suivant.
- La comparaison avec les chiffres du chapitre 08 serait trompeuse : ce n'est plus la même charge. Les deux séries doivent rester séparées.

## 3. L'arrêt des post-processors

### 3.1 Le constat (FAIT)

Au démarrage, ws-service affiche `MaxListenersExceededWarning` : 11 écouteurs SIGTERM et 11 SIGINT pour une limite de 10. Ce n'est **pas une fuite** : le nombre est fixe. Chaque post-processor pose ses propres écouteurs à son démarrage (`npm-packages/packages/post-processors/src/core/processors/base.post-processor.ts:117`, `:192-194`), et ws-service en démarre 41. Au total : 43 écouteurs SIGTERM et 42 SIGINT. Même message dans `post-processor-ranking`, `-event`, `-storage` et `-user`.

### 3.2 Le vrai défaut

Les post-processors ne font pas partie du cycle de vie de Nest. À un SIGTERM, Nest ferme Redis et tue le processus sans attendre leur `stop()`. Et un second appel à `stop()` revient tout de suite sans attendre le premier (`base.post-processor.ts:149`).

Conséquence, INFERENCE : aucun message n'est perdu, mais ceux qui étaient en cours sont repris par le nouveau pod après 60 à 90 s (`XCLAIM`). À chaque déploiement de ws-service, des notifications WebSocket peuvent donc arriver avec ce retard, et parfois deux fois.

L'ordre d'arrêt de Nest 11.2.8 (FAIT, `nest-application-context.js`) : `onModuleDestroy`, puis `beforeApplicationShutdown`, puis la fermeture. Le Redis global est déconnecté dans `onModuleDestroy`, donc avant `beforeApplicationShutdown`.

### 3.3 Le correctif

| Étape | Où | Contenu |
| :--- | :--- | :--- |
| A | `@volontariapp/post-processors` (STOP) | option `handleSignals`, vraie par défaut ; `stop()` garde sa promesse en cours et la renvoie aux appels suivants ; bump mineur |
| B | ws-service et les 6 apps de post-processors-runner, après publication de A | une fabrique unique qui construit les post-processors avec `handleSignals: false` ; le Redis global déplacé dans son propre module, détruit en dernier ; les instances arrêtées et attendues dans `onModuleDestroy` d'un module détruit avant ; `enableShutdownHooks()` à la place de `process.on` plus `process.exit(0)` dans les runners ; un test qui prouve qu'un lot en cours est acquitté avant la fermeture de Redis |

Écarté : relever la limite d'écouteurs (`setMaxListeners`), qui ne ferait que cacher l'avertissement.

## 4. L'optimisation des écritures

Une première lecture du code (sans mesure) désigne le socle partagé `@volontariapp/database` comme le plus gros gisement : chaque écriture paie des allers-retours SQL inutiles (un `update()` en fait 6 pour changer une colonne), et l'outbox pousse et acquitte ses lignes une par une. Un sous-agent vérifie chaque constat dans le code et rédige le dossier `optimisation-ecritures/` du dépôt `docs`, avec un plan en lots. La mesure vient en premier : `pg_stat_statements` et les routes d'écriture de la rampe réaliste (lots L4 et L8 ci-dessus).

## 5. Ordre de mise en œuvre

1. **Démarrage à froid** : fusionner deploy#75 (redémarre Neo4j avec 2 CPU), puis ms-social#75. Ensuite npm-packages#318 et l'étape A des post-processors, ensemble pour un seul cycle STOP : publication par la CI, vérification par `npm view`, levée du verrou.
2. **Consommateurs** : `yarn up @volontariapp/domain-social` dans ms-social ; étape B dans ws-service et post-processors-runner.
3. **Critère d'acceptation** : le test du redémarrage de Neo4j (chapitre 09, section 6).
4. **Rampe réaliste** : L2 validée, puis L3 à L8. Le verrou STOP bloque les éditions dans traffic-simulator, qui dépend de `@volontariapp/contracts`, jusqu'à sa levée.
5. **Écritures** : relecture du dossier `optimisation-ecritures/`, puis implémentation par lots.

## 6. Règles de travail apprises

- Le verrou du STOP (hook `stop-rule-guard.sh`) s'applique à toute la session, sous-agents compris, et à tout dépôt dont un `package.json` dépend de `@volontariapp/*`, y compris `traffic-simulator`. Il faut donc ordonner les chantiers : d'abord les éditions chez les consommateurs, puis `npm-packages`, puis un seul cycle de publication.
- Les fusions de PR demandent l'intervention de Victor : le classifieur de permissions refuse les fusions de l'agent, même sur une PR verte (`gh pr merge`, avec ou sans `--admin`).
- Le profil d'attaque de la rampe (`LOAD_WARMUP_SECONDS=0`, `LOAD_ONSET_SECONDS`, `LOAD_ABORT_WINDOWS=99`) suffit à reproduire un démarrage à froid sans attendre une heure : redémarrer le composant soupçonné, puis lancer une rafale immédiate.
- Victor a autorisé l'agent, le 2026-11-09 au soir, à lancer lui-même les rampes et les commandes `kubectl`. L'agent annonce toujours une action perturbante (suppression de pod, redémarrage de Neo4j), évite les minutes de `ms-storage-purge` (:00, :15, :30, :45) et n'affiche aucun secret.
