# 17 - Format des tickets Notion (constat du 2026-10-18)

Relevé en **lecture seule** via l'API Notion (jeton `NOTION_TOKEN` dans `docs/.env`, ignoré par git). Aucun ticket n'a été créé ni modifié. Ce fichier sert de gabarit pour transformer [14](14-plan-d-implementation.md) en tickets.

## 1. Où sont les tickets

| Base Notion | Contenu |
| :--- | :--- |
| **Backlogs** (`2fd37561-a847-80a1-8c79-cebcaa8100b7`) | 531 tickets (385 `done`, 87 `todo`). C'est la base à utiliser |
| BIBLE (`2fd37561-a847-807f-aff3-e7a3e0d57b23`) | documentation, procédures, notes, POC |
| ROADMAP AGILE (`30437561-a847-8012-a07f-f9ac94edb24f`) | jalons (date, lead, assign, bloque / bloqué par) |

Les 71 tickets de l'EPIC `stockage de fichier` forment le modèle à suivre : c'est le seul ensemble entièrement structuré. Les autres EPIC (`Datadog` 58, `Event` 7, `Post`, `Badges`, `Team`) et les 392 tickets sans EPIC sont plus libres.

## 2. Titre et numérotation

Format : `<phase>.<n> <Catégorie> - <Sujet> : <détail>`.

Exemples : `4.5 Workers - worker-storage : handler storage.scan_file`, `2.8 Protos - Merge et publication des contrats storage (STOP)`, `5.4 Back - ms-post : création avec images`.

Catégories observées : `Back`, `Front`, `Gateway`, `NPM`, `Protos`, `Contracts`, `Infra`, `Infra Kube`, `CI/CD & Infra`, `Tooling`, `Satellites`, `Workers`, `Websockets`, `E2E`, `Integration`.

Les phases de l'EPIC de référence suivent l'ordre de dépendance :

| Phase | Contenu |
| :--- | :--- |
| 0 | Prérequis (démarrage, config, outillage) |
| 1 | Paquets `npm-packages` et infrastructure de base |
| 2 | Protos, avec un ticket explicite **`Merge et publication (STOP)`** qui bloque tout le reste |
| 3 | Back : gRPC des microservices |
| 4 | Satellites : post-processors, workers, `ws-service` |
| 5 | Gateway et Front |
| 6 | E2E et intégration |

## 3. Propriétés

| Propriété | Type | Convention |
| :--- | :--- | :--- |
| `Nom` | titre | voir section 2 |
| `EPIC` | select | `stockage de fichier`, `Datadog`, `Event`, `Badges`, `Post`, `Team`. **Il n'existe pas d'option `ranking`** : à créer |
| `État` | status | `to define`, `todo`, `in progress`, `to review`, `done`, `cancelled` ; un nouveau ticket est `todo` |
| `Priority` | select | `P0` à `P3` ; P0 = chemin critique, P1 = utile, P2 = post-MVP |
| `Ressources` | multi-select | étiquettes techniques : `Backend`, `FrontEnd`, `GRPC`, `NPM-PACKAGE`, `Infra`, `Kubernetes`, `Workers`, `Post-Processors`, `Events`, `Outbox`, `Redis`, `Websockets`, `S3`, `Postgres`, `SQL`, `Testing`, `CI/CD`, `Tooling`, `Docker`, `Documentation` |
| `Personne` | multi-select | `Victor A`, `Victor G`, `Clement`, `Damien` |
| `Charge` et `Delais` | texte | durée estimée, même valeur dans les deux : `30min`, `45min`, `1h`, `1h15`, `1h30`, `2h`, `2h30`. **Plancher : 30 min** ; plafond usuel : 3 h |
| `Difficulté` | texte | `Facile`, `Moyenne`, `Difficile` |
| `Sprint` | select | `Sprint N - <Personne> Assign` |
| `Weekly` | multi-select | `S<sprint> - W<semaine>` ; un sprint = 3 semaines du mardi au lundi (S8 : 6 au 26 octobre 2026, S9 : 27 octobre au 16 novembre, S10 : 17 novembre au 7 décembre) |
| `Date` | date | date de livraison prévue |
| `Description` | texte | une phrase : l'objectif du ticket |
| `Bloqué par` / `Bloque` | relations (vers Backlogs) | arêtes de dépendance, remplies des deux côtés |
| `Lien PR(s)` | url | rempli à la livraison |

## 4. Corps d'un ticket

Gabarit constant, dans cet ordre :

```text
> Contexte & Objectif : <la phrase de Description>
## Définition du problème
   <ce qui manque ou ne marche pas aujourd'hui>
## Description de la tâche
   <ce qu'il faut faire, précis>
## Aide
   - <piège, conseil, modèle à copier>
## Références dans la codebase
   - <chemin:ligne ou document>
## Étapes pour la réalisation
   [ ] 1. <étape>
   [ ] 2. <étape>
## Definitions of done
   [ ] La PR est liée au ticket
   [ ] Une documentation est rattachée au ticket
   [ ] Quelqu'un a approuvé le changement
   [ ] <critère propre au ticket>
## Dépendances et estimation
   - Bloqué par : <numéros>
   - Bloque : <numéros>
   - Estimation : 1h30 (échelle efficace, plancher 30 min). Responsable : <personne>. Livraison prévue le <date> (Sprint N, semaine M).
### Resultat (<date>)        <- ajouté à la livraison : versions publiées, pièges découverts
```

Les trois premières cases de « Definitions of done » sont fixes ; la suite reprend le « Fait quand » de [14](14-plan-d-implementation.md).

## 5. Conversion de [14](14-plan-d-implementation.md) en tickets

1. **Regrouper par PR (décision du 2026-10-18).** Un découpage fin en 50 à 70 tickets a été jugé excessif : on crée **16 tickets condensés, un par lot de travail d'une PR, de 3 h au plus**, listés en [18](18-tickets-par-pr.md). Les lignes suivantes décrivent l'ancienne piste de découpage fin, conservée pour mémoire. (Ancienne formulation : les lignes `RK-xx` sont trop grosses pour ce format, ticket usuel de 30 min à 2 h 30.) Exemples : RK-07 (`domain-ranking`) devient plusieurs tickets (entités et migrations, repositories, score des événements, popularité, score des posts, codes d'explication, curseur et `PASS`, seaux de débit, chiffrement de la position) ; RK-15 (`worker-ranking`) un ticket par handler et par client ; RK-19 (application) un ticket par changement N1 à N9 de [15](15-nativapp.md). Ordre de grandeur : **50 à 70 tickets**, comme l'EPIC de stockage (71).
2. **Numéroter par phase** comme en section 2 : phase 0 `sync-migrations.sh` (RK-18c) ; phase 1 RK-04 à RK-09 et manifestes (RK-18a) ; phase 2 RK-01 à RK-03 et un ticket **`Merge et publication (STOP)`** ; phase 3 RK-10 à RK-12b ; phase 4 RK-13 à RK-16 ; phase 5 RK-17 et RK-19 ; phase 6 RK-20 à RK-23.
3. **Créer l'option d'EPIC `ranking`** dans la base Backlogs.
4. **Relations** : traduire les dépendances de [14](14-plan-d-implementation.md) en `Bloqué par` et `Bloque` (le STOP bloque toutes les phases suivantes).
5. **À décider avec l'équipe** : `Personne`, `Sprint`, `Weekly` et `Date` (non déduits de la documentation). La séparation observée : Clement prend surtout l'infrastructure et les satellites, Victor A les paquets, protos, backend et front.
6. **Gabarit réutilisable** : chaque ticket reprend la section 4 ; le champ « Références dans la codebase » cite les chemins de la documentation (`docs/matching/NN-...md`) et du code.

## 6. Exemple rendu

`1.1 NPM - shared : streams du domaine ranking`

| Propriété | Valeur |
| :--- | :--- |
| EPIC | `ranking` (à créer) |
| État / Priority | `todo` / P0 |
| Ressources | `NPM-PACKAGE`, `Redis` |
| Charge / Delais / Difficulté | `45min` / `45min` / Facile |
| Description | Déclarer les streams du domaine ranking et celui de la purge de compte. |
| Bloqué par | `2.4 Protos - Merge et publication des contrats ranking (STOP)` |

Corps : problème (les streams `ranking:job:outbox:success`, `:failure` et `user:deleted:ranking` n'existent pas dans `Streams`) ; tâche (ajouter les trois valeurs et les inclure dans l'union de types) ; références (`npm-packages/packages/shared/src/enums/streams.enum.ts`, [04](04-flux-asynchrone.md) section 3, [13](13-decisions-v1.md) section 7) ; étapes (1. ajouter les valeurs ; 2. build et tests ; 3. changeset) ; critère propre (test de l'enum vert).
