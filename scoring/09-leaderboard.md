# 09 - Leaderboard

Conception seule. Il n'existe aujourd'hui aucune requête top-N par points (recherche dans `domain-user`, `ms-user`, `api-gateway` et `proto-registry` par exploration, non relue ce jour).

## 1. Besoins

| Besoin | Exemple |
| :--- | :--- |
| Top N global | "Les 50 premiers bénévoles." |
| Ma position | "Tu es 128e, à 340 points du 127e." |
| Autour de moi | Cinq voisins au-dessus, cinq en dessous. |
| Période | Classement de la semaine ou du mois. |

## 2. Où le placer

Dans `ms-user`, qui possède `total_impact_score` et `impact_score_credits`. Pas dans `ms-ranking` : ce service ne possède aucun contenu et son "score" désigne l'affinité d'un utilisateur avec un événement ([matching](../matching/README.md)).

## 3. Lecture

| Classement | Source | Requête |
| :--- | :--- | :--- |
| Global | `users.total_impact_score` | `ORDER BY total_impact_score DESC, id`, index `(total_impact_score DESC, id)`. Position par `RANK()` ou comptage des supérieurs. |
| Période | `impact_score_credits` | `SUM(score) ... WHERE created_at >= $debut GROUP BY user_id ORDER BY 2 DESC`, index `(created_at, user_id)` ([05](05-modele-de-donnees-et-checkin.md)). |

Pagination par keyset (`score, id`), pas par `OFFSET`.

## 4. Contrats

- RPC de lecture dans `user.services.proto` : `GetLeaderboard(scope, period, cursor, limit)` et `GetMyRank(period)`. Passent par la règle du STOP ([07](07-contrats-et-impacts-par-repo.md)).
- Route gateway en GET sous `/users/leaderboard`, avec token interne et repli 206 si besoin (`volontariapp-api-gateway`).

## 5. Vie privée

- Un utilisateur supprimé (`PENDING_DELETION`) ne doit pas apparaître. La suppression de compte cascade déjà les crédits (`suppression-compte/README.md`).
- Pas d'e-mail ni de donnée personnelle dans la réponse : pseudo, avatar, points, position.
- Décision ouverte : classement visible pour tous, ou seulement pour les profils publics.

## 6. Performance

- Le top N tient dans un cache Redis court (30 à 60 s). Pas besoin de temps réel.
- La position de l'utilisateur est une requête indexée (comptage des supérieurs).
- Les classements périodiques peuvent être précalculés par un job BullMQ (`worker-user`, à confirmer) si la table de crédits grossit.

## 7. Ordre de livraison

Après le calcul et le crédit. Le classement est une lecture et n'a pas de dépendance amont : il peut être fait en parallèle, mais ses seuils d'affichage dépendent du recalibrage de [08](08-impacts-nativapp.md).
