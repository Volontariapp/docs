# 07 - L11 : l'écriture à la lecture de ms-ranking, options à trancher

Chapitre écrit le 2026-11-10. **Rien n'est implémenté** : L11 demande une décision métier (consigne de l'orchestrateur). Ce chapitre donne le fonctionnement actuel, les options et une recommandation. Code lu sur `origin/main` le 2026-11-10.

## 1. Ce qui se passe aujourd'hui (FAIT)

- Une lecture de liste sans liste (`ranking-read.service.ts:46-48`) demande un calcul `ON_DEMAND` ; une lecture d'une liste périmée (`refreshWhenStale`, `:120-133`) demande un calcul `STALE_REFRESH`, et sert l'ancienne liste.
- `RankingJobService.requestCompute` (`ranking-job.service.ts:31-72`) ouvre une transaction, fait l'upsert de `ranking_request`, et écrit un job dans `jobs_outbox` si `needs_job`.
- L'upsert (`domain-ranking/src/repositories/postgres-ranking-request.repository.ts:35-60`) **réécrit `requested_at` et `reason` à chaque appel**, même quand un job est déjà en route ; il ne repose `job_enqueued_at` (donc un nouveau job) que si `force` ou si le dernier job a plus de `ttlSeconds`.
- À la fin d'un calcul, `completeRequestSql` (`request-sql.ts:13-28`) supprime la demande si `requested_at <= startedAt`, sinon la garde et un job de suivi est écrit (`markFollowUpSql`). Donc **chaque lecture périmée pendant un calcul en cours déclenche un calcul de suivi**.
- Mesure : `ranking_request` a 67 435 insertions et 5 340 627 mises à jour (chapitre 02), soit environ 80 réécritures par demande ouverte.

Coût d'une lecture périmée : BEGIN, upsert, COMMIT (3 allers-retours), plus SELECT et INSERT de `jobs_outbox` quand un job part ; et un calcul de suivi complet si un calcul tournait déjà.

## 2. La question métier

Une lecture qui trouve une liste périmée doit-elle :

1. seulement s'assurer qu'un calcul est en route (une demande ouverte suffit), ou
2. demander un calcul **qui commence après elle** (d'où le calcul de suivi) ?

Une lecture ne change aucune donnée d'entrée du classement. Un calcul déjà parti après le dernier changement de données produira une liste aussi fraîche que le calcul de suivi. Le calcul de suivi n'a de sens que si les **données** ont changé pendant le calcul, ce que disent les autres raisons (événement créé, like, souhait), pas la lecture.

## 3. Options

| Option | Changement | Gain | Risque |
| :--- | :--- | :--- | :--- |
| A. Statu quo plus une seule requête | `WITH r AS (INSERT ... ON CONFLICT ... RETURNING ...) INSERT INTO jobs_outbox ... SELECT ... FROM r WHERE r.needs_job` en autocommit (plan initial, chapitre 03) | 3 à 5 allers-retours vers 1 | Aucun changement de comportement ; les 5,3 millions d'UPDATE et les calculs de suivi restent |
| B. Une lecture ne réécrit pas une demande ouverte (**recommandée**) | Pour `STALE_REFRESH` seulement : `ON CONFLICT ... DO UPDATE ... WHERE r.job_enqueued_at <= now() - ttl` (sinon `DO NOTHING`) ; les raisons de données (`IMMEDIATE_REASONS`, événements) gardent la réécriture | La plupart des UPDATE disparaissent, et les calculs de suivi provoqués par des lectures aussi | Une lecture arrivée pendant un calcul ne relance rien : la liste servie juste après est celle du calcul en cours. Si ce calcul échoue, la demande reste ouverte et le TTL relance un job (comportement actuel du TTL) |
| C. Seuil de temps pour toutes les raisons | `... DO UPDATE ... WHERE r.requested_at < EXCLUDED.requested_at - interval 'N s'` | Moins d'UPDATE, toutes raisons confondues | Un changement de données arrivé moins de N s après une demande, pendant un calcul, est manqué jusqu'au calcul suivant : perte de fraîcheur réelle |
| D. Plus d'écriture à la lecture | La lecture ne demande rien ; la péremption est traitée par un balayage périodique (job planifié) | Plus aucune écriture sur le chemin de lecture | Liste périmée servie plus longtemps (jusqu'au balayage) ; un job planifié de plus, une logique de priorité à écrire |

B et A se combinent : B réduit le nombre d'écritures, A le nombre d'allers-retours de celles qui restent.

## 4. Recommandation

**B puis A**, dans un même lot `domain-ranking` (STOP), puis `ms-ranking`. Critère d'acceptation : pendant une rampe de lecture, `n_tup_upd` de `ranking_request` par lecture périmée et le nombre de jobs de suivi (`markFollowUpSql`) baissent à débit égal, sans hausse du délai moyen de fraîcheur des listes (mesure à définir avec `docs/matching`, chapitres 13 et 14).

## 5. Décision attendue de Victor

1. La lecture périmée doit-elle encore provoquer un calcul de suivi ? (oui : A seule ; non : B)
2. Si oui avec une limite : quel N pour l'option C ?
3. Faut-il viser D plus tard (aucune écriture à la lecture) ?

Non vérifié : la liste exacte de `IMMEDIATE_REASONS` et des raisons émises par les post-processors de ranking (à relire dans `ms-ranking` avant de coder) ; la part des 5,3 millions d'UPDATE qui vient des lectures (chapitre 05, point 15, mesurable après L0).
