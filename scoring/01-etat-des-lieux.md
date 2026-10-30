# 01 - État des lieux

Faits relevés dans le code au 2026-10-30. La colonne "Source" distingue ce qui a été **relu** ce jour de ce qui a été **relevé par exploration** et reste à revérifier avant d'implémenter.

## 1. Ce qui existe

| Élément | Où | Source |
| :--- | :--- | :--- |
| Score total d'un utilisateur `total_impact_score` | `npm-packages/packages/domain-user/src/models/user.model.ts:38` | exploré |
| Points d'un événement `awardedImpactScore` (saisi par le créateur, défaut 0 côté backend) | `npm-packages/packages/domain-event/src/models/event.model.ts:77` | exploré |
| Registre idempotent `impact_score_credits`, clé `(event_id, user_id)`, colonnes `score`, `created_at` | `ms-user/src/migrations/domain/1792100000000-CreateImpactScoreCredits.ts` | exploré |
| Crédit à `FINISHED` : insertion `orIgnore` dans le registre, `increment` du total, ligne outbox `user.impact_score_credited`, une transaction par participant | `post-processors-runner/post-processor-user/src/core/services/impact-score-crediter.service.ts:42-123` | relu |
| Émission de `event.finished` avec `{eventId, eventType, awardedImpactScore}` dans la transaction du changement d'état | `npm-packages/packages/domain-event/src/repositories/postgres-event.repository.ts:289-324` (payload `300-304`) | relu |
| Inscription : arête `PARTICIPATE` créée par `MERGE` sans aucune propriété | `npm-packages/packages/domain-social/src/repositories/neo4j-participation.repository.ts:89-98` | relu |
| Liste des participants : aucun `ORDER BY`, pagination `SKIP/LIMIT` | `neo4j-participation.repository.ts:197-211` | relu |
| Notification temps réel `user.impact_score_credited` puis toast "+N points d'impact" | `nativapp/src/hooks/useNotificationHandlers.ts:172-179` | exploré |
| Échelle de rangs d'impact calculée côté client, calibrée sur 100 points par événement | `nativapp/src/shared/lib/impact-ranks.ts` | exploré |
| Formulaire : presets de points 25, 50, 100, 200, 500 (libre 0 à 10 000), défaut 100 ; presets de durée 1, 2, 3, 4, 8, 24 h (libre 0,5 à 720 h) ; presets de capacité 5, 10, 20, 50, 100 (libre 1 à 5 000) | `nativapp/src/components/forms/EventInfoGrid.tsx`, `EventDurationModal.tsx` | exploré |
| Badges : 13 badges déjà évalués sur `event.finished` | [badges](../badges/README.md) | doc |

## 2. Ce qui manque

| Manque | Conséquence |
| :--- | :--- |
| Aucun ordre d'inscription (`PARTICIPATE` sans timestamp, liste non ordonnée) | Impossible de déterminer "le premier inscrit". |
| Aucune notion de présence (recherche `check-in` et `attendance` sans résultat dans l'exploration ; périmètre : `domain-social`, `ms-social`, `ms-event`) | Le texte du formulaire promet une validation de présence que le backend ne fait pas : tous les `PARTICIPATE` sont crédités. |
| L'organisateur n'est pas crédité (il n'a pas d'arête `PARTICIPATE`) | Aucune incitation à créer. |
| Pas de champ durée | La durée se dérive de `endAt - startAt`. |
| Pas de rang d'impact côté backend | Les seuils vivent dans `nativapp` seulement. |
| Pas de requête top-N par points | Pas de classement des utilisateurs. |

## 3. Points non vérifiés

- **Capacité appliquée ?** L'exploration n'a pas trouvé où une inscription est refusée quand l'événement est plein. Le calcul de `currentParticipants` et son filtre vivent dans la gateway (`api-gateway/src/modules/event/services/event-participants.service.ts:40`, `ranking/helpers/ranked-event-filter.helper.ts:24`), et `0` semble signifier illimité. À vérifier dans `ms-social` avant de s'appuyer sur `N <= beta`.
- **Qui passe l'événement à `FINISHED` ?** Manuel par l'organisateur ou job planifié : ouvert dans [badges/07](../badges/07-evenement-event-finished.md).
- **Un organisateur peut-il aussi avoir une arête `PARTICIPATE` ?** Non vérifié. La règle de [03](03-formule.md) l'exclut des participants pour être sûre.

## 4. Pièges de nommage

"Score" et "rank" désignent déjà autre chose :

- `matching/05` : score de recommandation d'`ms-ranking` (structurel et sémantique, version `FORMULA_VERSION`).
- Rangs d'impact du front (`impact-ranks.ts`).

Ce dossier parle de **points** et de **rang d'inscription**, et ne construit rien dans `ms-ranking`, dont la décision d'architecture est de ne posséder aucun contenu ([matching](../matching/README.md)). `ms-ranking` consomme déjà `event.finished` pour ses propres déclencheurs : c'est un consommateur indépendant du calcul des points.
