# 07 - ms-event-db, puis la mémoire de la VM

Suite du [chapitre 06](06-resultats-vague1.md), le 2026-11-09 de 12:30 à 14:00 (UTC). Chaque chiffre est un **FAIT** (sortie de `yarn load`, `EXPLAIN`, `record-ramp.sh`, API du kubelet, journaux) sauf mention **INFERENCE**.

## 1. Le résumé

1. **La confirmation à 300 req/s est fragile.** Au second passage, 300 tient sans erreur mais avec un p95 de 483 ms, et `ms-event-db` colle à sa limite de CPU (799m sur 800m).
2. **La cause côté base est le total de la recherche.** `EXPLAIN` en production : la page lit 61 lignes par index, le `COUNT` lit toute la table `events` à chaque recherche. C'est environ 80 % du travail de `ms-event-db` à 300 req/s.
3. **Le correctif est livré** (`domain-event` 3.17.0 et ms-event#96 : total en cache 10 s, listes en un seul paramètre tableau), **mais son effet n'a pas pu être mesuré.**
4. **La VM manque de mémoire.** Les deux rampes suivantes se sont effondrées à 275 puis à 200 req/s, avec peu de CPU et aucune erreur dans les `ms-*` : la VM relisait son disque (cache des fichiers vidé). Avec 11,8 Gi, il ne reste qu'environ 2 Go de cache disque une fois les pods chargés.
5. **Prochaine marche : la mémoire, avant le code.** Plus de mémoire pour la VM (Proxmox), ou moins de mémoire consommée dans le cluster, puis refaire la mesure.

## 2. La confirmation (12:31 à 12:36)

Mêmes paliers qu'au chapitre 06, rejoués 15 minutes plus tard.

| | 275, 1er passage | 275, confirmation | 300, 1er passage | 300, confirmation |
| :--- | :--- | :--- | :--- | :--- |
| p95 | 159 ms | 225 ms | 196 ms | **483 ms** |
| p99 | 342 ms | 554 ms | 314 ms | 760 ms |
| Erreurs | 0 % | 0 % | 0 % | 0 % |
| Nœud au pic | 7,9 vCPU (56 %) | 9,0 vCPU (64 %) | 7,9 vCPU (56 %) | 10,2 vCPU (72 %) |
| `ms-event-db` au pic | | 666m | 707m | **799m** (limite 800m) |
| Pods de gateway | 5 | 5 | 5 | 5, puis 6 à 12:35:10 |

À 300, le p50 monte régulièrement sur les 9 fenêtres (51 puis 166 ms) : la base est bridée par sa limite. Le même travail coûte plus de CPU qu'au premier passage (9 à 10 vCPU contre 7,9) ; INFERENCE, non vérifiée faute de relevé de fréquence : l'hôte a chauffé et baissé sa fréquence ([chapitre 04](04-resultats.md), section 4.6).

**Verdict** : 275 req/s confirmés avec marge ; 300 req/s tiennent, mais à la limite.

## 3. Pourquoi ms-event-db

Chaque `events-list-app` (40 % du mélange, environ 120 recherches par seconde à 300 req/s) appelait `searchAdvanced`, qui envoyait deux requêtes : la page, puis un `COUNT(1)` sans `LIMIT` ajouté par `getManyAndCount()` de TypeORM. Mesures en production, table `events` de **15 333 lignes** :

| Requête | Plan | Blocs lus | Durée |
| :--- | :--- | ---: | ---: |
| Page (`ORDER BY "createdAt" DESC, id DESC LIMIT 20 OFFSET 40`, 1 000 ids exclus) | `Index Scan` sur `idx_events_created_at_desc`, arrêt après 61 lignes, `Incremental Sort` | 24 | 1,35 ms |
| Total, 1 000 ids en tableau littéral (comme en production) | `Seq Scan` de toute la table | 987 | 4,95 ms, plus 0,79 ms de planification |
| Total, 1 000 ids issus d'une sous-requête | `Seq Scan`, sans table de hachage | 987 | 56,7 ms |

INFERENCE (calcul) : 120 recherches par seconde à environ 7 ms (total et page) font environ 0,84 vCPU, soit la limite de 0,8 vCPU de la base, atteinte pendant la confirmation. Le total pèse environ 80 % de ce travail. La page coûte la même chose quelle que soit la taille de la table ; le total grossit avec chaque événement créé.

La dernière ligne du tableau montre qu'un tableau d'ids non constant pour le planificateur (sous-requête) fait perdre le hachage et multiplie le coût par 11 : à garder en tête si la forme des paramètres change encore.

## 4. Ce qui a été livré

| Changement | PR | En production |
| :--- | :--- | :--- |
| `domain-event` 3.17.0 : option `knownTotal` sur `searchAdvanced` (le total est sauté quand l'appelant le connaît, sinon page et total en parallèle) ; listes d'ids en un seul paramètre `uuid[]` (`= ANY`, `<> ALL`) ; `findByIds` avec `relationLoadStrategy: 'query'` (plus de produit cartésien tags x exigences) | `npm-packages#316` | publié (`npm view` vérifié), verrou STOP levé |
| ms-event : `domain-event` ^3.17.0, cache du total de la recherche 10 s par filtre (empreinte sha1 de tous les champs sauf `page` et `limit`, listes triées), 5 000 entrées, compteurs `event-search-total` | `ms-event#96` | `sha-0695761` depuis 13:41 |
| Gateway : HPA 6 à 7 pods au lieu de 5 à 6 ; sonde de disponibilité HTTP sur `/api/v1/health` au lieu du port TCP | `deploy#73` | depuis 12:53 |

Décision appliquée : D2 (total en cache 10 s, contrat inchangé).

## 5. Les deux effondrements

### 5.1 Palier 275 à 13:44:50

| Route | Requêtes | Erreurs |
| :--- | ---: | ---: |
| `events-list-app` | 4 440 | 41 % |
| `is-following` | 1 073 | 40 % |
| `posts-list` | 3 421 | 27 % |
| `me` | 2 256 | 3 % |

- Arrêt automatique à la 4e fenêtre : 28,8 % d'erreurs, p95 3,4 s.
- **Toutes les erreurs sont des 504** de la deadline de 2 s (`api-gateway#123`, `GatewayTimeoutException`). Aucune erreur ni avertissement dans les journaux de ms-event, ms-social, ms-post et ms-user.
- Au palier 300 lancé ensuite (13:47), les 504 arrivent alors que **le nœud est à 26 % de CPU** (3,8 vCPU à 13:47:13).
- Les routes qui passent par ms-social et Neo4j sont les plus touchées ; `me` (ms-user seul) l'est peu.

### 5.2 Montée douce à 13:53

| Palier | p95 | Erreurs | CPU du nœud |
| ---: | :--- | ---: | ---: |
| 100 | 125 à 159 ms (581 ms une fenêtre) | 0 % | |
| 150 | 133 à 163 ms | 0 % | 26 à 27 % |
| 200 | 162 ms, puis **8,8 s** dès la 2e fenêtre | 65 à 70 % | 26 à 30 % |

### 5.3 La signature : la VM relit son disque

| Moment | Lectures disque des pods système (Traefik, coredns, agent Datadog, argocd) |
| :--- | :--- |
| Palier 300 de midi (12:13 à 12:15) | **aucune** |
| Avant la montée douce (13:52) | aucune |
| Palier 150 (13:54:54) | 8 à 11 Mo/s |
| Après l'arrêt de la charge (13:56:16 à 13:56:49) | **45 à 80 Mo/s** |
| 13:59:52 | 1 à 3 Mo/s, retour progressif |

Mémoire relevée par l'API du kubelet :

| Mesure | Valeur |
| :--- | :--- |
| Capacité du nœud | 11,8 Gi (`12379548Ki`) |
| Mémoire des processus (`rss`) | 8 583 Mo |
| Mémoire disponible | 2 114 à 2 657 Mo |
| Défauts de page majeurs | 5 495 502 à 13:49:47, 5 933 113 à 13:56:20 (environ 1 100 par seconde) ; 32 par seconde au repos |
| Traefik | 134 Mi à 13:49, 598 Mi à 13:57 (aucune limite mémoire) |
| Plus gros pods | `clamd` 961 Mi, `neo4j` 607 Mi, Traefik 558 à 598 Mi, agent Datadog 302 à 354 Mi, `redis-master` 340 Mi |

INFERENCE : quand la mémoire disponible devient trop faible, le noyau vide le cache des fichiers. Les processus relisent alors leurs binaires et les bases leurs fichiers de données sur le disque. Les requêtes attendent l'entrée-sortie sans consommer de CPU, dépassent 2 s, et la gateway renvoie des 504. Des pods qui ne lisent jamais rien (Traefik, coredns) qui lisent des dizaines de Mo/s, c'est la marque de ce phénomène.

Ce qui reste **non déterminé** :
- pourquoi la mémoire a basculé depuis midi. Plusieurs causes s'additionnent : un 6e pod de gateway depuis 12:53, Traefik qui gonfle sous la charge, les caches remplis, et peut-être le ballon Proxmox (VM 101 : 16 Go configurés, ballon à 12 Go d'après la note de capacité du 2026-11-07) qui a repris de la mémoire. Ce dernier point demande un accès à l'hôte `pve` ;
- l'effet du cache du total sur `ms-event-db` : la VM relisait son disque avant que la base ne soit chargée.

Faits annexes, sans lien établi avec l'effondrement : la tâche `ms-storage-purge` tourne toutes les 15 minutes (`*/15`, de 13:45:01 à 13:45:34 ce jour-là) et fait lire minio ; `yarn load` reconnecte les 200 acteurs (200 lignes `Login attempt` à la gateway) juste avant chaque palier.

## 6. Limites

| Limite | Conséquence |
| :--- | :--- |
| Pas d'accès à `pve` | Mémoire réelle de la VM, ballon et fréquence de l'hôte non relevés |
| Relevés de CPU par pod espacés de 12 à 45 s pendant les effondrements | Les pods en attente d'entrée-sortie n'apparaissent pas forcément dans le relevé |
| `kubectl logs -l` ne renvoie que 10 lignes par pod sans `--tail=-1` | Une première lecture des journaux des `ms-*` était vide à tort ; corrigée avec `--tail=-1` |

## 7. Prochaines étapes

| Ordre | Quoi | Où | Pourquoi |
| :--- | :--- | :--- | :--- |
| 1 | Mémoire de la VM : relever `qm config 101` et `free -m` sur `pve`, puis donner à la VM au moins 14 à 16 Go fixes si l'hôte a de la marge | Proxmox (Victor) | Cause la plus directe |
| 2 | Limite mémoire de Traefik, et comprendre pourquoi il passe de 134 à 598 Mi | `deploy` | Plus forte hausse observée |
| 3 | Gateway : revenir à 5 pods minimum tant que la mémoire n'est pas réglée | `deploy` | 150 à 300 Mi rendus |
| 4 | Refaire la mesure : montée douce (100, 150, 200, puis 250, 275, 300), hors des minutes de purge (:00, :15, :30, :45), avec la boucle de fréquence sur `pve` et un relevé de la mémoire disponible | Victor et agent | Mesurer enfin le cache du total |
| 5 | Vague 2, suite : jeton interne réutilisé, une requête Cypher pour les exclusions, une requête SQL par page dans ms-post | `npm-packages` (règle du STOP) | Marge CPU |
| 6 | Remonter le cache borné et le rapporteur de stats (copiés entre ms-post et ms-event) dans un paquet partagé | `npm-packages` | Duplication |

Une seconde machine reste la voie vers 1 000 req/s ; ce chapitre montre qu'elle soulagerait aussi la mémoire, pas seulement le CPU.
