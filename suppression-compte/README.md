# Suppression de compte : événements, organisateur et participants

> [!NOTE]
> **Statut : proposition de conception, rien n'est implémenté.** Les règles de la section 3 viennent du Lead Dev. Les faits de la section 2 sont vérifiés dans le code (références `fichier:ligne`). Les points de la section 4 sont des questions ouvertes, avec une recommandation quand il y en a une.

---

## 1. Contexte

Deux sujets se rejoignent ici :

1. **Le crédit du score d'impact** à la fin d'un événement (`ImpactScoreCrediter`, table `impact_score_credits`) échoue sur une clé étrangère si un participant n'existe plus dans `users`.
2. **Le sort des événements** quand leur organisateur supprime son compte : aujourd'hui ils disparaissent, même avec des participants.

Le Lead Dev propose une règle simple pour les deux cas (section 3).

---

## 2. Comportement actuel (faits vérifiés)

| Cas | Comportement aujourd'hui | Source |
| :--- | :--- | :--- |
| **Organisateur supprime son compte, côté `ms-event`** | Tous ses événements sont supprimés, sans regarder les participants, et `event.deleted` est ré-émis pour chacun. | `UserDeletedPostProcessor` (`post-processor-event/src/post-processors/user-deleted.post-processor.ts`) appelle `deleteAllByOrganizerWithEventDeleted` (`domain-event/src/repositories/postgres-event.repository.ts`) |
| **Organisateur supprime son compte, côté `ms-social`** | Les `SocialEvent` qu'il a créés (relation `CREATED`) sont supprimés avec `DETACH DELETE`, ce qui efface aussi les relations `PARTICIPATE` de ces événements. | `purgeUser`, `domain-social/src/repositories/neo4j-social-user.repository.ts:44-57` |
| **Participant supprime son compte** | Son nœud `SocialUser` est supprimé avec `DETACH DELETE`, donc ses relations `PARTICIPATE` et `WISH_TO_PARTICIPATE` disparaissent. Le lien participant/événement est donc déjà coupé dans `ms-social`. | même fonction `purgeUser`, types de relations dans `neo4j-participation.repository.ts:95,128` |
| **Compteur `currentParticipants`** | Déclaré sur l'événement, mais aucun site d'écriture trouvé dans `ms-event`, `ms-social`, `post-processors-runner`, `domain-event` et `domain-social`. Non déterminé pour les autres racines (`ws-service`, runners outbox et workers, `nativapp`). | `domain-event/src/entities/event.entity.ts:20` |
| **Moment où la ligne `users` disparaît** | Seulement à la fin du gather `user.deleted`, donc après la purge des autres services. | skill `volontariapp-user-account-deletion`, règle sur `finalizeDeletion` (non relu dans le code pour ce document) |

### Conséquence pour le crédit du score

Comme un participant supprimé est retiré de `ms-social` avant la suppression de sa ligne `users`, il n'apparaît normalement plus dans la liste de participants lue par `pp-user`. L'échec de clé étrangère reste possible dans une **fenêtre de course** : `pp-user` lit la liste des participants, puis la ligne `users` est supprimée avant la transaction de crédit.

Dans ce cas, la transaction échoue, le message est relancé puis part en DLQ. Les participants listés avant celui qui échoue sont déjà crédités (chaque participant a sa transaction), ceux listés après ne le sont pas. `BadgeEvaluator` a le même comportement, car son insertion de déduplication `badge_progress_events` a aussi une clé étrangère vers `users`.

---

## 3. Règles proposées

| # | Situation | Règle |
| :--- | :--- | :--- |
| R1 | Un **participant** supprime son compte | On coupe seulement le lien entre lui et l'événement dans `ms-social`. L'événement continue. |
| R2 | L'**organisateur** supprime son compte et **aucun autre participant** n'est inscrit | L'événement est supprimé (comportement actuel). |
| R3 | L'**organisateur** supprime son compte et **au moins un autre participant** est inscrit | Un nouvel organisateur est élu parmi ces participants. L'événement est conservé. |

R1 est déjà vraie dans `ms-social` (section 2). Il reste à confirmer qu'aucune autre trace du participant ne subsiste côté `ms-event`.

R2 et R3 changent le comportement actuel : aujourd'hui l'événement est supprimé dans tous les cas.

---

## 4. Points à trancher avant d'implémenter

### 4.1 Qui décide, et dans quel ordre

`ms-social` possède la liste des participants, `ms-event` possède `organizer_id`. Les consommateurs de `user.deleted` (`post-processor-event`, `-social`, `-post`, `-storage`) tournent en parallèle et de façon indépendante.

Aujourd'hui `purgeUser` supprime les `SocialEvent` créés par l'utilisateur et efface leurs participations. Si ce processor passe avant que l'élection ait eu lieu, les participants à élire n'existent plus. La purge sociale doit donc être modifiée **en même temps** que `ms-event`, sinon R3 est impossible.

Deux options :

- **A.** `ms-social` élit (il a la liste), re-pointe la relation `CREATED` vers le nouvel organisateur, puis émet un événement que `ms-event` consomme pour mettre à jour `organizer_id`.
- **B.** `ms-event` demande la liste à `ms-social` par gRPC, élit, puis demande à `ms-social` de re-pointer `CREATED`.

Recommandation : **A**, parce que la donnée nécessaire est locale à `ms-social` et que cela évite un appel synchrone depuis un post-processor. À valider.

### 4.2 Élection aléatoire ou déterministe

Un tirage aléatoire n'est pas rejouable. Si le traitement échoue à moitié (retry, DLQ), un second passage peut désigner une autre personne, et `organizer_id` (`ms-event`) diverge de la relation `CREATED` (`ms-social`).

Recommandation : une règle **déterministe**, par exemple le participant inscrit depuis le plus longtemps, avec l'identifiant comme départage. Sinon, persister le choix avant d'agir et le relire au rejeu.

### 4.3 Éligibilité du candidat

Un participant lui-même en `PENDING_DELETION` doit être exclu, sinon l'événement change d'organisateur puis le nouveau part à son tour. Le statut vient de `ms-user`, donc il faut un appel ou un ordre d'exécution qui le garantisse.

### 4.4 L'organisateur est-il un participant ?

Non déterminé. À la création, le code crée la relation `CREATED` (`neo4j-participation.repository.ts:54,74`) et la relation `PARTICIPATE` est créée séparément (`:95`). La règle « aucun participant autre que lui-même » suppose qu'on sait si l'organisateur est aussi compté parmi les participants.

### 4.5 Droits et consentement du nouvel organisateur

Le nouvel organisateur hérite de droits d'organisation (changer l'état, modifier l'événement). Décision produit : le prévenir par WebSocket, lui laisser ou non la possibilité de refuser, et comment élire à nouveau s'il refuse.

### 4.6 Événements terminés ou annulés

Supprimer un événement `FINISHED` n'annule ni les badges ni le score déjà crédités, car ils vivent dans `ms-user`, mais cela fait perdre l'historique. À débattre : conserver les événements `FINISHED` et `CANCELLED` en anonymisant l'organisateur, au lieu de les supprimer.

### 4.7 `currentParticipants`

Aucun site d'écriture trouvé (section 2). Ne pas s'en servir pour décider qu'il n'y a « aucun autre participant » : utiliser la liste de `ms-social`.

### 4.8 Badge d'organisateur

`EVENT_HOST_COUNT_1` est attribué à la création de l'événement. Le nouvel organisateur n'en reçoit pas. À confirmer.

---

## 5. Lien avec le crédit du score d'impact

R1 réduit la fenêtre de course mais ne la supprime pas, parce que la suppression de la ligne `users` et la lecture de la liste de participants ne sont pas atomiques.

Atténuation possible, non implémentée : dans `ImpactScoreCrediter` (et `BadgeEvaluator`), traiter l'erreur de clé étrangère (`23503`) sur un participant comme « utilisateur supprimé » : journaliser un `warn`, passer au suivant, et ne pas faire échouer l'événement. Elle demande un test dédié.

---

## 6. Plan de mise en oeuvre suggéré (non engagé)

1. Trancher 4.1 à 4.4 avec l'équipe.
2. Contrats : nouvel événement de transfert d'organisateur dans `npm-packages/packages/messaging`, et changements dans `domain-social` et `domain-event`. Règle du STOP : publication par la CI avant de toucher aux services.
3. `ms-social` : adapter `purgeUser` pour ne plus supprimer les événements à transférer.
4. `ms-event` / `post-processor-event` : remplacer `deleteAllByOrganizerWithEventDeleted` par la règle R2/R3.
5. Tests : élection rejouable, organisateur seul, organisateur avec participants, participant en cours de suppression.
6. `nativapp` : message au nouvel organisateur.
