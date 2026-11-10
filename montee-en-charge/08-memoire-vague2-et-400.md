# 08 - Mémoire de la VM, vague 2, puis 400 req/s

Suite du [chapitre 07](07-ms-event-db-et-memoire.md), le 2026-11-09 de 16:30 à 21:30 (UTC). Chaque chiffre est un **FAIT** (sortie de `yarn load`, `qm`, API du kubelet, `record-ramp.sh`, journaux) sauf mention **INFERENCE**. Les relevés bruts sont dans `meta/profiles/ramp-vague2-deps/` (non versionnés).

## 1. Le résumé

1. **La mémoire de la VM était la cause des effondrements du chapitre 07.** Le ballon Proxmox reprenait la mémoire de la VM 101 jusqu'à 12 Go dès que l'hôte manquait de place. Plancher relevé à 14 Go à chaud ; mémoire disponible du nœud passée d'environ 2 Go à 6 Go.
2. **La vague 2 est livrée et déployée** : jeton interne réutilisé, une requête Cypher pour les exclusions, une requête SQL par page de posts et par `GetUser`.
3. **300 req/s tiennent largement** : 0 erreur, p95 166 ms, nœud à 35 % de CPU (contre 56 à 72 % au chapitre 07). `ms-event-db` passe de 799m à 217m.
4. **400 req/s tiennent aussi** : 0 erreur, p95 196 ms, nœud à 52 %.
5. **Mais ces chiffres ne valent que pour le mélange de 4 routes**, qui mesure les replis de l'application et pas ses écrans réels (section 6).
6. **Un défaut grave est apparu au passage** : après plusieurs heures sans trafic, la première rafale casse. Il a son propre chapitre, le [09](09-demarrage-a-froid.md).

## 2. La mémoire de la VM

### 2.1 Ce que montrait l'hôte (FAIT, `pve`, 20:00)

| Mesure | Valeur |
| :--- | :--- |
| Mémoire physique de l'hôte | 31 859 Mo, 6 286 Mo disponibles |
| VM 100 (`ubuntu-server`) et VM 103 | 8 Go chacune, sans ballon |
| VM 101 (`ubuntu-worker-2`, le nœud K3s) | `memory: 16384`, `balloon: 12288` |
| VM 104 | arrêtée |

Avec le ballon, la VM 101 voit entre 12 et 16 Go selon la pression sur l'hôte. Le pire cas (8 + 8 + 16 = 32 Go) dépasse la mémoire physique de l'hôte : c'est pour cela que le ballon avait été gardé le 2026-11-07.

### 2.2 Ce qui a été fait

| Heure | Action | Effet |
| :--- | :--- | :--- |
| 20:05 | `qm set 101 --balloon 14336` | appliqué à chaud : `balloon_min` = 15 032 385 536 octets (14 Gio), la VM ne descend plus sous 14 Go |
| 20:06 | `qm set 101 --memory 16384 --balloon 0` | en attente (`qm pending 101` : `cur balloon: 14336`, `new balloon: 0`) : 16 Go fixes **au prochain démarrage de la VM** |

Mémoire disponible du nœud, relevée par l'API du kubelet : environ 2 Go pendant les effondrements de l'après-midi, **6,1 à 6,5 Go** après le changement, **5,4 à 5,6 Go** pendant les rampes du soir. Défauts de page majeurs pendant les rampes : quasi nuls, contre environ 1 100 par seconde à 13:56.

**Risque restant** : au prochain démarrage de la VM, 16 Go fixes. Le pire cas sur l'hôte passe alors à 32 Go pour 31,8 Go physiques : l'hôte basculerait en swap (8 Go). À surveiller avec `free -m` sur `pve` pendant les rampes.

**Point de détail** : le kubelet affiche toujours une capacité de 11,8 Gi (`12379548Ki`), lue à son démarrage. L'ordonnanceur et les seuils d'éviction raisonnent donc sur 11,8 Gi jusqu'au prochain redémarrage de k3s.

### 2.3 Traefik

| | Avant | Après (deploy#74, puis deploy#75) |
| :--- | :--- | :--- |
| Requests | aucune | 100m, 128Mi |
| Limite mémoire | aucune | 768Mi |
| Limite CPU | aucune | aucune (volontaire : Traefik est sur chaque requête) |
| `GOMEMLIMIT` | aucun | 691MiB, calculé par la chart (90 % de la limite) |

Le `HelmChartConfig` `kube-system/traefik` vit dans `deploy/infrastructure/security/traefik/` et est synchronisé par l'application ArgoCD `cluster-security`. La valeur `GOMEMLIMIT=400MiB` écrite dans deploy#74 était ignorée (la chart impose la sienne) ; deploy#75 la retire. Traefik : 71 Mi au repos, 117 Mi au début des rampes, 390m de CPU à 400 req/s.

INFERENCE, non mesurée : le passage de 134 à 598 Mi de l'après-midi venait des requêtes en vol empilées derrière la deadline de 2 s pendant l'effondrement.

Constat annexe (FAIT) : le middleware `global-rate-limit` (100 requêtes par seconde par IP, `rate-limit.yaml`) existe mais n'est attaché à aucun ingress (`kubectl get ingress -A`, annotation `router.middlewares` vide sur `api-gateway-ingress` et `minio-ingress`).

## 3. La vague 2

| Paquet ou service | Version, PR | Changement |
| :--- | :--- | :--- |
| `@volontariapp/auth` | 3.4.0, npm-packages#317 | jeton interne réutilisé 30 s pour la même charge utile (jamais au-delà de son `exp` moins 60 s, ni de l'`exp` du jeton d'accès) ; jetons interne et d'accès vérifiés gardés 30 s par chaîne complète ; options `internalTokenReuseSeconds`, `verifiedTokenCacheSeconds`, `tokenCacheMaxEntries` (0 coupe) |
| `@volontariapp/domain-social` | 0.19.3 | `getSearchExclusions` : une requête (deux `CALL { }`, une ligne, deux listes) au lieu de deux requêtes dans deux sessions |
| `@volontariapp/domain-post` | 3.11.1 | `listPaginated` : page sans jointure (`OFFSET`/`LIMIT`), médias lus à part, seulement pour les posts dont `media_status` n'est pas `NONE` |
| `@volontariapp/domain-user` | 2.17.13 | `findById` : `find` sans `take`, une requête SQL au lieu de deux |
| Consommateurs | api-gateway#125 (`sha-b85d481`), ms-social#74 (`0af86a5`), ms-event#97 (`297babb`), ms-post#81 (`c4995a6`), ms-user#94 (`7be819c`) | montée de version seulement |

Tests à la livraison : `auth` 79 tests unitaires ; `domain-social` 195 unitaires et 128 d'intégration contre Neo4j 5.20 (même version que la prod, chart `5.20.0`) ; `domain-post` 57 et 54 ; `domain-user` 131 et 57.

Le levier 3 du chapitre 05 (cache des liens post vers événement dans ms-post) était **déjà en production** depuis ms-post#80 (`86c3ba5`) : un cache par pod, 30 s pour un post lié, 5 s pour un post sans lien, 5 000 entrées. Un sous-agent l'a établi en voulant l'implémenter.

## 4. Les rampes

Mélange : `events-list-app:40,posts-list:30,me:20,is-following:10`, paliers de 90 s, simulateur de fond à 0 réplica, gateway à 6 pods.

### 4.1 21:01 : arrêt dès 100 req/s

Première rampe après environ 4 h sans trafic : 71 % d'erreurs dans la première fenêtre (p50 2 033 ms), arrêt automatique en 30 s. `me` (ms-user seul) n'a aucune erreur ; les trois routes qui passent par ms-social échouent. Expliqué au [chapitre 09](09-demarrage-a-froid.md).

### 4.2 21:03 à 21:14 : de 100 à 300 req/s

| Palier | p50 | p95 | p99 | Erreurs |
| ---: | ---: | ---: | ---: | ---: |
| 100 | 44 ms | 124 ms | 141 ms | 0 % |
| 150 | 45 ms | 128 ms | 151 ms | 0 % |
| 200 | 46 ms | 131 ms | 157 ms | 0 % |
| 250 | 49 ms | 147 ms | 455 ms | 0 % |
| 275 | 50 ms | 146 ms | 186 ms | 0 % |
| 300 | 67 ms | 166 ms | 240 ms | 0 % |

Une fenêtre isolée à 692 ms de p95 au palier 250 (vers 21:10:20), sans cause visible côté ressources : mémoire stable, aucun défaut de page, nœud à 29-30 %. Non expliquée.

### 4.3 21:16 à 21:25 : de 300 à 400 req/s

| Palier | p50 | p95 | p99 | Erreurs |
| ---: | ---: | ---: | ---: | ---: |
| 300 | 54 ms | 153 ms | 202 ms | 0 % |
| 325 | 58 ms | 158 ms | 217 ms | 0 % |
| 350 | 63 ms | 179 ms | 333 ms | 0 % |
| 375 | 70 ms | 189 ms | 321 ms | 0 % |
| 400 | 76 ms | 196 ms | 324 ms | 0 % |

### 4.4 Ce qui travaille, et où est la marge

| Composant | À 300 req/s | À 400 req/s | Limite ou cible |
| :--- | ---: | ---: | ---: |
| Nœud | 4,8 à 5,0 vCPU (35 %) | 7,3 à 7,6 vCPU (52 %) | 14 vCPU |
| Gateway (6 pods) | environ 250m par pod | 390 à 414m par pod | cible HPA 500m, 7 pods max |
| `ms-event` (2 pods) | environ 300m | 455 à 463m | 1500m |
| `ms-social` (2 pods) | 216 à 248m | 345m | 800m |
| `ms-user` (1 pod) | 217m | 321m | 800m |
| Neo4j | 240 à 256m | 401m | 1000m (voir chapitre 09) |
| `ms-post-db` | 270 à 291m | 400m | 1500m |
| `ms-event-db` | 217 à 224m | 310m | 800m |
| Traefik | 265m | 390m | aucune |

- **`ms-event-db` : 217m à 300 req/s contre 707 à 799m au chapitre 07.** C'est le premier effet mesuré du cache du total de la recherche (ms-event#96). INFERENCE : la différence de débit n'explique pas un facteur 4.
- **Côté serveur, c'est rapide** : Traefik voit 99,1 % des requêtes du palier 300 et 95,1 % de celles du palier 400 sous 100 ms. La hausse du p50 vue par le client en fin de palier 300 (de 63 à 97 ms) n'apparaît pas dans le cluster : elle vient du chemin entre le Mac et Traefik (Cloudflare, réseau, Mac). INFERENCE.
- **Le premier mur au-delà de 400** serait la gateway (HPA plafonné à 7 pods), puis ms-social vers 800 à 900 req/s si la charge reste linéaire, ce qui n'est pas garanti. INFERENCE.

## 5. Ce qu'on ne peut pas départager

La vague 2, le cache du total de ms-event et la mémoire de la VM sont arrivés ensemble. On ne peut pas attribuer le gain à l'un d'eux en particulier, sauf la chute de `ms-event-db`, qui correspond exactement à ce que vise le cache du total.

## 6. La limite principale : la rampe ne mesure pas l'application

Lecture de `nativapp` sur `origin/main` (FAIT) :

- l'accueil lit `GET /ranking/feed` (`src/screens/main/hooks/use-home-screen.ts`, `useRankingFeed`) ; `GET /posts` n'est qu'un repli en cas de 206 ou d'échec ;
- le swipe lit `GET /ranking/events` (`use-swipe-screen.ts:59-63`) ; `GET /events` avec exclusions n'est qu'un repli.

Les « 400 req/s » ci-dessus ne sollicitent donc jamais `ms-ranking`, et ne contiennent aucune écriture. La refonte de la rampe est décrite au [chapitre 10](10-suites.md).

## 7. Limites de ces mesures

| Limite | Conséquence |
| :--- | :--- |
| Mélange de 4 routes en lecture seule | Les chiffres sont une borne haute pour l'application réelle |
| 200 acteurs qui relisent les mêmes pages | Les caches réussissent mieux qu'en trafic réel |
| Relevés de CPU à 12-15 s de résolution | Les pointes courtes n'apparaissent pas |
| Un seul passage par palier | Pas de confirmation à 15 minutes d'écart comme au chapitre 07 |
