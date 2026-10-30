# 10 - Plan de livraison et risques

## 1. Tranches

Peu de gros tickets, une PR par dépôt touché, 3 heures au plus par ticket. Chaque tranche respecte la règle du STOP ([07](07-contrats-et-impacts-par-repo.md)).

| Tranche | Contenu | Dépend de |
| :--- | :--- | :--- |
| S0 | Exposant, plafond du premier, arrondi et seuil du créateur tranchés ([04](04-exemples-et-simulations.md), script figé dans `scripts/simulate.py`). Reste : bornes de `alpha`. | Décision de Victor |
| S1 | `proto-registry` : RPC check-in, lecture des présents, champs. | S0 |
| S2 | `npm-packages` : messaging, shared (calcul pur et tests), domain-social, domain-event, domain-user. Publication CI. | S1 |
| S3 | `ms-social`, `ms-event`, `ms-user` (migration "Expand"). | S2 publié |
| S4 | `post-processor-user` : lecture des présents, calcul, crédit participants et créateur, chemin hérité. | S3 |
| S5 | `api-gateway` : route de check-in, DTO sans score. | S3 |
| S6 | `nativapp` : formulaire, check-in, affichages, rangs recalibrés. | S5 |
| S7 | Leaderboard ([09](09-leaderboard.md)). | S3 |
| S8 | Doc finale, `evolve.py plan`, ajustements. | Toutes |

Déploiement en deux temps : consommateurs tolérants (payload optionnel, ancien chemin conservé) avant les producteurs, pour que les messages en vol ne cassent rien.

## 2. Risques

| Risque | Gravité | Réponse |
| :--- | :--- | :--- |
| **Sybil** : un créateur crée un événement avec des comptes complices, les coche présents et encaisse `P` et la prime. L'inflation de points n'est pas bornée par un coût réel. | Haute, atténuée | Atténué : la prime du créateur exige 3 présents (`MIN_ATTENDEES_FOR_ORGANIZER_POINTS`). Reste ouvert : plafond de points par utilisateur et par période ; plafond d'événements rémunérés par créateur et par jour. Journal d'audit des crédits en place (`event_pool`, `rank`). |
| **Créateur plus payé qu'un participant à `N` faible** (`N`=1 : 180 contre 120 avant le seuil) | Résolu | Seuil de 3 présents : prime à 0 pour `N` < 3. |
| **Bonus du premier trop élevé à grand `N`** (+248 % à 200) | Résolu | Plafond de +100 % de la moyenne pour tous les rangs ([04](04-exemples-et-simulations.md), section 3). |
| **Check-in non verrouillé à `FINISHED`** : `ms-social` n'a pas d'état d'événement, donc `N` et les rangs peuvent changer après la clôture, y compris entre deux rejeux. | Haute | Point ouvert : placer le verrou dans `ms-event` ou porter un état d'événement dans `ms-social`. |
| **Rang instable au rejeu** | Haute | Tri stable `registeredAt, userId` ([06](06-flux-asynchrone.md)). |
| **Capacité non appliquée** (`N > beta`) | Moyenne | Plafonner `N/beta` à 1, vérifier l'application de la capacité (S3). |
| **Check-in oublié** : le créateur termine sans cocher personne, aucun point | Moyenne | Rappel dans la modale de clôture et nombre de présents cochés affiché. Décision ouverte : durée de grâce après `FINISHED`. |
| **Réinscription pour changer de place** | Faible | Une réinscription passe en fin de file ([05](05-modele-de-donnees-et-checkin.md)). |
| **Dérive des rangs d'impact** après recalibrage | Moyenne | Pas de backfill, seuils revus par simulation ([08](08-impacts-nativapp.md)). |
| **Messages `event.finished` anciens** sans nouveaux champs | Moyenne | Champs optionnels, chemin hérité si `scoring_version` est absent. |
| **Confusion de vocabulaire** score, rank, ranking | Faible | Glossaire du [README](README.md). |

## 3. Points non vérifiés avant implémentation

- L'application de la capacité côté `ms-social` et `ms-event`.
- Le déclencheur de `FINISHED`.
- Qu'un organisateur n'a pas d'arête `PARTICIPATE`.
- Le verrouillage du check-in à `FINISHED` : où il vit (voir le risque ci-dessus).
- Le consommateur `ws-service` de `user.impact_score_credited` (à confirmer avec `analyze_impact`, sur toutes les racines).
