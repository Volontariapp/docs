# 05 - Non vérifié

Ce qui n'a pas été regardé ou pas pu l'être le 2026-11-10, avec l'outil à utiliser. Toute absence affirmée ailleurs dans ce dossier cite son outil et son périmètre ; cette liste dit ce qui n'est couvert par rien.

| # | Point | Pourquoi ce n'est pas fait | Comment le vérifier |
| :--- | :--- | :--- | :--- |
| 1 | Nombre réel de requêtes par opération en prod | `pg_stat_statements` n'est pas chargé ; l'activer demande un redémarrage et une écriture (hors mandat) | L0, puis une rampe d'écriture (L1) |
| 2 | Nombre exact de requêtes du `manager.save` d'un événement avec tags (chargement des ids de relations, UPDATE éventuel) | Demande une exécution, pas une lecture | Test d'intégration de `domain-event` avec un logger TypeORM |
| 3 | Que `primary.args` du chart Bitnami 15.5.30 soit transmis à l'image officielle `postgres` | Pas de `kustomize build --enable-helm` lancé | `kustomize build --enable-helm deploy/apps/overlays/prod/ms-post/db-postgres` |
| 4 | Cause exacte des 107 lignes `PROCESSING` du 2026-11-07 (pod tué pendant un lot, ou N3) | Journaux de l'époque non lus | Datadog, journaux des pods `outbox-*` du 2026-11-07 15:35 à 15:45 |
| 5 | Valeurs par défaut de `pg-pool` (`max` 10, `idleTimeoutMillis` 10 000) | Non relues dans le code de `pg-pool` | `npm pack pg-pool` à la version du `yarn.lock` |
| 6 | Allers-retours Bolt d'une session Neo4j (`session.run` et `executeWrite`) | Dépend du pipelining du pilote `neo4j-driver` | Lire la version du `yarn.lock` de ms-social et son code, ou mesurer |
| 7 | Allers-retours de `queue.add` BullMQ (script Lua, chargement initial) | Non relu | `bullmq` 5.81.5, `dist/cjs/classes/scripts.js` |
| 8 | Consommateurs de `comment.created` et effets d'un commentaire | Non tracé | `analyze_impact({ target: 'comment.created', depth: 2 })` |
| 9 | Écritures de ms-storage pour un post avec médias (`confirmPostAttachment`) | Volume faible (59 fichiers), non compté | Lire `domain-storage/src/repositories/postgres-file.repository.ts:276-420` |
| 10 | Persistance de `redis-master` (AOF, RDB) : un redémarrage perd-il les verrous d'idempotence ? | Configuration non lue | `kubectl -n prod exec redis-master-0 -- redis-cli CONFIG GET appendonly` (lecture seule ; demande le mot de passe, à lancer par le Lead Dev) |
| 11 | Durée maximale d'un traitement de post-processor (nécessaire pour la durée du verrou `processing` de L3) | Non mesurée | Spans `event *` et `batch *` dans Datadog |
| 12 | Ordre des événements supporté par chaque consommateur en cas de reprise (L4) | Non lu consommateur par consommateur | `analyze_impact` sur chaque type bloqué, puis lecture des handlers |
| 13 | Contrainte unique `(user_id, metric)` de `badge_progress` (L12) | Migration non lue | Migrations de `ms-user` |
| 14 | Pourquoi les UPDATE de `events` ne sont presque jamais HOT (2 sur 57 167) | Demande `pgstattuple` ou `pg_stat_statements` | Après L0 : quelles colonnes changent, quels index les couvrent |
| 15 | Sources des 5,3 millions d'UPDATE de `ranking_request` (lectures périmées, `fanout`, post-processors) | Compteur global seulement | Après L0 : `calls` de la requête d'upsert, croisés avec les spans des appelants |
| 16 | Health-check de `health-check-nest` : peut-il lire le DataSource de TypeORM au lieu du sien ? | Non lu en détail | `health-check-nest/src/health-check/health.controller.ts` |
| 17 | `job-outbox-failed.post-processor.ts` a-t-il le même COUNT que le succès ? | Non relu | `post-processors/src/common/job-outbox-failed.post-processor.ts` |
| 18 | Couverture de `mesh-mcp` : `analyze_impact` sur `post.created` ne liste pas `post-processor-storage` (chapitre 01, N12) | Anomalie d'outil, non analysée | Skill `volontariapp-mesh-mcp-verification` |
| 19 | Les numéros de ligne cités par `mesh-mcp` viennent des checkouts locaux, pas d'`origin/main` | Les checkouts sont sur d'autres branches | Toujours relire sur `origin/main` avant d'éditer |
