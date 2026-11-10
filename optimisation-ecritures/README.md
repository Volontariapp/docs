# Optimisation des écritures

Dossier rédigé le 2026-11-10 par un agent Claude Code, à partir d'une première analyse des écritures (lecture du code par un autre modèle) que ce dossier vérifie, corrige et complète. Il répond à une question : **que faut-il changer pour qu'une écriture (créer un post, liker, participer, créer ou modifier un événement) coûte moins d'allers-retours, et pour qu'aucun événement ne se perde en route ?**

Le code lu est celui de `origin/main` le 2026-11-10 (`npm-packages` add719b8, `outbox-runners` 2028223, `post-processors-runner` 19e0d892, `workers-runners` 37dc441, `ms-*`, `deploy` e010ccc). TypeORM est lu dans le tarball `typeorm@0.3.31`, la version résolue par tous les `yarn.lock`. Les mesures viennent des bases de prod, en lecture seule.

**Statut au 2026-11-10 vers 16:00 : L0, L2 et L3 en prod, L4 publié, phase 1 de L9 en prod.** L4 se monte dans les runners (outbox-runners#49) ; worker-social (workers-runners#65) en revue ; la phase `async` de L9 attend le [ticket du chapitre 12 de `montee-en-charge`](../montee-en-charge/12-ticket-l9-prerequis-async.md) ; L5 à L8, L10 à L12 restent à faire. Le suivi lot par lot est au chapitre 03, section « Avancement ».

## Le résumé

1. **Le socle partagé coûte plus cher que les domaines.** `BaseRepository.update()` fait 6 allers-retours SQL pour changer une colonne (COUNT, SELECT, BEGIN, UPDATE, COMMIT, relecture avec relations), et `create()` relit la ligne par son id avant de l'insérer dès que l'id est fixé dans le code, ce qui est le cas de toutes les lignes d'`event_queue`.
2. **L'outbox fait 6 requêtes SQL et 1 aller-retour Redis par ligne**, soit 303 requêtes SQL et 50 allers-retours Redis pour un lot de 50, contre 4 SQL et 1 Redis possibles.
3. **Mesuré en prod : 147 événements bloqués depuis le 2026-11-07 15:37** (107 en `PROCESSING`, 40 en `FAILED`) dans cinq bases. Aucun code ne les reprend. C'est le constat le plus important du dossier : aujourd'hui l'outbox livre « au plus une fois », pas « au moins une fois ».
4. **Le délai de l'outbox est mesuré** sur `ms-ranking` : p50 0,44 s, p95 1,63 s, p99 3,11 s entre l'écriture et le passage en `COMPLETED` (142 lignes, 24 h).
5. **`pg_stat_statements` est installable mais pas chargé** dans les sept bases (`shared_preload_libraries` vide). Sans lui, aucun gain ne peut être chiffré en prod.
6. **Les post-processors font un `SET NX` Redis par message**, sur l'id du message Redis et non sur l'id de l'événement, et un verrou posé par un pod qui meurt fait sauter le message quand il est repris.
7. **ms-social écrit dans Neo4j puis dans Postgres sans lien entre les deux**, et avale l'erreur d'outbox en `warn` : un like peut exister sans `post.liked`.
8. **Une lecture écrit** : chaque lecture d'une liste périmée de `ms-ranking` ouvre une transaction et fait un upsert sur `ranking_request` (5,3 millions de mises à jour mesurées pour 67 000 lignes).
9. **Les workers BullMQ traitent un job à la fois** (valeur par défaut de `bullmq` 5.81.5), sauf `worker-ranking` (5).
10. **Ordre proposé** : mesurer, rendre l'outbox sûre (reprise et idempotence), puis alléger le socle `database`, puis les domaines.

## Chapitres

| Chapitre | Contenu |
| :--- | :--- |
| [01 - Constats vérifiés](01-constats-verifies.md) | Les 11 constats de la première analyse classés (confirmé, faux, à nuancer), les constats nouveaux, les allers-retours par opération avant et après, le chemin d'une écriture de la gateway au post-processor |
| [02 - Mesure](02-mesure.md) | Ce qui a été mesuré en prod, comment activer `pg_stat_statements`, les compteurs à suivre, les routes d'écriture que la rampe doit tester |
| [03 - Plan d'implémentation](03-plan-d-implementation.md) | Lots de 3 h au plus : dépôt, fichiers, changement exact, tests, règle du STOP, risques, retour arrière, critère d'acceptation |
| [04 - Risques de cohérence](04-risques-de-coherence.md) | Idempotence sur l'id de l'événement, atomicité Neo4j et outbox, lots d'outbox et fenêtre de panne, triggers SQL |
| [05 - Non vérifié](05-non-verifie.md) | Ce qui reste à regarder, et avec quel outil |
| [06 - Conception de L9](06-conception-l9-ms-social.md) | ms-social « Postgres d'abord » : table `social_edge`, worker-social qui applique dans Neo4j, ordre des événements, concurrence, options écartées |
| [07 - Options de L11](07-options-l11-ms-ranking.md) | L'écriture à la lecture de ms-ranking : fonctionnement, options, recommandation, décision attendue |

## Ordre de mise en œuvre

| Ordre | Lot | Dépôt | Pourquoi à cette place |
| :--- | :--- | :--- | :--- |
| 1 | L0 Mesure : `pg_stat_statements` | `deploy` + une action du Lead Dev | Sans compteur, aucun lot ne peut prouver son gain |
| 2 | L1 Rampe d'écriture | `traffic-simulator` (besoin seulement) | Donne la charge qui rend les compteurs lisibles |
| 3 | L2 Réveil plus rapide de l'outbox | `deploy` | Une variable, gain de délai immédiat, retour arrière trivial |
| 4 | L3 Idempotence sur l'id de l'événement | `npm-packages` (`post-processors`) | Prérequis de toute reprise d'outbox : sans lui, reprendre crée des doublons |
| 5 | L4 Reprise des lignes bloquées | `npm-packages` (`database`) | Rend l'outbox « au moins une fois » ; débloque les 147 lignes après décision |
| 6 | L5 Outbox par lot | `npm-packages` (`database`) | 303 SQL vers 4 par lot ; dépend de L3 et L4 |
| 7 | L6 `update()` et `create()` du socle | `npm-packages` (`database`) | Touche toutes les écritures d'un coup |
| 8 | L7 Créations de post et d'événement | `npm-packages` (`domain-post`, `domain-event`) | Relectures inutiles après insert |
| 9 | L8 Saga et succès de job par lot | `post-processors-runner`, `npm-packages` (`post-processors`) | Une requête par lot au lieu d'un `update()` par événement |
| 10 | L9 ms-social : Postgres d'abord, Neo4j par worker (chapitre 06) | `npm-packages` (`messaging`, `domain-social`), `ms-social`, `workers-runners`, `deploy` | Cohérence d'abord, et lissage des écritures sur Neo4j |
| 11 | L10 Pool de connexions | `npm-packages` (`bridge`, `config`) puis `ms-*` | Taille réelle du pool, budget de connexions |
| 12 | L11 Écriture à la lecture dans ms-ranking | `ms-ranking`, `npm-packages` (`domain-ranking`) | Décision métier préalable |
| 13 | L12 Compteurs de badges et concurrence des workers | `post-processors-runner`, `workers-runners`, `deploy` | Gains locaux, à faire quand la mesure le justifie |

Chaque lot qui touche `npm-packages` suit la règle du STOP (`AGENTS.md`, section 1) : une PR, la publication par la CI, puis seulement `yarn up` chez les consommateurs, dans une autre PR.

## Glossaire

| Terme | Sens dans ce dossier |
| :--- | :--- |
| **Aller-retour (RT)** | Une requête envoyée et sa réponse attendue avant la suivante. `BEGIN` et `COMMIT` en sont chacun un |
| **Outbox** | Tables `event_queue` (événements vers Redis Streams) et `jobs_outbox` (jobs vers BullMQ) écrites dans la transaction métier, puis poussées par un runner |
| **Claim** | Le `UPDATE ... SET status = 'PROCESSING' ... FOR UPDATE SKIP LOCKED RETURNING *` qui réserve un lot de lignes d'outbox |
| **Reprise (reaper)** | Code qui remet en `PENDING` une ligne restée trop longtemps en `PROCESSING`, ou qui relance une ligne `FAILED` |
| **Au plus une fois / au moins une fois** | Garantie de livraison : un message peut être perdu mais jamais doublé, ou jamais perdu mais parfois doublé (il faut alors dédoublonner) |
| **FAIT, INFERENCE, NON VERIFIE** | Un FAIT est une ligne de code citée ou une sortie de commande lue le 2026-11-10. Une INFERENCE est un raisonnement non mesuré. Un NON VERIFIE n'a pas été regardé |
