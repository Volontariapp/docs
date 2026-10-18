# 03 - Modèle de données (PostgreSQL de `ms-ranking`)

Une base PostgreSQL dédiée, isolée, comme tout microservice (`AGENTS.md` section 4). Elle contient les **trois tables standard de la plateforme** et **trois tables métier**.

## 1. Tables standard (déjà définies)

`jobs_outbox`, `job_audit` et `event_queue`, avec leurs triggers (`job_audit_status_trigger`), sont créées par les **migrations communes** (`src/migrations/common/`) synchronisées entre services par `sync-migrations.sh` (voir C3).

Précisions vérifiées sur `sync-migrations.sh` :

- Le tableau est `SERVICES=("user" "social" "post" "event")` (ligne 15) ; `ms-storage` n'y figure pas. Il faut ajouter `"ranking"`.
- Le script copie **tout** `ms-X/src/migrations` vers `npm-packages/packages/domain-X/src/test/migrations` et exige que `src/config/data-source.ts` du service référence ces migrations (comme `ms-social/src/config/data-source.ts`). `ms-ranking` doit donc avoir son propre `data-source.ts`.

Le trigger déduit le stream du champ `emitter` (`replace(NEW.emitter, 'ms-', '')`). **Tout job écrit dans cette base, quel que soit l'auteur (`ms-ranking`, `post-processor-ranking`, `worker-ranking`), doit porter `emitter = 'ms-ranking'`**, sinon le stream de retour est faux et le job n'est jamais nettoyé. Le champ `emitterId` (uuid) vaut le `userId` pour un calcul et l'`eventId` pour un fan-out.

Ni `post-processor-ranking` ni `worker-ranking` ne possèdent cette base : ils s'y connectent comme le font `post-processor-social` et `worker-social` (qui écrivent `event_queue` et `job_audit`), via `domain-ranking`.

## 2. Tables métier

Trois tables pour les événements (ci-dessous). Le feed de posts ajoute `ranking_post_score` et `ranking_like_log`, décrites en [11](11-feed-conception.md) section 3 ; `ranking_run` et `ranking_request` portent la dimension `list_kind` pour les deux listes.

### `ranking_score` : la liste d'un utilisateur

| Colonne | Type | Contrainte | Rôle |
| :--- | :--- | :--- | :--- |
| `user_id` | `uuid` | NOT NULL, partie de la PK | Utilisateur concerné. **Pas de clé étrangère** (propriété de `ms-user`). |
| `event_id` | `uuid` | NOT NULL, partie de la PK | Événement recommandé. Pas de clé étrangère (propriété de `ms-event`). |
| `score` | `numeric(5,4)` | NOT NULL, `CHECK (score BETWEEN 0 AND 1)` | Score final utilisé pour le tri. |
| `structural_score` | `numeric(5,4)` | NOT NULL, `CHECK (... BETWEEN 0 AND 1)` | Composante graphe, conservée pour le diagnostic. |
| `semantic_score` | `numeric(5,4)` | NULL, `CHECK (... BETWEEN 0 AND 1)` | Probabilité Jev, `NULL` si non évalué. |
| `rank` | `integer` | NOT NULL, `CHECK (rank >= 1)` | Position dans la liste (fige l'ordre, départage les égalités). |
| `reasons` | `varchar(30)[]` | NOT NULL, défaut `{}` | Codes d'explication (2 au plus), voir [13](13-decisions-v1.md) section 6 |
| `computed_at` | `timestamptz` | NOT NULL | Date du calcul qui a produit la ligne. |

- **Clé primaire** `(user_id, event_id)` ; **index** `(user_id, rank)`.
- Volume borné à `RANKING_LIST_SIZE` (100) lignes par utilisateur.

### `ranking_run` : une ligne par utilisateur et par type de liste (dernier calcul réussi)

Clé primaire `(user_id, list_kind)`. `list_kind` vaut `'EVENT'` ou `'POST'` (le feed de posts est décrit en [11](11-feed-conception.md)) ; la dimension est présente **dès la première migration**, pour que les deux listes aient chacune leur fraîcheur, leur coalescence, leur verrou et leur version de formule. Toutes les requêtes ci-dessous filtrent donc aussi sur `list_kind` ; le verrou consultatif utilise la clé `user_id || ':' || list_kind` pour ne pas sérialiser inutilement les deux calculs d'un même utilisateur.

| Colonne | Type | Rôle |
| :--- | :--- | :--- |
| `user_id` | `uuid` (partie de la PK) | Utilisateur. |
| `list_kind` | `varchar(10)` (partie de la PK) | `EVENT` ou `POST`. |
| `started_at` | `timestamptz` NOT NULL | **Début** du calcul qui a produit la liste. Sert à la coalescence et à l'anti-écrasement (voir [04](04-flux-asynchrone.md)). |
| `computed_at` | `timestamptz` NOT NULL | Fin du calcul (âge de la liste). |
| `source` | `varchar(20)` NOT NULL | `FULL`, `STRUCTURAL_ONLY` ou `COLD_START` (feed). |
| `formula_version` | `integer` NOT NULL | Version de la formule **du `list_kind` concerné** (`FORMULA_VERSION` pour les événements, `FEED_FORMULA_VERSION` pour les posts). Une version différente de la courante rend la liste périmée. |
| `reason` | `varchar(30)` NOT NULL | Cause du dernier calcul. |
| `candidate_count` | `integer` NOT NULL | Lignes écrites (sert de `totalCount`). |
| `jev_scored_count` | `integer` NOT NULL | Candidats évalués par Jev. |
| `jev_input_tokens`, `jev_output_tokens` | `integer` NULL | Consommation déclarée (`usage`). |
| `duration_ms` | `integer` NOT NULL | Durée totale. |
| `last_error` | `text` NULL | Dernière erreur Jev. **Tronquée à 200 caractères et passée au masque de `@volontariapp/logger`** : une erreur `422` nomme le champ fautif et peut citer du texte d'événement. |

### `ranking_request` : demande de calcul en attente (déduplication), clé `(user_id, list_kind)`

Résout le problème que `jobs_outbox` ne sait pas dédupliquer : `JobsOutboxEntity.createJob` génère un `randomUUID()` sans clé d'idempotence (`database/src/outbox/entities/jobs-outbox.entity.ts`), le `jobId` BullMQ vaut cet identifiant, et la ligne passe à `COMPLETED` dès le push (`outbox.consumer.ts`, `processItems`). Les statuts de `jobs_outbox` ne disent donc pas si une demande est en cours.

| Colonne | Type | Rôle |
| :--- | :--- | :--- |
| `user_id`, `list_kind` | `uuid`, `varchar(10)` PK | Une seule demande ouverte par utilisateur et par type de liste. |
| `requested_at` | `timestamptz` NOT NULL | Date de la demande la plus récente, posée par l'horloge de la **base** (`clock_timestamp()` de `ms-ranking`). C'est cette valeur, retournée par l'`INSERT` et transmise comme texte (microsecondes conservées), qui devient `requestedAt` du job. Elle se compare à `started_at` **en SQL**, jamais en JavaScript (qui tronque à la milliseconde) : comparer les horloges de deux hôtes exposerait à un décalage. |
| `reason` | `varchar(30)` NOT NULL | Cause de la demande la plus récente. |
| `job_enqueued_at` | `timestamptz` NOT NULL | Dernière écriture effective d'un job pour cette demande. |

Règle d'écriture d'une demande (lecture ou post-processor), **dans la même transaction que l'écriture du job** :

```sql
WITH t AS (SELECT clock_timestamp() AS ts)
INSERT INTO ranking_request AS r (user_id, list_kind, requested_at, reason, job_enqueued_at)
SELECT $1, $4, t.ts, $2, t.ts FROM t
ON CONFLICT (user_id, list_kind) DO UPDATE
  SET requested_at = EXCLUDED.requested_at,
      reason = EXCLUDED.reason,
      job_enqueued_at = CASE
        WHEN $5::boolean
          OR r.job_enqueued_at <= EXCLUDED.requested_at - make_interval(secs => $3::double precision)
        THEN EXCLUDED.requested_at     -- nouveau job requis (forcé, ou job probablement perdu)
        ELSE r.job_enqueued_at         -- un job récent existe déjà
      END
RETURNING requested_at, (job_enqueued_at = requested_at) AS needs_job;
```

Paramètres : `$1` utilisateur, `$2` cause, `$3` délai `RANKING_REQUEST_TTL_SECONDS` (120), `$4` `list_kind`, `$5` demande forcée (`true` pour `ON_DEMAND` et `MANUAL`).

Interprétation : la ligne est **toujours** mise à jour (`requested_at` avance) ; `needs_job` vaut `true` quand un job doit être écrit (première demande, demande forcée, ou job écrit depuis plus de `RANKING_REQUEST_TTL_SECONDS`, donc probablement perdu : [06](06-lecture-et-206.md) section 3) et `false` quand un job récent existe déjà (la demande est alors fusionnée, sans nouveau job). Le worker supprime la ligne en fin de calcul **seulement si `requested_at <= started_at`**. Si la ligne survit (une demande est arrivée pendant le calcul), il écrit **dans la même transaction** un job de suite (`scheduled_at = now + 30 s`) et rafraîchit `job_enqueued_at` : sans cela, la demande resterait sans job. Tests obligatoires : (1) demande après `started_at` => second calcul ; (2) demande pendant la fenêtre de débounce => un seul job ; (3) job périmé => nouveau job.

## 2 bis. Tables ajoutées par les décisions du 2026-10-18

| Table | Colonnes | Rôle |
| :--- | :--- | :--- |
| `ranking_user_location` | `user_id` uuid PK, `location_enc` bytea NOT NULL, `updated_at` timestamptz | position arrondie à 1 km et chiffrée au repos ; purgée avec le compte |
| `ranking_event_feedback` | `user_id`, `event_id` (PK), `action` varchar(10) (`PASS`), `created_at` ; index `(event_id, action)` et `(user_id, created_at DESC)` | swipes à gauche ; exclusion pendant `RANKING_PASS_COOLDOWN_DAYS` et entrée de la popularité ; rétention 90 jours |
| `ranking_event_wish` | `user_id`, `event_id` (PK), `created_at` ; index `(event_id)` | souhaits actifs, alimentés par `EVENT_SOCIAL_WISHED` (insert `ON CONFLICT DO NOTHING`) et `EVENT_SOCIAL_UNWISHED` (delete) ; un comptage par lignes reste idempotent en cas de rejeu |
| `ranking_event_mention` | `post_id` PK, `event_id`, `author_id`, `created_at` ; index `(event_id, created_at)` | posts liés à un événement, alimentés par `POST_CREATED` et purgés par `POST_DELETED` ; on compte les auteurs distincts |
| `ranking_rate_bucket` | `user_id`, `bucket` (PK), `tokens` numeric(6,3), `updated_at` | seaux à jetons : `REFRESH` (5 par minute, partagé événements et posts) et `LOCATION` (1 par minute) ; requête et tests dans [13](13-decisions-v1.md) section 3 bis |

Pas de clé étrangère (les identifiants appartiennent à d'autres services). Le jeu de données démarre vide au déploiement : les souhaits et mentions antérieurs ne sont pas rétro-alimentés (aucune RPC de comptage), la popularité s'appuie d'abord sur le taux de remplissage fourni par `ms-event`.


## 3. Requêtes de référence

### Lecture (chemin chaud)

```sql
SELECT event_id, score, structural_score, semantic_score
FROM ranking_score WHERE user_id = $1
ORDER BY rank LIMIT $2 OFFSET $3;

SELECT computed_at, source, formula_version, candidate_count
FROM ranking_run WHERE user_id = $1 AND list_kind = 'EVENT';
```

(La lecture du feed de posts utilise `ranking_post_score` et `list_kind = 'POST'`, voir [11](11-feed-conception.md).)

### Remplacement atomique (chemin d'écriture, **transaction courte**)

Le calcul (appels `ms-social`, `ms-event`, Jev) se fait **avant** et **hors** transaction. Seule l'écriture est transactionnelle :

```sql
BEGIN;
SELECT pg_advisory_xact_lock(hashtextextended($1::text || ':' || $5, 0));    -- $5 = list_kind

-- anti-ecrasement : refuser si une liste calculee a partir d'un etat plus recent existe deja
SELECT started_at FROM ranking_run WHERE user_id = $1 AND list_kind = $5;   -- si started_at >= $started_at du calcul : ROLLBACK, fin

DELETE FROM ranking_score WHERE user_id = $1;
INSERT INTO ranking_score (...) VALUES (...), ...;           -- insertion groupee, 100 lignes max
INSERT INTO ranking_run (...) VALUES (...)
  ON CONFLICT (user_id, list_kind) DO UPDATE SET ... ;

DELETE FROM ranking_request
 WHERE user_id = $1 AND list_kind = $5 AND requested_at <= $started_at;   -- une demande plus recente survit

-- retention opportuniste (aucun planificateur n'existe) : voir 11 pour le journal de likes
COMMIT;
```

Propriétés :

- Sous `READ COMMITTED`, un lecteur voit l'ancienne liste complète ou la nouvelle complète, jamais un mélange.
- Le verrou consultatif de transaction n'est tenu que pendant l'écriture (quelques millisecondes), jamais pendant un appel réseau.
- **Anti-écrasement** : un calcul lent, démarré avant un calcul plus récent déjà écrit, abandonne au lieu d'écraser une liste plus fraîche.
- Si le calcul échoue avant le `COMMIT`, l'ancienne liste reste en place.

### Fan-out : utilisateurs actifs (pagination par curseur)

```sql
SELECT user_id, computed_at
FROM ranking_run
WHERE list_kind = $5                              -- sans ce filtre : 2 lignes par utilisateur
  AND computed_at > now() - make_interval(days => $1)
  AND (computed_at, user_id) < ($2, $3)           -- curseur
ORDER BY computed_at DESC, user_id DESC
LIMIT $4;
```

Index : `ranking_run (list_kind, computed_at DESC, user_id DESC)`. La pagination par `OFFSET` est évitée (coûteuse sur plusieurs milliers de lignes).

## 4. Migrations

Emplacement : `src/migrations/` du microservice, copiées par `sync-migrations.sh` vers `domain-ranking/src/test/migrations/{common,domain}/`.

1. Migrations communes.
2. `CreateRankingTables<timestamp>` : trois tables, contraintes et index. Réversible (`down()` supprime index puis tables). Aucune donnée de seed.

## 5. Rétention et suppression de compte

| Donnée | Politique |
| :--- | :--- |
| `ranking_score` d'un utilisateur actif | Remplacée à chaque calcul, jamais plus de `RANKING_LIST_SIZE` lignes. |
| IDs d'événements supprimés ou terminés | Restent jusqu'au prochain calcul. Sans effet visible (la gateway les écarte). |
| Utilisateur inactif | Aucune purge nécessaire pour la démonstration. Option : job de purge des `ranking_run` de plus de 90 jours. |
| Suppression d'un compte | Purge par le stream `user:deleted:ranking` (voir ci-dessous). |

> [!WARNING]
> **La suppression de compte émet désormais `user.deleted` (corrigé le 2026-10-18).** `ms-ranking` doit : (1) obtenir son stream `Streams.USER_DELETED_RANKING = 'user:deleted:ranking'` dans `shared` ; (2) être ajouté aux `targetServices` de `requestDeletionWithUserDeleted` (`domain-user`, modification amont soumise au STOP, à regrouper avec l'étape 2 de [09](09-plan-de-livraison.md)) ; (3) héberger un post-processor de purge (modèle : `post-processor-storage/src/post-processors/user-deleted.post-processor.ts`) qui supprime les lignes du compte dans toutes les tables `ranking_*` (liste canonique : [13](13-decisions-v1.md) section 7, étape 4) ; (4) participer au gather de `ws-service` : le domaine doit acquitter par un événement `USER_RANKING_DELETED` (ou `USER_RANKING_DELETION_FAILED`) vers `ws:user-deleted-feedback`, et `ws-service` doit l'attendre ; le protocole détaillé, l'ordre de déploiement et le risque d'échec au bout de 60 s sont en [13](13-decisions-v1.md) section 7. Les listes des **autres** utilisateurs qui contiennent des éléments du compte supprimé se corrigent d'elles-mêmes : la gateway n'affiche que ce que `ms-event` et `ms-post` renvoient, et le rafraîchissement périodique les recalcule.

## 6. Ce que ce modèle évite par rapport à un cache

- Aucun contenu d'événement stocké : aucune question de cohérence de contenu.
- Rien n'est perdu au redémarrage d'un cache.
- Pas de reconstruction massive après incident.
- « Pourquoi cet ordre ? » se répond en SQL sur `structural_score` et `semantic_score`.
