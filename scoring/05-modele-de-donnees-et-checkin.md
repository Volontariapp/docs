# 05 - Modèle de données et check-in

Propositions de modèle. Rien n'existe encore, voir [01](01-etat-des-lieux.md).

## 1. Inscription : ordre et présence (ms-social, Neo4j)

L'arête actuelle `(:SocialUser)-[:PARTICIPATE]->(:SocialEvent)` n'a aucune propriété (`neo4j-participation.repository.ts:89-98`). On lui ajoute :

| Propriété | Type | Rôle |
| :--- | :--- | :--- |
| `registeredAt` | datetime | Posé à la création de l'arête. Sert à ordonner les présents. |
| `checkedInAt` | datetime, nullable | Posé quand le créateur coche le participant. Vide tant que non présent. |

Règles :

- `createParticipation` utilise `MERGE ... ON CREATE SET r.registeredAt = datetime()`. Un `MERGE` rejoué ne modifie pas la date d'origine.
- Une désinscription supprime l'arête (`deleteParticipation`, lignes `100-108`), donc une réinscription reçoit une nouvelle date et passe en fin de file. C'est voulu : on ne peut pas garder une place.
- Les arêtes existantes n'ont pas de `registeredAt`. Pour les événements non terminés au déploiement, on les initialise à une date de repli (par exemple la date de migration) avec une règle de départage stable sur `userId`.
- La lecture ordonnée des présents est une nouvelle requête (`MATCH ... WHERE r.checkedInAt IS NOT NULL RETURN u.userId, r.registeredAt ORDER BY r.registeredAt ASC, u.userId ASC`) avec pagination stable. L'existant (`getEventParticipants`, `197-211`) n'ordonne pas.
- Un index sur `registeredAt` n'est utile que si les événements sont très grands. À mesurer avant d'en créer un.

## 2. Check-in

| Aspect | Décision |
| :--- | :--- |
| Qui | Le créateur (organizerId) ou un admin, comme pour le changement d'état (`event.service.ts:180-226`, exploré). |
| Quand | À partir de `IN_PROGRESS`, jusqu'au passage à `FINISHED`. |
| Verrouillage | À `FINISHED`, plus aucune modification : `N` et les rangs deviennent définitifs. |
| Opération | Un RPC par lot : `SetEventAttendance(eventId, userIds[] cochés, userIds[] décochés)`, idempotent. |
| Contrôle | On ne peut cocher que des utilisateurs ayant une arête `PARTICIPATE`. |

## 3. Registre de crédits (ms-user, PostgreSQL)

`impact_score_credits` a aujourd'hui `(event_id, user_id)` en clé, `score`, `created_at`. On ajoute des colonnes nullables (étape "Expand", compatible zero-downtime, voir le playbook `volontariapp-db-migration`) :

| Colonne | Type | Rôle |
| :--- | :--- | :--- |
| `role` | `text` : `PARTICIPANT` ou `ORGANIZER` | Distingue la prime du créateur. Nullable pour l'historique. |
| `rank` | `int` nullable | Rang d'inscription parmi les présents. Vide pour le créateur. |
| `formula_version` | `int` nullable | Version de formule appliquée. Vide pour l'historique. |
| `event_pool` | `int` nullable | `P` de l'événement, pour auditer la somme. |

La clé `(event_id, user_id)` reste valable : un utilisateur ne reçoit qu'un crédit par événement (créateur ou participant, jamais les deux, voir [03](03-formule.md)).

Index à prévoir pour les classements périodiques ([09](09-leaderboard.md)) : `(created_at, user_id)`.

## 4. Événement (ms-event)

- `awardedImpactScore` : **n'est plus saisi**. Il ne peut pas devenir un "résultat calculé par `ms-event`" car la présence vit dans `ms-social` et le calcul dans `post-processor-user` (voir [06](06-flux-asynchrone.md)). Il reste en base pour l'historique et pour distinguer les anciens événements.
- Une colonne `scoring_version` nullable sur l'événement marque les événements créés sous la nouvelle règle. Vide : ancien événement, comportement hérité (voir [06](06-flux-asynchrone.md), section 5).
- La durée n'est pas stockée, elle se dérive de `startAt` et `endAt`.
