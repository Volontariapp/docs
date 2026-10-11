# 03 - Modèle de données (PostgreSQL de `ms-affinity`)

Une base PostgreSQL dédiée, isolée, comme tout microservice (`AGENTS.md` section 4). Elle contient les **trois tables standard de la plateforme** et **trois tables métier**.

## 1. Tables standard (déjà définies)

`jobs_outbox`, `job_audit` et `event_queue`, avec leurs triggers (`job_audit_status_trigger`), sont créées par les **migrations communes** (`src/migrations/common/`) synchronisées entre services par `sync-migrations.sh` (voir C3).

Précisions vérifiées sur `sync-migrations.sh` :

- Le tableau est `SERVICES=("user" "social" "post" "event")` (ligne 14) ; `ms-storage` n'y figure pas. Il faut ajouter `"affinity"`.
- Le script copie **tout** `ms-X/src/migrations` vers `npm-packages/packages/domain-X/src/test/migrations` et exige que `src/config/data-source.ts` du service référence ces migrations (comme `ms-social/src/config/data-source.ts`). `ms-affinity` doit donc avoir son propre `data-source.ts`.

Le trigger déduit le stream du champ `emitter` (`replace(NEW.emitter, 'ms-', '')`). **Tout job écrit dans cette base, quel que soit l'auteur (`ms-affinity`, `post-processor-affinity`, `worker-affinity`), doit porter `emitter = 'ms-affinity'`**, sinon le stream de retour est faux et le job n'est jamais nettoyé. Le champ `emitterId` (uuid) vaut le `userId` pour un calcul et l'`eventId` pour un fan-out.

Ni `post-processor-affinity` ni `worker-affinity` ne possèdent cette base : ils s'y connectent comme le font `post-processor-social` et `worker-social` (qui écrivent `event_queue` et `job_audit`), via `domain-affinity`.

## 2. Tables métier

Trois tables pour les événements (ci-dessous). Le feed de posts ajoute `affinity_post_score` et `affinity_like_log`, décrites en [11](11-feed-conception.md) section 3 ; `affinity_run` et `affinity_request` portent la dimension `list_kind` pour les deux listes.

### `affinity_score` : la liste d'un utilisateur

| Colonne | Type | Contrainte | Rôle |
| :--- | :--- | :--- | :--- |
| `user_id` | `uuid` | NOT NULL, partie de la PK | Utilisateur concerné. **Pas de clé étrangère** (propriété de `ms-user`). |
| `event_id` | `uuid` | NOT NULL, partie de la PK | Événement recommandé. Pas de clé étrangère (propriété de `ms-event`). |
| `score` | `numeric(5,4)` | NOT NULL, `CHECK (score BETWEEN 0 AND 1)` | Score final utilisé pour le tri. |
| `structural_score` | `numeric(5,4)` | NOT NULL, `CHECK (... BETWEEN 0 AND 1)` | Composante graphe, conservée pour le diagnostic. |
| `semantic_score` | `numeric(5,4)` | NULL, `CHECK (... BETWEEN 0 AND 1)` | Probabilité Jev, `NULL` si non évalué. |
| `rank` | `integer` | NOT NULL, `CHECK (rank >= 1)` | Position dans la liste (fige l'ordre, départage les égalités). |
| `computed_at` | `timestamptz` | NOT NULL | Date du calcul qui a produit la ligne. |

- **Clé primaire** `(user_id, event_id)` ; **index** `(user_id, rank)`.
- Volume borné à `AFFINITY_LIST_SIZE` (100) lignes par utilisateur.

### `affinity_run` : une ligne par utilisateur et par type de liste (dernier calcul réussi)

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

### `affinity_request` : demande de calcul en attente (déduplication), clé `(user_id, list_kind)`

Résout le problème que `jobs_outbox` ne sait pas dédupliquer : `JobsOutboxEntity.createJob` génère un `randomUUID()` sans clé d'idempotence (`database/src/outbox/entities/jobs-outbox.entity.ts`), le `jobId` BullMQ vaut cet identifiant, et la ligne passe à `COMPLETED` dès le push (`outbox.consumer.ts`, `processItems`). Les statuts de `jobs_outbox` ne disent donc pas si une demande est en cours.

| Colonne | Type | Rôle |
| :--- | :--- | :--- |
| `user_id`, `list_kind` | `uuid`, `varchar(10)` PK | Une seule demande ouverte par utilisateur et par type de liste. |
| `requested_at` | `timestamptz` NOT NULL | Date de la demande la plus récente, **posée par l'horloge de la base** (`now()` de `ms-affinity`). C'est cette valeur, retournée par l'`INSERT`, qui est copiée dans `requestedAt` du job : comparer `requestedAt` (horloge d'un post-processor) à `started_at` (horloge d'un worker) exposerait à un décalage entre hôtes. |
| `reason` | `varchar(30)` NOT NULL | Cause de la demande la plus récente. |
| `job_enqueued_at` | `timestamptz` NOT NULL | Dernière écriture effective d'un job pour cette demande. |

Règle d'écriture d'une demande (lecture ou post-processor), **dans la même transaction que l'écriture du job** :

```sql
INSERT INTO affinity_request (user_id, list_kind, requested_at, reason, job_enqueued_at)
VALUES ($1, $4, now(), $2, now())
ON CONFLICT (user_id, list_kind) DO UPDATE
  SET requested_at = now(), reason = EXCLUDED.reason
  WHERE affinity_request.job_enqueued_at > now() - make_interval(secs => $3)   -- job encore "frais"
RETURNING requested_at, (xmax = 0) AS inserted;
```

Interprétation : si une demande ouverte a un job écrit récemment (moins de `AFFINITY_REQUEST_TTL_SECONDS`, 120 s), on **met à jour `requested_at`** sans écrire de nouveau job ; sinon (demande absente, ou job probablement perdu, voir [06](06-lecture-et-206.md) section 6) on écrit un nouveau job et on rafraîchit `job_enqueued_at`. La ligne est supprimée par le worker dans la transaction d'écriture de la liste, si aucune demande plus récente n'est arrivée entre-temps.

## 3. Requêtes de référence

### Lecture (chemin chaud)

```sql
SELECT event_id, score, structural_score, semantic_score
FROM affinity_score WHERE user_id = $1
ORDER BY rank LIMIT $2 OFFSET $3;

SELECT computed_at, source, formula_version, candidate_count
FROM affinity_run WHERE user_id = $1 AND list_kind = 'EVENT';
```

(La lecture du feed de posts utilise `affinity_post_score` et `list_kind = 'POST'`, voir [11](11-feed-conception.md).)

### Remplacement atomique (chemin d'écriture, **transaction courte**)

Le calcul (appels `ms-social`, `ms-event`, Jev) se fait **avant** et **hors** transaction. Seule l'écriture est transactionnelle :

```sql
BEGIN;
SELECT pg_advisory_xact_lock(hashtextextended($1::text || ':' || $5, 0));    -- $5 = list_kind

-- anti-ecrasement : refuser si une liste calculee a partir d'un etat plus recent existe deja
SELECT started_at FROM affinity_run WHERE user_id = $1 AND list_kind = $5;   -- si started_at >= $started_at du calcul : ROLLBACK, fin

DELETE FROM affinity_score WHERE user_id = $1;
INSERT INTO affinity_score (...) VALUES (...), ...;           -- insertion groupee, 100 lignes max
INSERT INTO affinity_run (...) VALUES (...)
  ON CONFLICT (user_id, list_kind) DO UPDATE SET ... ;

DELETE FROM affinity_request
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
FROM affinity_run
WHERE list_kind = $5                              -- sans ce filtre : 2 lignes par utilisateur
  AND computed_at > now() - make_interval(days => $1)
  AND (computed_at, user_id) < ($2, $3)           -- curseur
ORDER BY computed_at DESC, user_id DESC
LIMIT $4;
```

Index : `affinity_run (list_kind, computed_at DESC, user_id DESC)`. La pagination par `OFFSET` est évitée (coûteuse sur plusieurs milliers de lignes).

## 4. Migrations

Emplacement : `src/migrations/` du microservice, copiées par `sync-migrations.sh` vers `domain-affinity/src/test/migrations/{common,domain}/`.

1. Migrations communes.
2. `CreateAffinityTables<timestamp>` : trois tables, contraintes et index. Réversible (`down()` supprime index puis tables). Aucune donnée de seed.

## 5. Rétention et suppression de compte

| Donnée | Politique |
| :--- | :--- |
| `affinity_score` d'un utilisateur actif | Remplacée à chaque calcul, jamais plus de `AFFINITY_LIST_SIZE` lignes. |
| IDs d'événements supprimés ou terminés | Restent jusqu'au prochain calcul. Sans effet visible (la gateway les écarte). |
| Utilisateur inactif | Aucune purge nécessaire pour la démonstration. Option : job de purge des `affinity_run` de plus de 90 jours. |
| Suppression d'un compte | **Non couverte en V1** (voir ci-dessous). |

> [!WARNING]
> **La suppression de compte n'émet aucun événement aujourd'hui.** `analyze_impact` ne trouve aucun producteur de `user:deleted` ; `UserService.delete` (`domain-user/src/services/user.service.ts:135-139`) appelle seulement `userRepository.delete` ; le trigger SQL des utilisateurs ne gère que `INSERT` (`domain-user/src/database/triggers/index.ts`). Un `PurgeUserAffinityHandler` branché sur `user:deleted` **ne se déclencherait donc jamais**. Deux options : ajouter un trigger `AFTER DELETE` ou une émission d'événement dans `domain-user` (3e modification amont soumise au STOP, voir [09](09-plan-de-livraison.md)), ou ne pas présenter la purge comme acquise. Dans les deux cas il faut décider du sort des listes **d'autres utilisateurs** qui contiennent des événements créés par le compte supprimé (ils disparaissent à la lecture car `ms-event` ne les renvoie plus, ou après suppression de ses événements). En attendant, ces données restent en base : à documenter comme limite connue.

## 6. Ce que ce modèle évite par rapport à un cache

- Aucun contenu d'événement stocké : aucune question de cohérence de contenu.
- Rien n'est perdu au redémarrage d'un cache.
- Pas de reconstruction massive après incident.
- « Pourquoi cet ordre ? » se répond en SQL sur `structural_score` et `semantic_score`.
