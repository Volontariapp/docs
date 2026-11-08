# 01 - Mesures et méthode

Tous les chiffres viennent des rampes de charge du soir du 2026-11-08 (heures en UTC, sauf mention). Chaque ligne indique si elle est un **FAIT** (sortie d'outil ou ligne de code citée), une **INFERENCE** ou un **NON VERIFIE**.

## 1. La machine

| Élément | Valeur | Source |
| :--- | :--- | :--- |
| Hôte physique | Proxmox sur un Intel Core i7-1360P, 16 threads, 31,8 Go de RAM | FAIT : `lscpu` et `free -m` de l'hôte |
| VM de production | `ubuntu-worker-2` (VM 101), **14 vCPU** depuis 21:25Z (12 avant) | FAIT : `qm config`, `kubectl get node` |
| RAM vue par Kubernetes | 12,4 Go depuis le redémarrage de la VM, contre environ 15,6 Go avant (16 Go alloués dans Proxmox) | FAIT : `kubectl get node` ; la cause (ballooning) est NON VERIFIE |
| Autres VM de l'hôte | `ubuntu-server` 4 vCPU à 5 % d'usage, VM 103 4 vCPU à 0,5 %, VM 104 arrêtée, conteneur pihole | FAIT : `pvesh get /cluster/resources` (instantané) |
| Cluster | k3s, **un seul nœud**, namespace `prod` ; les bases sont en `local-path`, épinglées au nœud | FAIT : `kubectl`, skill `volontariapp-deploy-gitops` |
| Gateway | Node 24 (`node:24-alpine`), Express, de 3 à 6 pods (HPA), limite 2 CPU et 256Mi par pod | FAIT : `Dockerfile`, `deployment.yaml`, `hpa.yaml` |
| HPA de la gateway | cible 500m de CPU moyen par pod, **ajoute jusqu'à 2 pods par minute sans délai de stabilisation**, retire 1 pod toutes les 2 minutes après 5 minutes de calme | FAIT : `deploy/apps/base/api-gateway/hpa.yaml` |
| Services métiers | `ms-social` 2 réplicas (512Mi), `ms-event` 2, `ms-post` 2, `ms-user` 1 | FAIT : `kubectl get deploy` |

**Conséquence matérielle à garder en tête.** Les 14 vCPU de la VM occupent presque tous les 16 threads de l'hôte. On ne peut pas donner plus de CPU à cette VM : au-delà, il faut une autre machine ou moins de CPU par requête.

## 2. La méthode

- **Outil** : `yarn load` (dépôt `traffic-simulator`), en lecture seule, lancé depuis le Mac de Victor vers la gateway publique (jeton Cloudflare Access). Paliers de 75 à 100 secondes (10 s de chauffe, puis fenêtres de 10 s). 200 acteurs déterministes. Arrêt automatique après deux fenêtres consécutives à plus de 5 % d'erreurs ou à plus de 2 s de p95.
- **Mélange de requêtes** : `events-list-app` 40 %, `posts-list` 30 %, `me` 20 %, `is-following` 10 %. La route `events-list-app` envoie les quatre filtres que l'application mobile envoie réellement (`excludeBlockedUsers`, `excludeParticipatedByMe`, `excludeCreatedByMe`, `excludeWishedByMe`), qui déclenchent des lectures dans `ms-social`. Le mélange d'origine (sans filtres) sous-estimait le coût de cette route.
- **Enregistreurs** : histogramme de latence de Traefik (seule mesure de latence côté cluster), `kubectl top` des 30 pods les plus gourmands toutes les 5 s (résolution réelle d'environ 12 s), lectures disque par pod, et pression E/S de la VM (PSI).
- **Contexte** : des utilisateurs réels étaient connectés pendant les mesures.

## 3. Résultats : la montée en charge

Mélange de l'application, VM de 14 vCPU, `ms-social` à 2 réplicas, exclusions lues en un seul appel. Heures de début de palier entre parenthèses.

| Palier | p50 | p95 | Erreurs | Nœud (vCPU) | Remarque |
| ---: | ---: | ---: | ---: | ---: | :--- |
| 25 (22:28) | 47 à 53 ms | 63 à 75 ms | 0 % | non relevé | lancé 2 minutes après le déploiement de la gateway |
| 50 (22:31) | 46 à 48 ms | 61 à 67 ms | 0 % | 2,0 | |
| 75 (22:35) | 46 à 47 ms | 63 à 78 ms | 0 % | 2,7 | |
| 100 (22:38) | 48 ms | 68 ms | 0 % | 3,3 | rejoué à 23:31 : p50 49 ms, p95 107 ms |
| 150 (22:40) | 55 ms | 167 ms | 0 % | 5,9 | un à-coup d'une seconde (992 ms) à 22:41:12Z |
| 200 (22:43) | 171 ms | 1 316 ms | 0 % | 10,5 à 11,4 | p99 2 219 ms ; l'HPA a ajouté 2 pods de gateway en cours de palier |
| 250 (22:47) | 10 000 ms | 10 002 ms | 51,7 % | 12,0 | arrêt après 30 s ; un 6e pod de gateway est créé au début du palier |

FAIT pour tout ce tableau : sorties de `yarn load`, `cpu.log` et `traefik.log` des enregistreurs.

**Coût marginal de CPU du nœud** : environ 29m par req/s jusqu'à 100 req/s, environ 52m par req/s de plus au-delà de 150 req/s. Le repos du nœud est à 0,45 vCPU.

## 4. Résultats : le palier à 150 req/s rejoué trois fois (instable)

À 22:40 ce palier avait tenu. Rejoué plus tard, il s'est dégradé à chaque fois, toujours à partir de la troisième fenêtre (environ 30 s après le début du palier) :

| Début (UTC) | p95 par fenêtre (ms) | Résultat | Pods créés par l'HPA | CPU du nœud pour 150 req/s |
| :--- | :--- | :--- | :--- | :--- |
| 22:40:13 | 110, 142, 144, 141, 992, 146, 120, 122, 106 | tient | aucun | 5,9 vCPU (42 %) |
| 23:23:45 | 203, 203, 499, 2 499, 4 465 | arrêt | 23:24:26, un pod | non enregistré |
| 23:33:22 | 361, 266, 1 142, 6 734, 5 212 | arrêt | 23:33:57, **deux pods** | 7,4 à 9,3 vCPU (52 à 66 %) |
| 23:38:55 | 193, 184, 654, 814, 415, 2 077, 2 078 | arrêt | 23:39:57, un pod ; l'HPA avait retiré un pod vers 23:38:40 | 6,0 à 8,5 vCPU (42 à 60 %) |

FAIT : sorties de `yarn load`, `kubectl describe hpa`, dates de création des pods (`kubectl get pods -o jsonpath`), `cpu.log`. Ces trois derniers paliers n'ont pas été enregistrés côté PSI de la VM (l'enregistreur avait été perdu au redémarrage de la VM de 21:25Z).

**Ce que ce tableau montre sans l'expliquer** : pour le même débit de 150 req/s, le nœud a consommé de 2 % à 58 % de CPU de plus à partir de 23:33 qu'à 22:41. Le chapitre 02 discute les explications possibles.

## 5. Déjà livré dans ce chantier

| Livraison | Effet | Dépôt et PR |
| :--- | :--- | :--- |
| Index et purge des tables d'outbox | Fin des lectures disque continues qui gelaient la VM | `npm-packages#310`, migrations dans 9 dépôts |
| Comptage SQL de `posts-list` sans jointure | Moins de CPU dans `ms-post-db` | `npm-packages#309` |
| Le worker de ranking n'analyse plus tout le graphe par utilisateur | Fin de la saturation de Neo4j | `workers-runners#62` |
| Appel unique `GetSearchExclusions` | Un appel `ms-social` au lieu de cinq lectures paginées par requête de l'application ; `ms-social` n'est plus tué par manque de mémoire | `proto-registry#43`, `npm-packages#311` et `#312`, `ms-social#69`, `api-gateway#115` |
| `ms-social` : 512Mi et 2 réplicas | Marge mémoire (il consommait 123Mi au repos sur 256Mi) | `deploy#67` |
| Route de rampe `events-list-app` | Mesure fidèle à l'application | `traffic-simulator#10` |

Avant ces correctifs, la limite se situait entre 100 et 125 req/s (mélange sans filtres, VM de 12 vCPU) et `ms-social` mourait de mémoire 17 secondes après le début d'un palier à 100 req/s avec la route de l'application.

## 6. Limites de ces mesures

| Limite | Conséquence |
| :--- | :--- |
| 200 acteurs qui répètent les mêmes pages (1 à 3) | Tout gain mesuré sur un cache est une borne haute ; le trafic réel est plus varié |
| Une seule machine, à l'heure du soir | Les chiffres ne disent rien d'une autre heure, d'une autre température ou d'une autre charge de l'hôte |
| Utilisateurs réels pendant les tests | Les paliers hauts les gênent, et leur activité s'ajoute au bruit |
| `kubectl top` à résolution d'environ 12 s | Les pics de moins de 12 s ne se voient pas dans le CPU par pod |
| L'HPA agit pendant les paliers | Les paliers à 200, 250 et les trois rejoués à 150 sont confondus avec des créations de pods |
| Pas d'enregistrement PSI pour les incidents | On ne peut pas dire si la VM a gelé ou saturé pendant ces incidents |
| Profil CPU d'un seul pod et d'une seule fenêtre de 30 s | Les parts du chapitre 02 peuvent différer en régime stable |
