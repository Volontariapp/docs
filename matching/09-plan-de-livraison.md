# 09 - Plan de livraison, risques et questions ouvertes

Ce plan intègre les résultats d'une revue indépendante (agent senior, lecture seule) : voir la section 7 pour le journal des corrections.

> [!NOTE]
> L'ordre d'exécution à jour, sous forme de tickets (RK-01 à RK-23), est dans [14](14-plan-d-implementation.md). Ce fichier garde les tranches fonctionnelles, les risques et le scénario de démonstration.

## 1. Ordre imposé par la règle du STOP

`AGENTS.md` section 1 interdit de coder dans un consommateur tant que l'amont n'est pas publié. Les étapes ne sont **pas** parallélisables.

| Ordre | Dépôt(s) | Contenu | Sortie obligatoire |
| :--- | :--- | :--- | :--- |
| 1 | `proto-registry` | paquet `ranking` + `AdminGetRecommendedEventIds` | `buf lint`, `buf breaking`, **STOP**, PR automatique dans `npm-packages`, publication |
| 2 | `npm-packages` | `messaging` (jobs **et mapping WebSocket**), `shared` (streams, dont `user:deleted:ranking`), `domain-ranking` (nouveau), `domain-user` (ajout du stream de purge) | `yarn build`, `yarn test`, changeset, **STOP**, PR, publication CI |
| 3 | `ms-social` | handler `AdminGetRecommendedEventIds` | tests, `yarn up` des paquets publiés |
| 4 | `ms-ranking`, `outbox-ranking`, `worker-ranking`, `post-processor-ranking` | nouveau domaine | tests, images, `yarn up` |
| 4 bis | `ws-service` | `USER_RANKING_DELETED` ajouté aux `expects` du gather `user.deleted` (`config/default.config.json`) et post-processors de feedback correspondants | tests ; à déployer **après** `post-processor-ranking` (sinon chaque suppression de compte échoue au bout de 60 s) |
| 5 | `api-gateway` | `GET /ranking/events`, `POST /ranking/refresh` | tests |
| 6 | `deploy`, `ci-tools`, racine `meta` | manifestes, secrets, NetworkPolicies, CI, `e2e-matrix`, `sync-migrations.sh` | `kubeseal` par le Lead Dev (étape humaine : skill `wizard`) |
| 7 | `nativapp` | hook, discrimination du 206, handler de notification, écran | tests |

Le hook `.claude/hooks/stop-rule-guard.sh` verrouille mécaniquement les dépôts consommateurs après toute modification de `proto-registry` ou `npm-packages`. Le déverrouillage (`release`) appartient au Lead Dev.

Le **feed de posts** ([10](10-feed-etat-des-lieux.md) à [12](12-feed-plan-et-risques.md)) ajoute ses RPC `ms-post` à la même PR `proto-registry` et impose que `ms-post` soit publié avant `worker-ranking` et `api-gateway`.

## 2. Tranches fonctionnelles

| Tranche | Contenu | Résultat démontrable | Jev ? |
| :--- | :--- | :--- | :--- |
| **T0** | Squelettes, migrations, `docker-compose` local, post-processors communs, mapping WebSocket | les services démarrent, `job_audit` et le feedback WebSocket fonctionnent avec un job factice | Non |
| **T1** | Candidats depuis `ms-event` (publiés, non commencés, rayon de 100 km), signal d'amis booléen, score structurel (`NoopRankingScorer`), route de position, retour `PASS`, déclencheur `social:user`, lecture par curseur, 206 à la demande, notification, codes d'explication | `GET /ranking/events` renvoie une liste classée par le graphe et la proximité ; le démarrage à froid fonctionne de bout en bout | **Non** |
| **T2** | Adaptateur Jev, résumé de goût, dégradation par sous-lot, coupe-circuit | classement hybride, `source = FULL` | Oui |
| **T3** | Déclencheurs souhait, événement créé (fan-out), événement terminé ; coalescence ; popularité (tables de souhaits et de mentions) | la liste évolue quand l'utilisateur agit et les événements populaires remontent | Non |
| **T4** | `STALE_REFRESH`, `RequestRankingRefresh`, limite de fréquence, alertes `jobs_outbox` | liste toujours disponible, bouton « recalculer » | Non |
| **T5** | Événements de participation/follow (`domain-social`) ; la purge à la suppression de compte est livrée dès T0 | réactivité complète | Non |
| **T6** | Application : hook, 206, WebSocket, écran | démonstration de bout en bout | Non |

T1 est livrable et défendable sans accès à Jev.

## 3. Risques

| Risque | Gravité | Atténuation |
| :--- | :--- | :--- |
| Notification de fin de calcul inexistante sans mapping messaging | Haute (bloquant fonctionnel) | mapping ajouté au périmètre de l'étape 2 ([04](04-flux-asynchrone.md) section 9) |
| Les jobs dont le push BullMQ échoue sont perdus (`FAILED` définitif, ligne `PROCESSING` bloquée après crash) | Haute | réémission par la lecture suivante (`ranking_request` + TTL), `STALE_REFRESH`, alertes sur `jobs_outbox` |
| RPC `Admin*` sans contrôle de rôle (IDOR préexistant) | Haute | à signaler au Lead Dev ; hors périmètre mais à corriger |
| Données du compte conservées dans `ms-ranking` après suppression | Moyenne (conformité) | stream `user:deleted:ranking` et post-processor de purge (T0), voir [03](03-modele-de-donnees.md) section 5 ; vérifier le gather de `ws-service` |
| Candidats Neo4j arbitraires et obsolètes | Haute | candidats depuis `ms-event` (statuts, date, pagination explicite) |
| Chemin d'échec : nom de stream **et** statut `PENDING` erronés, `FAILED` émis à chaque tentative | Moyenne | délai d'attente côté client, alerte `job_audit`, correction du post-processor commun recommandée (hors périmètre) |
| 206 détourné de son sens pour une lecture, corps d'erreur résolu comme succès par axios | Moyenne | discrimination sur `data.code`, alternative 200 `{ status: 'PENDING' }` documentée |
| Accès Jev indisponible (liste d'attente ; un guide tiers signale une pause des inscriptions fin septembre 2026, non confirmé) | Moyenne | T1 sans Jev ; port `RankingScorer` ; passerelles tierces (format différent) en plan B |
| Données personnelles dans le texte d'événements envoyé à un tiers sans politique de rétention documentée | Haute | liste blanche, troncature, masquage, texte public, test de non-régression |
| Événements de souhait perdus (écriture Neo4j puis insertion outbox non atomique, échec avalé) | Moyenne | `STALE_REFRESH` comme filet de sécurité |
| Volume de travail | Haute | tranches ; copier les modèles ; T1 d'abord |
| Tempête de notifications WebSocket (une par job `COMPLETED`, y compris ceux sautés) | Faible | handler client idempotent avec regroupement |
| Utilisateurs actifs au-delà du plafond de fan-out non recalculés | Faible | `STALE_REFRESH` |
| Historique de goût arbitraire (pas de tri ni d'horodatage dans Neo4j) | Faible | acceptée en V1 ; correctif : `createdAt` sur les relations |

## 4. Questions ouvertes

### Tranchées par la revue (vérifiées dans le code)

| # | Question | Réponse |
| :--- | :--- | :--- |
| 2 | Qui écarte les événements complets ? | Aucun filtre de capacité n'existe : `only_available` signifie seulement `state = PUBLISHED`. Le filtrage se fait sur `currentParticipants >= maxParticipants` après lecture, dans le worker puis dans la gateway |
| 5 | Contournement du débounce pour `ON_DEMAND` | Remplacé : la coalescence saute un job **seulement** si un calcul commencé après sa demande a déjà écrit une liste ([04](04-flux-asynchrone.md) section 6) |
| 4 | Appel Jev dans ou hors transaction | **Hors** transaction ; transaction courte pour l'écriture avec anti-écrasement par `started_at` |
| 7 | Contrôle de rôle des `Admin*` | **Absent** (voir risque ci-dessus) |
| 8 | `ms-event` accepte-t-il un jeton interne de service ? | Oui : tout jeton interne valide est accepté (`ms-event/src/app.module.ts:51`) |
| 10 | La gateway propage-t-elle le 206 d'un appel gRPC ? | Oui, via `global-exception.filter.ts` (`PartialContentError`) |

### À décider par l'équipe

1. **Nom du service** : tranché le 2026-10-18, `ms-ranking` ([13](13-decisions-v1.md)).
2. **`bio` dans le résumé de goût** : exclue. Tranché le 2026-10-18 : à Jev, seulement du texte d'événements et de posts publics, aucune donnée personnelle.
3. **206 ou 200 `PENDING`** : tranché le 2026-10-18, 206 (voir [06](06-lecture-et-206.md) section 5).
4. **Signal d'amis** : booléen en V1. Un compte demande une nouvelle requête Cypher et un message proto adapté.
5. **Suppression de compte** : tranché le 2026-10-18, on modifie `domain-user` (stream `user:deleted:ranking`), voir [13](13-decisions-v1.md).
6. **Rôle système plus étroit que `ADMIN`** : tranché le 2026-10-18, limite connue non bloquante ; jeton `ADMIN` comme `post-processor-user` ; garde de rôle sur les `Admin*` = chantier séparé.

### À vérifier dans le code avant d'implémenter

7. Comment `nativapp` consomme la notification issue de `ws:jobs-outbox-success` (`useNotificationHandlers.ts`) et si `syncPendingBus` déclenché par un 206 est le comportement voulu.
8. Que `outbox-runners` supporte un nouveau domaine sans changement de code partagé (`command.sh`, workflows).
9. La convention des files `FALLBACK_*` et ce que consomme réellement `fallback-event.worker.ts` (le nommage retenu rompt la convention : [04](04-flux-asynchrone.md) section 3).
10. Plafond de questions par requête Jev, latence réelle de 30 questions, liste des modèles, limites de format d'une clé de question.
11. Statut des inscriptions Jev et politique de conservation des données de TypeSafe AI.
12. Ce que les sous-modules de `deploy/submodules/` exigent pour un nouveau service.

## 5. Définition de « terminé »

- Les tranches T0 à T4 et T6 livrées, tests verts en CI.
- Les STOP respectés (aucune édition d'un consommateur avant publication).
- Les skills `volontariapp-*` concernées resynchronisées (`evolve.py plan` puis `sync`).
- Une démonstration reproductible (section 6).
- Aucun secret en clair dans Git ; NetworkPolicies appliquées.
- Les limites connues (`Admin*` sans rôle, chemin d'échec) documentées.

## 6. Scénario de démonstration

1. **Préparation** : comptes `A` et `B` avec suivi mutuel ; `A` participe à deux événements écologiques et souhaite le troisième.
2. **Compte neuf** : créer `C` et ouvrir l'application. `GET /ranking/events` répond **206** ; l'application affiche la liste d'événements normale ; quelques secondes plus tard la **notification WebSocket** fait basculer sur la liste recommandée. Montrer dans `job_audit` le job `PROCESSING` puis `COMPLETED`.
3. **Utilisateur `B`** : 200, les événements liés à `A` en tête ; afficher `structural_score`, `semantic_score` et `source = FULL`.
4. **Réactivité** : `B` souhaite un événement ; sa liste est recalculée après le délai de 30 s ; le classement change. Faire trois souhaits rapides pour montrer la **coalescence** (un seul calcul).
5. **Résilience** : couper `worker-ranking` (les lectures continuent, `computedAt` vieillit) ; couper Redis (les lectures continuent, la liste est en PostgreSQL) ; invalider la clé Jev (les nouveaux calculs passent en `STRUCTURAL_ONLY`).
6. **Explication d'un classement** : requête SQL sur `ranking_score`.
7. **Confidentialité** : le test qui échoue si un champ interdit apparaît dans la requête Jev.

## 7. Journal des corrections issues de la revue

| Gravité | Constat | Traitement |
| :--- | :--- | :--- |
| Bloquant | Circuit WebSocket inexistant sans mapping messaging | [04](04-flux-asynchrone.md) section 9, [07](07-creation-du-microservice.md) B |
| Bloquant | Post-processors communs `JobOutboxSuccess`/`Failed` oubliés | [04](04-flux-asynchrone.md) section 4, [07](07-creation-du-microservice.md) G |
| Bloquant | Candidats Neo4j arbitraires (pas de tri, de date ni d'état) | [04](04-flux-asynchrone.md) étapes 4 et 5 : candidats depuis `ms-event` |
| Bloquant | Score `friends` non calculable (identifiants dédupliqués) | booléen, [05](05-scoring-et-jev.md) |
| Bloquant | `user:deleted` sans producteur | Obsolète depuis le 2026-10-18 : le producteur existe ([03](03-modele-de-donnees.md) section 5) |
| Majeur | Affirmation fausse sur la reprise après panne Redis | [06](06-lecture-et-206.md) section 6 réécrite |
| Majeur | Déduplication `ON_DEMAND` inopérante | table `ranking_request`, [03](03-modele-de-donnees.md) |
| Majeur | Sémantique du 206 pour un GET et corps d'erreur résolu par axios | [06](06-lecture-et-206.md) sections 3 et 5 |
| Majeur | Collision de route avec `@Get(':id')` | route `/ranking/events` |
| Majeur | `Admin*` sans contrôle de rôle ; cache de jeton présenté à tort comme atténuation | [08](08-tests-observabilite-securite.md) |
| Majeur | Flux `USER_CREATED` erroné ; événements de souhait non atomiques | [04](04-flux-asynchrone.md) section 2 (`social:user`, `STALE_REFRESH` obligatoire) |
| Majeur | Transaction et verrou tenus pendant les appels réseau | calcul hors transaction, anti-écrasement, [04](04-flux-asynchrone.md) section 5 |
| Majeur | Anti-rebond qui jette au lieu de replanifier ; fan-out sans coalescence | coalescence par `requestedAt`/`started_at`, [04](04-flux-asynchrone.md) section 6 |
| Majeur | Deux défauts (et non un) dans le chemin d'échec | [04](04-flux-asynchrone.md) section 10 |
| Majeur | `searchEvents` : pagination par défaut 10, pas de filtre de capacité | [04](04-flux-asynchrone.md) étape 4 |
| Majeur | Inventaire de création incomplet ou inexact (dépôts, `create-outbox.sh`, `e2e-matrix`, `data-source.ts`, deux classes de worker, clé interne, `emitter`) | [07](07-creation-du-microservice.md), [03](03-modele-de-donnees.md) section 1 |
| Majeur | Idempotence des post-processors : mécanisme existant non cité | [04](04-flux-asynchrone.md) section 4 |
| Mineur | `freshness`, `rank`, `last_error`, index/curseur du fan-out, file par `reason`, références de lignes, `has_more`, sous-lot sur `422` | corrigés dans 03, 04, 05, 06 |

Points de la revue **non appliqués ou nuancés** : aucun refus ; la proposition de remplacer le 206 par un 200 `PENDING` est conservée comme alternative documentée, la décision du Lead Dev restant le 206.
