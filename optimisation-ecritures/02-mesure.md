# 02 - Mesure

## 1. Ce qui a été mesuré le 2026-11-10 (lecture seule)

Méthode : `kubectl -n prod exec -i <base>-db-postgresql-0 -- sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" -X -f -'`, chaque script commençant par `SET default_transaction_read_only = on;`. Aucune écriture, aucune extension créée, aucun redémarrage. Les compteurs `pg_stat_*` n'ont jamais été remis à zéro (`stats_reset` vide) : ils couvrent la vie de chaque base.

### Réglages Postgres (identiques dans les sept bases)

| Réglage | Valeur | Source |
| :--- | :--- | :--- |
| Version | 16.14 (Alpine) ; ms-event 16.4 (Debian, image PostGIS) | `version()` |
| `max_connections` | 100 | fichier de configuration |
| `shared_buffers` | 128 Mo (16384 × 8 ko) | fichier de configuration |
| `synchronous_commit` | `on` | défaut |
| `shared_preload_libraries` | vide | défaut |
| `wal_buffers`, `commit_delay`, `wal_compression` | 4 Mo, 0, `off` | défaut |
| `track_io_timing` | `off` | défaut |
| `statement_timeout`, `idle_in_transaction_session_timeout` | 0 (aucun) | défaut |
| `pg_stat_statements` | disponible (1.10), **non installé**, et non chargeable sans `shared_preload_libraries` | `pg_available_extensions` |
| Ressources du pod | limite 1,5 CPU et 512 Mi, demande 100m et 128 Mi | `kubectl get sts ms-post-db-postgresql` |

Les bases sont déployées par le chart Bitnami `postgresql` 15.5.30 via Kustomize (`deploy/apps/overlays/prod/<service>/db-postgres/kustomization.yaml`), **avec l'image officielle `postgres:16-alpine`** à la place de l'image Bitnami. Les variables Bitnami (`POSTGRESQL_SHARED_PRELOAD_LIBRARIES` est présente dans le pod) ne sont pas lues par l'image officielle : c'est pourquoi le réglage est vide. INFERENCE : un réglage posé par les valeurs Bitnami (`primary.extendedConfiguration`, `shared_preload_libraries`) resterait sans effet ; il faut passer par les arguments de `postgres` (voir 2).

### Connexions au repos

Une seule connexion applicative par base (celle du runner d'outbox, adresse IP du pod `outbox-*`), plus Datadog. Les pools des `ms-*`, workers et post-processors ferment leurs connexions inactives (INFERENCE : `idleTimeoutMillis` de `pg`, 10 s par défaut, non relu). Le runner d'outbox garde la sienne parce qu'il interroge au moins toutes les 5 s.

### Tables les plus écrites

| Base | Table | INSERT | UPDATE | dont HOT | DELETE |
| :--- | :--- | ---: | ---: | ---: | ---: |
| ms-ranking | `ranking_request` | 67 435 | 5 340 627 | 4 052 046 | 66 078 |
| ms-ranking | `ranking_score` | 3 173 853 | 0 | 0 | 3 029 963 |
| ms-ranking | `jobs_outbox` | 249 980 | 497 238 | 229 041 | 248 477 |
| ms-ranking | `event_queue` | 248 705 | 497 408 | 254 791 | 248 557 |
| ms-ranking | `job_audit` | 248 619 | 248 810 | 0 | 248 465 |
| ms-social | `event_queue` | 150 734 | 301 442 | 245 245 | 150 699 |
| ms-event | `event_queue` | 102 070 | 204 121 | 137 661 | 102 042 |
| ms-event | `events` | 15 333 | 57 167 | 2 | 0 |
| ms-user | `event_queue` | 51 984 | 103 920 | 70 952 | 51 931 |
| ms-user | `users` | 1 800 | 50 512 | 50 253 | 0 |
| ws-service | `event_queue` | 44 300 | 88 600 | 72 468 | 44 300 |
| ws-service | `gather_state` | 44 300 | 59 625 | 59 255 | 44 300 |
| ms-post | `event_queue` | 30 731 | 61 455 | 52 256 | 30 716 |
| ms-post | `posts` | 28 988 | 0 | 0 | 2 |

Lecture (FAIT) : dans toutes les bases, `event_queue` a **2,0 UPDATE par INSERT**, exactement le claim puis le passage en `COMPLETED`. Les UPDATE de `events` ne sont presque jamais HOT (2 sur 57 167) : INFERENCE, une colonne indexée change à chaque fois (`updated_at` ou la recherche), ou la page est pleine ; à regarder avec `pg_stat_statements` et `pgstattuple` (non installé).

### Délai de l'outbox

Sur les lignes `event_queue` `COMPLETED` encore présentes (la purge efface les plus anciennes), écart `updated_at - created_at` :

| Base | Lignes (24 h) | p50 | p95 | p99 |
| :--- | ---: | ---: | ---: | ---: |
| ms-ranking | 142 | 0,44 s | 1,63 s | 3,11 s |
| autres bases | 0 ligne `COMPLETED` restante | | | |

### Lignes bloquées

| Base | Statut | Type | Lignes | Plus ancienne | Plus récente |
| :--- | :--- | :--- | ---: | :--- | :--- |
| ms-post | FAILED | `post.created` | 8 | 2026-11-07 15:36:51 | 15:38:22 |
| ms-post | PROCESSING | `post.created` | 7 | 15:37:02 | 15:38:30 |
| ms-event | FAILED | `event.changed`, `event.created`, `event.finished` | 9 | 15:36:59 | 15:37:14 |
| ms-event | PROCESSING | idem | 19 | 15:37:14 | 15:38:30 |
| ms-social | FAILED | `post.liked` | 9 | 15:36:40 | 15:37:04 |
| ms-social | PROCESSING | `post.liked` | 26 | 15:37:04 | 15:38:03 |
| ms-user | FAILED | `user.created` | 5 | 15:39:23 | 15:39:24 |
| ms-user | PROCESSING | `user.created` | 48 | 15:39:24 | 15:39:36 |
| ms-ranking | FAILED | `ranking:job:outbox:success` | 4 | 15:36:30 | 15:36:30 |
| ms-ranking | PROCESSING | idem | 2 | 15:36:32 | 15:36:32 |

`attempts` vaut 1 sur toutes les `FAILED` et 0 sur toutes les `PROCESSING`. ms-storage, ws-service : aucune ligne bloquée. `jobs_outbox` : aucune ligne bloquée.

Requête utilisée (à rejouer avant L4) :

```sql
SET default_transaction_read_only = on;
SELECT status, type, count(*), min(created_at), max(created_at), max(attempts)
FROM event_queue WHERE status IN ('PROCESSING','FAILED','PENDING') GROUP BY 1, 2 ORDER BY 1, 3 DESC;
```

## 2. Activer `pg_stat_statements` (L0)

**État au 2026-11-10** : PR Volontariapp/deploy#77 ouverte en brouillon, **à ne pas fusionner sans décision de Victor** (chaque base redémarre). Vérifié avant de l'ouvrir :

- le chart 15.5.30 lit `primary.args` (`templates/primary/statefulset.yaml:199-200`) et `kustomize build --enable-helm` le rend dans le conteneur `postgresql` des sept overlays (FAIT) ;
- le StatefulSet en prod n'a ni `command` ni `args` (FAIT, `kubectl get sts ms-post-db-postgresql -o jsonpath`) : `args` remplace le `CMD` de l'image, et `docker-entrypoint.sh` ajoute `postgres` devant un premier argument qui commence par `-` ;
- en local, `postgres:16-alpine` et `postgis/postgis:16-3.4` démarrent avec ces arguments, `CREATE EXTENSION pg_stat_statements` réussit et `track_io_timing` vaut `on` (FAIT) ;
- l'utilisateur applicatif `ms-post` est superutilisateur (FAIT, lecture de `pg_roles`) ; `pg_stat_statements` n'est pas une extension « trusted », il faut ce droit pour la créer.

### Procédure du `CREATE EXTENSION` (Victor, après la synchronisation de deploy#77)

Une base à la fois, hors rampe. Pour chaque `<svc>` parmi `ms-post ms-event ms-social ms-user ms-storage ms-ranking ws-service` :

```bash
# 1. attendre le redémarrage de la base et vérifier que la bibliothèque est chargée
kubectl -n prod rollout status sts/<svc>-db-postgresql --timeout=180s
kubectl -n prod exec -i <svc>-db-postgresql-0 -- sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" -X -tA \
   -c "SHOW shared_preload_libraries" -c "SHOW track_io_timing"'
# attendu : pg_stat_statements, puis on

# 2. créer l'extension (écriture, une fois par base)
kubectl -n prod exec -i <svc>-db-postgresql-0 -- sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" -X -v ON_ERROR_STOP=1 \
   -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements"'

# 3. contrôle (lecture seule)
kubectl -n prod exec -i <svc>-db-postgresql-0 -- sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" -X -tA \
   -c "SET default_transaction_read_only = on" -c "SELECT count(*) FROM pg_stat_statements"'

# 4. vérifier que les pods du service ont repris leurs connexions
#    (outbox-<suffixe> : outbox-post, outbox-event, outbox-social, outbox-user, outbox-storage,
#     outbox-ranking, outbox-ws)
kubectl -n prod get pods | grep -E '<suffixe>' ; kubectl -n prod logs deploy/outbox-<suffixe> --since=5m | tail -20
```

L'extension n'existe que dans la base où elle est créée : `$POSTGRES_DATABASE` est la base applicative, c'est là que tournent les requêtes à mesurer. Retour arrière : `DROP EXTENSION pg_stat_statements;` puis retirer les arguments (nouveau redémarrage).

Procédure d'origine, gardée pour les raisons des choix :

1. Dans chaque `deploy/apps/overlays/prod/<service>/db-postgres/kustomization.yaml`, ajouter aux `valuesInline.primary` les arguments du conteneur, puisque l'image officielle lit `-c` :

   ```yaml
   primary:
     args:
       - "-c"
       - "shared_preload_libraries=pg_stat_statements"
       - "-c"
       - "pg_stat_statements.track=top"
       - "-c"
       - "pg_stat_statements.max=5000"
       - "-c"
       - "track_io_timing=on"
   ```

   NON VERIFIE : que le chart 15.5.30 expose `primary.args` et les passe tels quels à l'image officielle. Vérifier avant de pousser avec `kustomize build --enable-helm deploy/apps/overlays/prod/ms-post/db-postgres | grep -A12 'args:'`. Si le chart impose sa propre commande Bitnami, passer par `primary.command` (`["docker-entrypoint.sh", "postgres", "-c", ...]`).
2. Mémoire : `pg_stat_statements.max=5000` coûte de l'ordre de quelques Mo de mémoire partagée (INFERENCE) ; la limite de 512 Mi suffit, mais la VM manque de mémoire (dossier `montee-en-charge`, chapitre 07) : déployer une base à la fois.
3. Redémarrage : ArgoCD recrée le pod de la base ; l'application perd sa connexion quelques secondes. Le faire hors rampe.
4. Dans chaque base, une fois : `CREATE EXTENSION IF NOT EXISTS pg_stat_statements;` (lancé par le Lead Dev, ou par une migration `common` si l'équipe préfère la tracer ; dans ce cas, suivre `volontariapp-db-migration`).
5. Datadog : l'annotation `ad.datadoghq.com/postgresql.instances` existe déjà ; ajouter `"dbm": true` permet d'avoir les requêtes dans Datadog (Database Monitoring), NON VERIFIE sur l'offre Datadog du projet.

## 3. Compteurs à suivre

| Question | Requête ou métrique |
| :--- | :--- |
| Requêtes SQL par écriture | `pg_stat_statements` : `calls` des requêtes d'une opération, divisé par le nombre d'opérations faites par la rampe ; remise à zéro avant chaque palier avec `SELECT pg_stat_statements_reset();` (écriture : à faire par le Lead Dev ou dans la fenêtre de rampe) |
| Transactions par seconde | `pg_stat_database.xact_commit` relevé avant et après un palier |
| Lignes réécrites | `pg_stat_user_tables` : `n_tup_upd / n_tup_ins` d'`event_queue` (2,0 aujourd'hui, doit rester 2,0 après L5 ; le nombre de transactions, lui, doit baisser) |
| Délai de l'outbox | percentiles de `updated_at - created_at` sur `event_queue` `COMPLETED` (requête de la section 1), avant la purge |
| Lignes bloquées | `count(*)` de `PROCESSING` plus vieilles que 5 min et de `FAILED`, par base ; à mettre en monitor Datadog (requête personnalisée du check postgres) |
| Allers-retours Redis | `INFO commandstats` sur `redis-master` (`cmdstat_set`, `cmdstat_xadd`, `cmdstat_xack`), avant et après |
| Neo4j | `CALL dbms.listTransactions()` ou les métriques Bolt du conteneur ; NON VERIFIE ce qui est exposé |

## 4. Les routes d'écriture que la rampe doit tester (L1)

La rampe actuelle ne fait que des lectures (`traffic-simulator/README.md`, section « Rampe de charge (lecture seule) »). Elle est en refonte (lots L1 à L8, mode `app`, pool de comptes `load.NNNN`) : ce dossier décrit le besoin, pas le code.

| Route | Poids proposé dans un mélange « écriture » | Pourquoi | Effets en aval à surveiller |
| :--- | ---: | :--- | :--- |
| `POST /social/likes/:postId` puis `DELETE /social/likes/:postId` | 30 | L'écriture la plus fréquente d'une app sociale ; Neo4j + outbox | `post.liked` vers ranking, badges, ws-service |
| `POST /posts/:postId/comments` | 15 | Transaction ms-post + outbox | `comment.created` (NON VERIFIE : consommateurs) |
| `POST /social/events/:eventId/participate` puis `DELETE` | 15 | 4 à 5 sessions Neo4j | aucun événement émis |
| `POST /social/events/:eventId/wish` puis `DELETE` | 10 | Neo4j + outbox | `event.social.wished` vers badges et ranking |
| `POST /social/follow/:followedId` puis `DELETE` | 10 | Neo4j seul | |
| `POST /posts` (sans média) | 10 | Création avec relecture | `post.created` vers ranking, social, storage, ws-service |
| `POST /events` (avec 2 tags) | 5 | Le chemin le plus coûteux (save, triggers `event_tags`) | `event.created`, géocodage, `event.tag_linked` |
| `PATCH /events/:id` | 5 | `update()` du socle et trigger `event.changed` | `event.changed` |

Exigences :

- Chaque écriture a son inverse dans la même session de l'acteur (like puis unlike), pour que la rampe laisse la base dans l'état où elle l'a trouvée, à la purge de l'outbox près.
- Les acteurs écrivent sur des objets créés pour la rampe (posts et événements de comptes `load.NNNN`), jamais sur ceux des vrais utilisateurs. Les notifications push et WebSocket vers de vrais comptes doivent être impossibles (un acteur `load.*` ne like que des posts `load.*`).
- `POST /events` déclenche le géocodage (OpenStreetMap) : le désactiver (`GEOCODING_ENABLED=false`) ou limiter ce poids, pour ne pas solliciter un service tiers.
- Le rapport donne, en plus du p95 HTTP, le délai bout en bout d'au moins un flux : écrire un like et attendre son effet (`post.liked` reçu par ws-service, ou le compteur visible en lecture), pour mesurer l'outbox sous charge.
- Mélange lecture et écriture réglable (`LOAD_MIX`), par exemple 90 % lecture et 10 % écriture, proche de l'usage.
- La rampe « lecture seule » écrit déjà (N6 : `ranking_request`) ; la noter dans le rapport.
