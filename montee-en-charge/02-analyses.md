# 02 - Analyses

Chaque analyse donne : le constat, la preuve, la conclusion et le niveau de confiance. Les analyses abandonnées ou corrigées en cours de route sont listées à la fin, parce qu'elles évitent de refaire les mêmes erreurs.

## 1. Où part le CPU à 200 req/s

Relevé de 22:44:20Z, au pic du palier à 200 req/s. **FAIT** : `cpu.log` de l'enregistreur du soir.

| Poste | vCPU | Part du nœud (11,45) |
| :--- | ---: | ---: |
| `api-gateway` (5 pods, 650 à 753m chacun) | 3,48 | 30 % |
| `ms-event` (2 pods : 822m et 390m) | 1,21 | 11 % |
| `ms-social` (2 pods : 748m et 384m) | 1,13 | 10 % |
| `ms-post-db` | 0,82 | 7 % |
| `ms-post` (2 pods : 509m et 218m) | 0,73 | 6 % |
| `ms-event-db` | 0,64 | 6 % |
| `neo4j` | 0,62 | 5 % |
| `datadog-agent` | 0,57 | 5 % |
| `ms-user` | 0,35 | 3 % |
| `traefik` | 0,28 | 2 % |
| Somme des pods | 10,36 | 90 % |
| Système (noyau, kubelet, containerd) | 1,09 | 10 % |

Trois lectures :

- **La gateway est le plus gros poste** : 17 ms de CPU par requête (3,48 vCPU pour 200 req/s). La section 5 de ce chapitre regarde où part ce temps.
- **Les services en double sont déséquilibrés** : un réplica de chaque paire porte environ le double de l'autre (voir le point 3).
- **L'agent Datadog** passe de 80m au repos à 568m à 200 req/s puis 676m à 250 req/s : il coûte plus que `ms-user`. Cette hausse mêle journaux, traces et métriques ; la part des journaux seule n'est pas isolée (NON VERIFIE).

## 2. `ms-social` tué par manque de mémoire (corrigé)

- **Constat** : lors du premier palier à 100 req/s avec la route de l'application, `ms-social` est tué à 21:31:34Z, 17 secondes après le début du palier. Les routes qui l'appellent échouent à 100 % (`events-list-app` 1 229 erreurs sur 1 229, `is-following` 292 sur 292) ; `me`, qui ne le touche pas, reste à 0 %.
- **Preuve (FAIT)** : `OOMKilled`, code 137, limite mémoire de 256Mi (`kubectl get pod -o jsonpath`). Au repos il consommait déjà 123Mi (`kubectl top`). Les dernières lignes de son journal avant la mort sont les 5 lectures d'exclusions d'une requête de l'application (événements créés, participés, souhaités, blocages, bloqué par).
- **Cause** : `EventSocialFilterService` lisait ces ensembles avec des appels paginés de 100 identifiants (jusqu'à 100 pages), soit au moins 10 requêtes Cypher par requête de l'application et jusqu'à 10 000 identifiants par liste, alors que `ms-event` n'en garde que 1 000. Avec le comptage des participants, une requête faisait 6 appels `ms-social`.
- **Correctif livré** : un appel `GetSearchExclusions` plafonné à 1 000 identifiants par liste, avec des drapeaux de troncature (voir [chapitre 01](01-mesures-et-methode.md), section 5), et `ms-social` à 512Mi avec 2 réplicas.
- **Vérifié après correctif (FAIT)** : 2 appels `ms-social` par requête au lieu de 6 (journaux de `ms-social`), mémoire de 111 à 126Mi sur 512Mi, 0 redémarrage de 25 à 250 req/s.

## 3. Les connexions gRPC ne sont pas réparties entre les réplicas

- **Constat (FAIT)** : à 200 req/s, `ms-event` 822m contre 390m, `ms-social` 748m contre 384m, `ms-post` 509m contre 218m. À 250 req/s, `ms-social` 726m (sur sa limite de 800m) contre 473m.
- **Mécanisme** : les clients gRPC sont créés sans aucune option de canal (`npm-packages/packages/contracts-nest/src/grpc.helpers.ts:87-101`, FAIT) et les `Service` Kubernetes de ces `ms-*` sont des `ClusterIP`. Chaque pod de gateway ouvre donc une seule connexion HTTP/2 vers un service, et `kube-proxy` choisit un réplica **une fois, au moment de la connexion**. Avec 3 à 6 pods de gateway et 2 réplicas, la répartition est un tirage au sort qui se refait à chaque création de pod.
- **Conséquence** : le réplica le plus chargé atteint sa limite de CPU (800m pour `ms-social`) bien avant que le service soit à sa capacité réelle. Ajouter un 3e réplica n'y change rien tant que la répartition reste au hasard.
- **Conclusion** : confiance haute sur le mécanisme et le déséquilibre ; le gain exact d'un équilibrage reste une INFERENCE (le réplica le plus chargé baisserait d'un quart à un tiers).

## 4. L'HPA de la gateway et les pods froids

L'HPA ajoute jusqu'à 2 pods par minute sans délai de stabilisation (FAIT : `hpa.yaml`). Voici l'ordre des événements dans chaque palier :

| Palier | Hausse de latence visible | Création de pods | Ordre |
| :--- | :--- | :--- | :--- |
| 200 req/s, 22:43 | latence moyenne Traefik 116 ms à 22:43:30, 1 127 ms à 22:44:06 | 22:43:39 puis 22:43:54 (3 à 5 pods) | la hausse **précède** la création de 9 s |
| 250 req/s, 22:47 | effondrement dans les 30 premières secondes | 6e pod vers 22:47:09 | simultanés, non départageables |
| 150 req/s, 23:23 | fenêtre 3 (p95 499 ms), fenêtre 4 (2 499 ms) | 23:24:26 (4e pod) | la première hausse **précède** la création de 5 à 10 s |
| 150 req/s, 23:33 | latence moyenne 100 ms à 23:33:57, 505 ms à 23:34:02, 1 569 ms à 23:34:07 | 23:33:57 (**2 pods**) | la hausse **suit** la création |
| 150 req/s, 23:38 | première dégradation à 23:39:32 (294 ms), seconde à 23:40:08 (1 222 ms) | 23:39:57 (1 pod) | la première **précède** de 25 s, la seconde **suit** |
| 150 req/s, 22:40 | un à-coup d'une seconde à 22:41:12 | **aucune** | stable le reste du palier |

FAIT pour l'ensemble : `kubectl describe hpa`, dates de création des pods, `traefik.log`, sorties de `yarn load`.

- **Hypothèse (INFERENCE)** : un pod neuf reçoit sa part du trafic dès qu'il répond, alors que son code JavaScript n'est pas encore optimisé, ses connexions gRPC ne sont pas ouvertes et la clé RSA n'est pas importée. Avec 2 pods neufs sur 5, 40 % du trafic passe par des pods froids.
- **Ce qui la soutient** : à 23:33 et pour la seconde dégradation de 23:39, la hausse suit la création ; le seul palier à 150 req/s sans création tient (à un à-coup près).
- **Ce qui la limite** : dans trois cas sur six la latence monte **avant** la création du pod. L'HPA réagit au CPU déjà élevé : la création est au moins autant un symptôme qu'une cause. Le nœud n'était pas saturé (52 à 66 %), la gateway profilée n'était occupée qu'à 39 %. Le test censé l'isoler ("5 pods chauffés") n'en était pas un : l'HPA avait retiré un pod vers 23:38:40 puis en a ajouté un à 23:39:57.
- **Statut : amplificateur possible, déclencheur non démontré.** Pour la tester proprement, il faut figer le nombre de pods pendant un palier (chapitre 03, phase 0).

## 5. Le profil CPU de la gateway

- **Méthode (FAIT)** : profil de 30 s d'un pod de gateway en production (`SIGUSR1`, puis `capture-cpu-profile.mjs`), pendant le palier à 150 req/s de 23:33. Il couvre l'effondrement lui-même. Le pod n'était **occupé qu'à 39 %** (11,8 s sur 30,5 s).
- **Résultat (FAIT)** : temps propre (sans les fonctions appelées) par poste, en % du temps occupé.

| Poste | Part | Famille |
| :--- | ---: | :--- |
| Ramasse-miettes (GC) | 16,0 % | allocation de mémoire |
| Écriture des journaux (`writeUtf8String` 6,3 %, `console.log` 4,2 %, `consoleCall` 3,3 %, logger 1,9 %) | environ 15 % | observabilité |
| OpenTelemetry (spans, instrumentations HTTP, Express, gRPC) | 12,7 % | observabilité |
| gRPC (`grpc-js`) | 6,1 % | coût inhérent à Node |
| Express et routeur | 5,7 % | HTTP |
| JWT (`jose`) | 2,9 % | cryptographie |
| Validation, DTO, code applicatif | environ 2 % | notre code |
| Reste (système, Node interne, autres dépendances) | environ 40 % | divers |

- **Conclusions** :
  - Le CPU de la gateway ne part pas dans notre code ni dans la validation.
  - Les journaux et OpenTelemetry cumulent environ 28 % du temps de la gateway. Ces deux postes se réduisent par configuration et alimentent le GC.
  - Le coût "inhérent à Node" pèse environ 27 % (ramasse-miettes 16 %, gRPC 6,1 %, sérialisation JSON d'Express 3,1 %, protobuf 1,7 %), et gRPC seul 6 %.
- **Limites** : un pod, une fenêtre de 30 s, pendant un incident. Les parts peuvent différer en régime stable (NON VERIFIE).

## 6. Les journaux : ce que le benchmark disait, ce que le profil dit

- **La configuration existe mais n'est jamais appliquée (FAIT)** : `LoggerConfig.level` est un champ obligatoire (`npm-packages/packages/config/src/configs/logger-config.ts`) et les fichiers de production déclarent `warn` pour la gateway, `ms-user`, `ms-social`, `ms-event`, `ms-post` et `ws-service`, `info` pour `ms-ranking` et `ms-storage`. Mais **aucun point d'entrée ne le transmet au `Logger`** : dans les 11 dépôts relus (`api-gateway`, les six `ms-*`, `ws-service`, `workers-runners`, `post-processors-runner`, `outbox-runners`), tous les `Logger.setDefaultConfig` ne passent que le format. Le logger tourne donc à son niveau par défaut, `debug`.
- **Lignes `debug` émises à chaque requête par la gateway (FAIT, lu dans `@volontariapp/auth`)** : `AccessTokenGuard`, `GrpcInternalInterceptor` et `GrpcMetadataHelper` écrivent chacun une ligne `debug`. S'y ajoutent les lignes `debug` du garde interne de chaque `ms-*` et les lignes `info` des contrôleurs.
- **Le benchmark local a sous-estimé le coût.** Mesuré sur un Mac vers un tube local, une ligne coûte 4 à 8 µs. J'en avais déduit 0,3 % du CPU. **C'était faux** : le profil de production donne environ 15 % du temps occupé de la gateway, parce que l'écriture sur la sortie standard du conteneur coûte bien plus que vers un tube local. Retenir : pour ce type de coût, seul un profil en conditions réelles fait foi.
- **Gain attendu (INFERENCE)** : 0,45 à 0,5 vCPU sur la gateway à 200 req/s, une part comparable dans les `ms-*` (non mesurée) et une baisse de l'agent Datadog. Soit 0,6 à 1,1 vCPU en tout.

## 7. OpenTelemetry

- **Constat (FAIT)** : le SDK est actif partout (`OTEL_SDK_DISABLED: "false"` dans les 27 déploiements de `deploy/apps`), avec les instrumentations automatiques de Node sauf `fs` et `dns` (`monitoring/src/tracing.ts`). Le ratio d'échantillonnage vaut son défaut, **1, soit 100 % des traces conservées** : `OTEL_TRACES_SAMPLER_ARG` n'est défini nulle part dans `deploy/apps` (`monitoring/src/sampling.ts`).
- **Poids (FAIT)** : 12,7 % du temps propre de la gateway, plus la charge de l'agent Datadog qui reçoit chaque trace.
- **Gain attendu à 10 % d'échantillonnage (INFERENCE)** : environ 0,35 vCPU sur la gateway, davantage avec les `ms-*` et l'agent. Soit 0,5 à 0,8 vCPU en tout.
- **Risque** : les moniteurs Datadog fondés sur les traces (par exemple `apm-error-rate-grpc.json`) travailleraient sur 10 % des données. Leur sensibilité n'a pas été vérifiée (NON VERIFIE).

## 8. Cryptographie à chaque requête

- **FAIT (code de `@volontariapp/auth`)** : la gateway vérifie le jeton d'accès (RS256) puis **signe un nouveau jeton interne RS256 à chaque requête**, avec un identifiant aléatoire (`jwt.service.ts:34-40`) ; chaque `ms-*` vérifie ce jeton à chaque appel gRPC.
- **Mesure (FAIT)** : `jose` pèse 2,9 % du temps propre de la gateway. La signature elle-même s'exécute dans le pool de threads de Node et n'apparaît presque pas dans le profil du fil principal (`SignJob` 0,5 %).
- **Coût de la signature (INFERENCE)** : environ 1 ms de CPU par requête pour une clé RSA de 2048 bits (la taille documentée par `generate-certs.sh` ; celle de la production est NON VERIFIEE), soit 0,2 à 0,35 vCPU à 200 req/s.
- **Levier** : réutiliser le jeton interne d'un utilisateur pendant une courte durée inférieure à son expiration. La durée d'expiration configurée (`internalExpiresIn`) n'a pas été relue.

## 9. L'hypothèse matérielle (NON VERIFIE)

- **Signes (FAIT pour chaque observation, INFERENCE pour leur lien)** :
  - Les dégradations à 150 et 200 req/s commencent presque toujours dans la troisième fenêtre, environ 30 secondes après le début du palier (23:23, 23:33, 23:38, 22:43). Le palier de 22:40 est l'exception.
  - Le CPU du nœud pour le même débit de 150 req/s a augmenté de 2 % à 58 % entre 22:41 et 23:34.
  - L'hôte est un processeur mobile de 28 W de puissance de base (i7-1360P), conçu pour tenir une puissance plus élevée pendant quelques dizaines de secondes avant de redescendre à sa limite soutenue.
- **Hypothèse** : après une trentaine de secondes de charge soutenue, la fréquence des cœurs baisse, chaque requête consomme plus de CPU-secondes, et le système bascule dans une file d'attente.
- **Ce qui l'affaiblit** : le palier de 22:40 a tenu et d'autres facteurs (HPA, répartition gRPC) coïncident aussi.
- **Test à faire** : mesurer la fréquence des cœurs et la température de l'hôte pendant un palier à 150 req/s (commandes au chapitre 03, phase 0). Si la fréquence moyenne chute d'au moins 25 % après 30 secondes, le plafond de 300 req/s dépend de la limite de puissance et du refroidissement de l'hôte autant que du logiciel.

## 10. Faut-il réécrire la gateway en Go ou en Rust ?

- **Ce que le profil permet de dire (FAIT)** : gRPC pèse 6,1 % du temps propre de la gateway, le ramasse-miettes 16 %. Le coût "inhérent à Node" est d'environ 27 %. Les journaux et OpenTelemetry (28 %) se réduisent par configuration.
- **Ce qu'un portage rapporterait au mieux (INFERENCE)** : même avec 80 % de gain sur la gateway, les pods passeraient de 10,4 à 7,6 vCPU à 200 req/s, soit environ 11,4 vCPU à 300 req/s contre un budget de 10,8. La gateway pèse 34 % du CPU des pods, donc un portage seul ne suffit pas.
- **Ce que coûterait un portage (FAIT pour les tailles)** : 54 contrôleurs, 195 fichiers de DTO, 13 710 lignes de TypeScript hors tests, un proxy WebSocket et la documentation Swagger. `proto-registry` ne génère que du TypeScript (`buf.gen.yaml` : un seul plugin, `ts_proto`) : il faudrait ajouter la génération Go, reproduire la vérification RS256 et la signature du jeton interne, et garantir des formes JSON identiques pour l'application mobile.
- **Les tests E2E ne se rejouent pas tels quels (FAIT)** : les 28 fichiers de `api-gateway/e2e/` montent l'application Nest en mémoire (`e2e/helpers/create-app.helper.ts`). Les adapter pour viser une URL est faisable mais c'est un chantier. Leur couverture en routes est NON DETERMINEE.
- **Décision** : pas de réécriture. Si, après les phases 1 à 3 du chapitre 03, la gateway pèse encore plus de 25 % du CPU et 300 req/s n'est pas atteint, la forme à étudier est un service Go limité aux quatre routes chaudes (liste d'événements, liste de posts, `me`, `is-following`), derrière Traefik, les autres routes restant sur Nest. Entre Go et Rust, Go pour une équipe de trois : mêmes gains de CPU, coût de développement plus bas.

## 11. Analyses corrigées ou abandonnées

| Ce qui avait été avancé | Ce qui est vrai | Pourquoi c'est noté |
| :--- | :--- | :--- |
| Ajouter une variable `LOG_LEVEL` lue par `@volontariapp/logger` | La configuration `logger.level` existe déjà et n'est simplement pas branchée. De plus, la skill `volontariapp-logger` interdit de lire `process.env` dans le logger (compatibilité React Native) | Ne pas créer un second mécanisme à côté du premier |
| Les journaux coûtent 0,3 % du CPU (benchmark local) | Environ 15 % du temps occupé de la gateway en production | Un micro-benchmark qui n'écrit pas sur la vraie sortie sous-estime le coût |
| "`ms-social` sature en premier à 250 req/s" | Un 6e pod de gateway est arrivé en même temps : l'effondrement est confondu avec l'effet des pods froids. `ms-social` à 726m sur 800m reste un fait, mais plus une preuve de plafond | Le plafond de 250 n'est pas démontré |
| Un cache des exclusions (blocages compris) à la gateway | Reporté : l'appel unique a retiré l'essentiel du coût, et un cache change la règle "un blocage s'applique tout de suite" | Décision de produit, pas de performance |
| Le palier "à 5 pods chauffés" isole l'effet des pods froids | L'HPA a retiré puis ajouté un pod pendant le test | Pour isoler, il faut figer le nombre de pods (chapitre 03) |
