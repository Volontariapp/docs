# 11 - Passation pour les prochains agents

État au 2026-11-10 vers 14:00 (UTC). Ce document dit où en est chaque chantier, ce qui reste à faire, dans quel ordre, et les pièges à connaître. Les détails sont dans les chapitres [08](08-memoire-vague2-et-400.md), [09](09-demarrage-a-froid.md) et [10](10-suites.md) de ce dossier, et dans le dossier [`optimisation-ecritures/`](../optimisation-ecritures/README.md).

## 1. À lire d'abord

| Fait | Source |
| :--- | :--- |
| **Il n'y a pas de vrais utilisateurs en prod** (Victor, 2026-11-10) : rampes avec écritures, likes et redémarrages autorisés à toute heure. À revérifier avant le lancement public. | décision de Victor |
| Victor autorise l'agent à lancer les rampes et toutes les commandes `kubectl`. Le classifieur de permissions refuse en revanche les fusions de PR (`gh pr merge`, avec ou sans `--admin`) : **c'est Victor qui fusionne**, l'agent lui donne les commandes exactes. | session du 2026-11-09 |
| Le verrou de la règle du STOP (`.claude/hooks/stop-rule-guard.sh`) s'applique à toute la session, sous-agents compris, et à tout dépôt dont un `package.json` dépend de `@volontariapp/*`, y compris `traffic-simulator`. Ordre : les consommateurs d'abord, puis `npm-packages`, puis une seule publication, `npm view` pour chaque paquet, et enfin `release`. | `AGENTS.md`, section 1 |
| Éviter les minutes :00, :15, :30, :45 (`ms-storage-purge`) pour les tests. | skill `volontariapp-load-ramp` |

## 2. État par chantier

### 2.1 Démarrage à froid (chapitre 09) : presque fini

En prod :
- Neo4j à 2 CPU (deploy#75) ;
- requests CPU relevées, gateway fixée à 7 pods, quota de `prod` à 10 CPU ;
- driver Neo4j avec un pool de 32 par pod, préchauffage au démarrage et toutes les 5 min (ms-social#75) ;
- timeout de 1,8 s sur les lectures Cypher (`domain-social` 0.20.0, ms-social#76) ;
- readiness de ms-social sur `/health`.

Mesures après redémarrage de Neo4j :

| Rafale (100 req/s, mélange `events-list-app:40,posts-list:30,me:20,is-following:10`) | Erreurs |
| :--- | ---: |
| avant les correctifs, 30 s après le redémarrage | 80 % |
| après les correctifs, 30 s après | 52 % (events-list-app à 100 %) |
| après les correctifs, 6 min après (préchauffage passé) | **0 %** |

Le froid vient du JVM et des plans de Neo4j, pas du disque : 21 Mo de données pour un cache de pages de 512 Mo.

**Reste à faire** : une PR ms-social, en cours au moment de la passation, qui lance le préchauffage dès que Neo4j revient et met la readiness en 503 pendant ce temps (plafond de 30 s). **Critère d'acceptation** : redémarrer `neo4j-0`, attendre 30 s, lancer la rafale ci-dessous ; il faut moins de 1 % d'erreurs.

```bash
LOAD_CONFIRM=false LOAD_MIX="events-list-app:40,posts-list:30,me:20,is-following:10" LOAD_STEPS=100 LOAD_STEP_SECONDS=60 LOAD_WARMUP_SECONDS=0 LOAD_ONSET_SECONDS=15 LOAD_ABORT_WINDOWS=99 yarn --cwd traffic-simulator load
```

À lancer avec les variables de `nativapp/.env` (`LOAD_BASE_URL="$API_GATEWAY_URL"`, jeton Cloudflare Access ; ne jamais afficher les secrets).

### 2.2 Arrêt des post-processors (chapitre 10, section 3) : livré

- `@volontariapp/post-processors` 3.6.0 (npm-packages#319) : option `handleSignals` et `stop()` qui renvoie sa promesse en cours.
- ws-service#59 et post-processors-runner#76 : un registre unique avec `handleSignals: false`, arrêt attendu avant la déconnexion de Redis, `enableShutdownHooks()` dans les runners. Fusionnés.
- **Reste à vérifier après déploiement** : `kubectl logs -n prod <pod> --tail=-1 | grep -c MaxListeners` doit valoir 0 sur ws-service, post-processor-event, -ranking, -storage et -user.
- Dette : le registre est copié dans les 6 apps du runner. Le remonter dans un paquet coûterait un cycle STOP.

### 2.3 Rampe réaliste (chapitre 10, section 2)

- Fusionnés dans traffic-simulator : L1 (#11), L2 (#12), L3 (#13), L4 (#14), L5 (#15), L6 (#16).
- Fusionné dans meta : L7 (#61). La skill `volontariapp-load-ramp` est à jour, avec le script `async-recorder.sh`.
- L2 validé à 10 req/s en mode `app` : 0 erreur, les 16 routes servies.
- **En cours** : validation de L3 et L4 avec `LOAD_WRITES=default,like-toggle,comment-cycle,post-cycle`, à 10, 25 puis 50 req/s, avec nettoyage vérifié (`load:cleanup`).
- **Ensuite** : la rampe réaliste jusqu'à 300 req/s :

```bash
LOAD_MODE=app LOAD_WRITES=default LOAD_STEPS="100,150,200,250,275,300" LOAD_STEP_SECONDS=90 LOAD_RAMP_UP_SECONDS=10 LOAD_WARMUP_SECONDS=10 LOAD_ONSET_SECONDS=10 LOAD_CONFIRM=false yarn --cwd traffic-simulator load
```

  Avant de la lancer : `record-ramp.sh` et `async-recorder.sh` (dossier `.agents/skills/volontariapp-load-ramp/scripts/` de meta), simulateur de fond à 0 réplica. Après : `yarn --cwd traffic-simulator load:cleanup`, puis `--dry-run` pour vérifier qu'il ne reste rien.
- Constat : ws-service diffuse chaque like et chaque commentaire à tous les clients connectés (`broadcastExcept`). Sans vrais utilisateurs, c'est sans conséquence.

### 2.4 Optimisation des écritures (dossier `optimisation-ecritures/`)

Livré :
- `OUTBOX_MAX_IDLE_INTERVAL_MS` n'était lue par aucun runner, d'où outbox-runners#48 (lecture de la variable) et deploy#76 (5000 vers 1000 ms). Fusionnés ; déploiement à vérifier.

Ouvert :
- **deploy#77** (`pg_stat_statements`) : elle redémarre les 7 bases Postgres. À fusionner hors rampe, puis lancer `CREATE EXTENSION` base par base (procédure dans `optimisation-ecritures/02-mesure.md`, section 2).
- meta#62 : leçon de skill sur les variables d'environnement non liées.

Décisions prises (valent décision de Victor) :
- **L9 (ms-social), Postgres d'abord** : la transaction écrit la table `social_edge` et un job `SOCIAL_EDGE_APPLY` ; `worker-social` fait converger Neo4j, puis émet l'événement métier avec un id déterministe. L'événement part après Neo4j, parce que nativapp relit `likes-summary` à la réception de `POST_LIKED`. Worker : concurrence 4, 100 jobs/s, 12 tentatives, puis DLQ.
- **Les 147 événements bloqués depuis le 2026-11-07** ne sont pas rejoués automatiquement. La reprise automatique ne traite que les lignes de moins de 15 min ; les autres passent par une commande explicite.
- **L11 (ms-ranking)** : option B, puis A.

**Reste à faire** : les PR `npm-packages`, regroupées pour limiter les cycles STOP.
- PR A : L3, L4 et L5 (`post-processors`, `database`, `config`, `outbox`).
- PR B : L9 (`messaging`, `domain-social`).
- Puis les consommateurs, et L6 à L8, L10 et L12. L'ordre L3, puis L4, puis L5 est obligatoire.
- Le code n'était pas encore écrit à la passation : l'agent attendait le feu vert `npm-packages`, à donner une fois la PR ms-social du préchauffage ouverte.

## 3. PR ouvertes à la passation

| PR | Quoi | À faire |
| :--- | :--- | :--- |
| deploy#77 | `pg_stat_statements` | fusion hors rampe, puis `CREATE EXTENSION` |
| meta#62 | leçon sur les variables non liées | fusion |
| ms-social#77 | préchauffage au retour de Neo4j (sonde toutes les 5 s), readiness en 503 pendant 30 s au plus ; 222 tests verts | fusionner **en même temps que** deploy#78 |
| deploy#78 | readinessProbe de ms-social à `periodSeconds: 5`, `failureThreshold: 1` ; `/health` répond en 0,11 à 0,18 s. Sans elle, le 503 de ms-social#77 n'a presque aucun effet | fusionner avec ms-social#77, puis le test d'acceptation de la section 2.1 |
| (images) post-processors-runner#76 | le 2026-11-10, seuls `post-processor-social`, `-storage` et `-post` tournaient sur `sha-54928b2` ; `-event`, `-ranking` et `-user` étaient restés sur `sha-19e0d89`, et affichaient encore `MaxListenersExceededWarning`. `ws-service` (`sha-fae34ea`) : 0 avertissement | vérifier dans `deploy` les images des trois apps, et les monter à `sha-54928b2` si elles manquent (montée d'image dans le désordre, voir la skill `volontariapp-deploy-gitops`) |

## 4. Pièges appris

- Chart Neo4j 5.20.0 : les ressources se règlent sous `neo4j.resources`. Une clé `resources:` à la racine est ignorée sans avertissement : Neo4j tournait avec 1 CPU au lieu de 2.
- Une variable de `deploy` n'est lue que si `custom-env-vars.json` la lie (piège trouvé sur `OUTBOX_MAX_IDLE_INTERVAL_MS`).
- Le chart Traefik impose `GOMEMLIMIT` à 90 % de la limite mémoire et ignore la valeur passée par `env`.
- Le préchauffage de ms-social journalise son tour périodique en `debug` : invisible avec le niveau `info`.
- `XINFO GROUPS` renvoie un `lag` faux sur les streams tronqués : mesurer le retard par l'âge (`behind_ms` de `async-recorder.sh`).
- Pour reproduire un démarrage à froid sans attendre une heure : redémarrer le composant soupçonné, puis lancer une rafale immédiate (`LOAD_WARMUP_SECONDS=0`, `LOAD_ONSET_SECONDS`, `LOAD_ABORT_WINDOWS=99`).
- Les tests à froid déclenchent des alertes Datadog : prévenir Victor ou mettre les monitors en sourdine.
- Le ballon Proxmox de la VM 101 : plancher à 14 Go appliqué, et 16 Go fixes au prochain démarrage de la VM. Le pire cas sur l'hôte passera alors à 32 Go pour 31,8 Go physiques.
- `neo4j-0` a été redémarré à 21:49:07 le 2026-11-09 par une origine non déterminée.

## 5. Relevés

Bruts, non versionnés, dans `meta/profiles/` : `ramp-vague2-deps`, `cold-neo4j`, `cold-neo4j-restart`, `cold-acceptance`, `cold-acceptance-warm`. Le handoff de meta est `handoffs/montee-en-charge-froid.md`.
