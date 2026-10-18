# 18 - Tickets Notion : un lot de travail par PR

Décision du 2026-10-18 : au lieu de 50 à 70 petits tickets, **17 tickets condensés, un par lot de travail d'une PR**, de 3 h au plus chacun, avec plusieurs tâches cochables. Une PR peut contenir plusieurs tickets (c'est le cas des paquets `npm-packages`). Source : [14](14-plan-d-implementation.md) ; gabarit : [17](17-format-des-tickets-notion.md).

## 1. Réglages communs

| Champ | Valeur |
| :--- | :--- |
| EPIC | `MS Ranking` (option créée dans la base Backlogs le 2026-10-18) |
| Personne | `Victor A` |
| Sprint | `Sprint 8 - Victor A Assign` |
| État | `todo` |
| Weekly | `S8 - W2` pour le 19 octobre, `S8 - W3` du 20 au 26 octobre |
| Dates | du 19 au 26 octobre 2026 (dernier jour du sprint 8), dans l'ordre des dépendances |
| Charge et Delais | identiques, 3 h au plus |

Total : **17 tickets, environ 47.5 h**. Les dates tiennent dans la semaine demandée mais ne sont pas réalistes pour une personne seule (plusieurs tickets le même jour) : elles s'ajustent sans toucher aux dépendances.

**Cycles de STOP : 2 seulement.** Un pour `proto-registry` (ticket 2.1) et un pour `npm-packages` (tickets 1.1 à 1.3 sur une seule branche et un seul changeset). Aucun autre dépôt ne passe par un STOP.

## 2. Vue d'ensemble

| N° | Ticket | PR | Charge | Date | Bloqué par |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 0.0 | CI/CD & Infra - Setup du dépôt ms-ranking : GitHub, CI, base PostgreSQL de test et hooks | Création du dépôt Volontariapp/ms-ranking, puis PR dans ci-tools (base de test) et dans deploy (sous-module) | 2h30 | 10-19 | aucun |
| 2.1 | Protos - ranking, AdminGetRecommendedEventIds et lectures ms-post (STOP) | proto-registry (une seule PR), puis la PR automatique de régénération dans npm-packages | 3h | 10-19 | aucun |
| 1.1 | NPM - shared, messaging, domain-user, domain-post et contracts web : socle du ranking | npm-packages (une seule branche et un seul changeset pour 1.1, 1.2 et 1.3) | 3h | 10-20 | 2.1 |
| 1.4 | Infra Kube - manifests ms-ranking, secrets scellés et racine meta | deploy et racine meta (sync-migrations.sh, e2e-matrix, workspace) | 3h | 10-20 | 0.0 |
| 1.2 | NPM - domain-ranking : modèles, repositories, seaux de débit et chiffrement | npm-packages (même branche que 1.1) | 3h | 10-21 | 1.1 |
| 1.3 | NPM - domain-ranking : services de score, popularité, codes d'explication et curseur (STOP) | npm-packages (même branche que 1.1 ; fin de la PR, puis changeset et STOP) | 3h | 10-21 | 1.2 |
| 3.1 | Back - ms-social et ms-post : lectures pour le ranking | ms-social et ms-post (une PR chacun) | 2h30 | 10-22 | 1.3 |
| 3.2 | Back - ms-ranking : socle, lecture et commandes gRPC | ms-ranking (nouveau dépôt) | 3h | 10-22 | 1.3, 0.0 |
| 4.1 | Satellites - outbox-ranking et post-processor-ranking : déclencheurs et purge de compte | outbox-runners (outbox-ranking) et post-processors-runner (post-processor-ranking) | 3h | 10-23 | 1.3, 3.2 |
| 4.4 | Websockets - ws-service : gather de purge de compte et notification RANKING_READY | ws-service (code après la publication des paquets, déploiement en vague 2) | 1h30 | 10-23 | 4.1 |
| 4.2 | Workers - worker-ranking : calcul des événements et fan-out | workers-runners (worker-ranking) | 3h | 10-24 | 3.1, 3.2, 4.1 |
| 4.3 | Workers - worker-ranking : calcul du feed de posts | workers-runners (worker-ranking, même dépôt que 4.2) | 2h30 | 10-24 | 4.2 |
| 5.1 | Gateway - routes /ranking/* (événements, feed, rafraîchissement, position, PASS) | api-gateway | 3h | 10-25 | 3.2, 4.2 |
| 5.2 | Front - nativapp : swipe classé, position, retour PASS et rafraîchissement | nativapp | 3h | 10-25 | 5.1 |
| 5.3 | Front - nativapp : feed d'accueil classé et notification RANKING_READY | nativapp (même dépôt que 5.2) | 2h30 | 10-26 | 5.2, 4.3 |
| 6.1 | E2E - jeu d'essai, calibrage des poids et démonstration du ranking | ms-ranking et dépôts concernés (tests), documentation | 3h | 10-26 | 5.3, 4.3 |
| 6.2 | Workers - worker-ranking : adaptateur Jev derrière RankingScorer | workers-runners (worker-ranking) | 3h | 10-26 | 6.1 |

Ordre de dépendance : `0.0` -> `3.2` (et `1.4`) ; `2.1` -> `1.1` -> `1.2` -> `1.3` (publication npm-packages) -> `3.1` et `3.2` -> `4.1` -> `4.2` et `4.4` -> `4.3` -> `5.1` -> `5.2` -> `5.3` -> `6.1` -> `6.2`. Le ticket `0.0` (dépôt, CI, base de test) est le premier : il ne dépend de rien et bloque `3.2` et `1.4`. **Déploiement du gather en deux vagues** : `4.4` (`ws-service`) ne se déploie qu'après `4.1`.

## 3. Détail des tickets

### 0.0 CI/CD & Infra - Setup du dépôt ms-ranking : GitHub, CI, base PostgreSQL de test et hooks

- **PR** : Création du dépôt Volontariapp/ms-ranking, puis PR dans ci-tools (base de test) et dans deploy (sous-module)
- **Ressources** : CI/CD, Infra, Tooling, Postgres, Docker ; **Priority** : P0 ; **Difficulté** : Moyenne ; **Charge** : 2h30 ; **Date** : 2026-10-19
- **Bloqué par** : aucun
- **Objectif** : Créer le dépôt ms-ranking et le raccorder à la CI, à sa base PostgreSQL de test, aux sous-modules et aux hooks.
- **Tâches** :
  - 1. Créer le dépôt GitHub et protéger main
  - 2. Cloner dans le méta-dépôt et ajouter le sous-module ci-tools
  - 3. Ajouter ci.yml et e2e-matrix.json (modèle ms-storage)
  - 4. ci-tools : postgres-ranking et ms-ranking-migration dans le docker-compose
  - 5. deploy : sous-module submodules/ms-ranking
  - 6. Installer les hooks et vérifier l'accès aux secrets d'organisation
  - 7. Vérifier que les dépôts runners détectent les nouveaux dossiers
- **Critères propres** : Le workflow CI se déclenche et démarre postgres-ranking sur un push de ms-ranking ; Le sous-module apparaît dans deploy ; Les hooks de pré-commit sont installés

### 2.1 Protos - ranking, AdminGetRecommendedEventIds et lectures ms-post (STOP)

- **PR** : proto-registry (une seule PR), puis la PR automatique de régénération dans npm-packages
- **Ressources** : GRPC, Backend, CI/CD, NPM-PACKAGE ; **Priority** : P0 ; **Difficulté** : Moyenne ; **Charge** : 3h ; **Date** : 2026-10-19
- **Bloqué par** : aucun
- **Objectif** : Publier tous les contrats gRPC du ranking en une seule PR pour ne passer qu'une fois par le STOP.
- **Tâches** :
  - 1. Paquet ranking : enums, requêtes, commandes, réponses, services
  - 2. social : AdminGetRecommendedEventIds
  - 3. post : trois lectures
  - 4. buf lint et buf breaking --against main
  - 5. Merger (un commit proto par push)
  - 6. Suivre et faire merger la PR de régénération dans npm-packages
  - 7. Vérifier la version publiée de contracts-nest
- **Critères propres** : buf lint et buf breaking verts ; contracts et contracts-nest publiés avec les nouveaux types ; Version publiée notée dans le ticket

### 1.1 NPM - shared, messaging, domain-user, domain-post et contracts web : socle du ranking

- **PR** : npm-packages (une seule branche et un seul changeset pour 1.1, 1.2 et 1.3)
- **Ressources** : NPM-PACKAGE, Events, Redis, Postgres ; **Priority** : P0 ; **Difficulté** : Moyenne ; **Charge** : 3h ; **Date** : 2026-10-20
- **Bloqué par** : 2.1
- **Objectif** : Poser dans npm-packages les streams, les jobs, la purge de compte, les lectures de posts et les DTO web du ranking.
- **Tâches** :
  - 1. shared : streams
  - 2. messaging : jobs, événements de purge, mappings WebSocket
  - 3. domain-user : stream de purge et test d'intégration
  - 4. domain-post : trois lectures et tests
  - 5. contracts : DTO web du ranking
  - 6. Build et tests de chaque paquet
- **Critères propres** : Un test couvre getEventForJob pour les deux types de calcul ; Le test d'intégration de suppression de compte liste le nouveau stream ; Build vert de tous les paquets modifiés

### 1.4 Infra Kube - manifests ms-ranking, secrets scellés et racine meta

- **PR** : deploy et racine meta (sync-migrations.sh, e2e-matrix, workspace)
- **Ressources** : Infra, Kubernetes, Tooling, Postgres ; **Priority** : P1 ; **Difficulté** : Moyenne ; **Charge** : 3h ; **Date** : 2026-10-20
- **Bloqué par** : 0.0
- **Objectif** : Préparer le déploiement de ms-ranking : manifestes, base, secrets scellés et outillage de la racine.
- **Tâches** :
  - 1. Manifestes de base et overlays
  - 2. NetworkPolicies default-deny
  - 3. Application ArgoCD
  - 4. Secrets scellés (étape humaine)
  - 5. sync-migrations.sh, e2e-matrix, workspace, mesh-mcp
  - 6. Alertes et métriques
- **Critères propres** : kustomize build valide ; Aucun secret en clair dans Git ; sync-migrations.sh traite ranking

### 1.2 NPM - domain-ranking : modèles, repositories, seaux de débit et chiffrement

- **PR** : npm-packages (même branche que 1.1)
- **Ressources** : NPM-PACKAGE, Postgres, Backend ; **Priority** : P0 ; **Difficulté** : Difficile ; **Charge** : 3h ; **Date** : 2026-10-21
- **Bloqué par** : 1.1
- **Objectif** : Créer le paquet domain-ranking : tables, repositories, limiteur de débit et chiffrement de la position.
- **Tâches** :
  - 1. Scaffold du paquet
  - 2. Modèles et migrations
  - 3. Repositories
  - 4. Requête de demande (needs_job) et ses trois tests
  - 5. Seaux de débit et tests d'intégration
  - 6. Chiffrement de la position
- **Critères propres** : Une demande arrivée après started_at provoque un second calcul ; Six appels en rafale : le sixième est refusé ; La position chiffrée est liée au userId

### 1.3 NPM - domain-ranking : services de score, popularité, codes d'explication et curseur (STOP)

- **PR** : npm-packages (même branche que 1.1 ; fin de la PR, puis changeset et STOP)
- **Ressources** : NPM-PACKAGE, Backend, Testing ; **Priority** : P0 ; **Difficulté** : Difficile ; **Charge** : 3h ; **Date** : 2026-10-21
- **Bloqué par** : 1.2
- **Objectif** : Écrire les services purs de classement, testables sans infrastructure, puis publier la PR.
- **Tâches** :
  - 1. Score des événements et popularité
  - 2. Score des posts
  - 3. Codes d'explication
  - 4. Curseur et pénalités PASS
  - 5. Port RankingScorer et Noop
  - 6. Changeset, build, tests puis STOP
- **Critères propres** : Les cas limites de docs/matching/05 sont testés ; La version snapshot est publiée par la CI ; Version publiée notée dans le ticket

### 3.1 Back - ms-social et ms-post : lectures pour le ranking

- **PR** : ms-social et ms-post (une PR chacun)
- **Ressources** : Backend, GRPC, SQL, Testing ; **Priority** : P0 ; **Difficulté** : Moyenne ; **Charge** : 2h30 ; **Date** : 2026-10-22
- **Bloqué par** : 1.3
- **Objectif** : Exposer la recommandation admin de ms-social et les trois lectures du feed de ms-post.
- **Tâches** :
  - 1. yarn up des paquets publiés (les deux dépôts)
  - 2. ms-social : AdminGetRecommendedEventIds et tests
  - 3. ms-post : trois handlers et tests
  - 4. Migration de l'index sur posts
  - 5. analyze_grpc sur les quatre RPC
- **Critères propres** : Le plafond par auteur est testé ; Wire-format sans rupture ; L'index existe après migration

### 3.2 Back - ms-ranking : socle, lecture et commandes gRPC

- **PR** : ms-ranking (nouveau dépôt)
- **Ressources** : Backend, GRPC, Postgres, Testing ; **Priority** : P0 ; **Difficulté** : Difficile ; **Charge** : 3h ; **Date** : 2026-10-22
- **Bloqué par** : 1.3, 0.0
- **Objectif** : Créer le microservice ms-ranking : lecture des listes, rafraîchissement, position et retours PASS.
- **Tâches** :
  - 1. Dépôt, configuration, base et migrations
  - 2. GetRankingEvents et GetRankingFeed
  - 3. RequestRankingRefresh et seau
  - 4. UpdateUserLocation
  - 5. RecordEventFeedback
  - 6. Tests
- **Critères propres** : La lecture sans liste écrit le job puis lève le 206 ; Le sixième rafraîchissement d'une minute renvoie refreshThrottled ; Un lot de 51 PASS est refusé

### 4.1 Satellites - outbox-ranking et post-processor-ranking : déclencheurs et purge de compte

- **PR** : outbox-runners (outbox-ranking) et post-processors-runner (post-processor-ranking)
- **Ressources** : Outbox, Post-Processors, Events, Redis ; **Priority** : P0 ; **Difficulté** : Difficile ; **Charge** : 3h ; **Date** : 2026-10-23
- **Bloqué par** : 1.3, 3.2
- **Objectif** : Brancher les événements de la plateforme sur le ranking et purger les données d'un compte supprimé.
- **Tâches** :
  - 1. outbox-ranking
  - 2. Post-processors communs
  - 3. Déclencheurs événements et souhaits
  - 4. Déclencheurs posts
  - 5. Purge de compte et DLQ
  - 6. Tests d'idempotence et de purge par table
- **Critères propres** : Après user.deleted, plus aucune ligne du compte dans les tables ranking_* ; Rejouer un message ne double aucune ligne ; Un job PENDING passe COMPLETED et arrive dans BullMQ

### 4.4 Websockets - ws-service : gather de purge de compte et notification RANKING_READY

- **PR** : ws-service (code après la publication des paquets, déploiement en vague 2)
- **Ressources** : Websockets, Events, Redis ; **Priority** : P0 ; **Difficulté** : Moyenne ; **Charge** : 1h30 ; **Date** : 2026-10-23
- **Bloqué par** : 4.1
- **Objectif** : Faire attendre l'acquittement du ranking à la suppression de compte et notifier l'application.
- **Tâches** :
  - 1. Expects du gather
  - 2. Post-processors et options de feedback
  - 3. Notification RANKING_READY
  - 4. Tests
  - 5. Déploiement après post-processor-ranking
- **Critères propres** : Une suppression de compte de test réussit avec cinq acquittements ; RANKING_READY arrive à l'application

### 4.2 Workers - worker-ranking : calcul des événements et fan-out

- **PR** : workers-runners (worker-ranking)
- **Ressources** : Workers, Backend, GRPC, Redis ; **Priority** : P0 ; **Difficulté** : Difficile ; **Charge** : 3h ; **Date** : 2026-10-24
- **Bloqué par** : 3.1, 3.2, 4.1
- **Objectif** : Calculer et écrire la liste d'événements de chaque utilisateur, avec coalescence et fan-out.
- **Tâches** :
  - 1. Workers et configuration
  - 2. Clients gRPC et jeton interne
  - 3. ComputeUserRanking
  - 4. Écriture transactionnelle et job de suite
  - 5. FanoutRanking
  - 6. Tests de coalescence et de rejeu
- **Critères propres** : Un calcul de bout en bout écrit la liste ; Une demande arrivée pendant le calcul déclenche un second calcul ; source = STRUCTURAL_ONLY sans Jev

### 4.3 Workers - worker-ranking : calcul du feed de posts

- **PR** : workers-runners (worker-ranking, même dépôt que 4.2)
- **Ressources** : Workers, Backend, GRPC ; **Priority** : P0 ; **Difficulté** : Difficile ; **Charge** : 2h30 ; **Date** : 2026-10-24
- **Bloqué par** : 4.2
- **Objectif** : Calculer la liste de posts de chaque utilisateur à partir de ses abonnements, événements et interactions.
- **Tâches** :
  - 1. Classe de worker et file
  - 2. Ensemble d'auteurs et candidats
  - 3. Filtres et score
  - 4. Repli GLOBAL et COLD_START
  - 5. Fan-out de POST_CREATED
  - 6. Tests
- **Critères propres** : Un compte sans abonnement obtient COLD_START ; Les auteurs bloqués sont exclus ; Un post déjà liké est rétrogradé

### 5.1 Gateway - routes /ranking/* (événements, feed, rafraîchissement, position, PASS)

- **PR** : api-gateway
- **Ressources** : Backend, GRPC ; **Priority** : P0 ; **Difficulté** : Difficile ; **Charge** : 3h ; **Date** : 2026-10-25
- **Bloqué par** : 3.2, 4.2
- **Objectif** : Exposer le ranking à l'application et assembler listes classées et contenus.
- **Tâches** :
  - 1. Contrôleur et DTO web (contracts)
  - 2. Lecture événements
  - 3. Lecture feed et blocages
  - 4. Commandes : refresh, position, feedback
  - 5. 206 et plafonds
  - 6. Tests de routage
- **Critères propres** : Test de routage sans collision avec /events/:id ; Un auteur bloqué disparaît du feed sans recalcul ; Swagger à jour

### 5.2 Front - nativapp : swipe classé, position, retour PASS et rafraîchissement

- **PR** : nativapp
- **Ressources** : FrontEnd, Testing ; **Priority** : P0 ; **Difficulté** : Moyenne ; **Charge** : 3h ; **Date** : 2026-10-25
- **Bloqué par** : 5.1
- **Objectif** : Brancher l'écran de swipe sur le classement sans toucher à la carte.
- **Tâches** :
  - 1. Couche API et hooks
  - 2. Discrimination du 206
  - 3. Swipe : source, DRAFT, tampon PASS
  - 4. Position
  - 5. Rafraîchissement
  - 6. Tests
- **Critères propres** : useGetEvents inchangé ; Un swipe à gauche est envoyé en lot ; La permission de position refusée n'appelle rien

### 5.3 Front - nativapp : feed d'accueil classé et notification RANKING_READY

- **PR** : nativapp (même dépôt que 5.2)
- **Ressources** : FrontEnd, Websockets, Testing ; **Priority** : P1 ; **Difficulté** : Moyenne ; **Charge** : 2h30 ; **Date** : 2026-10-26
- **Bloqué par** : 5.2, 4.3
- **Objectif** : Afficher le feed classé à l'accueil et réagir à la fin d'un calcul sans casser la lecture.
- **Tâches** :
  - 1. use-ranking-feed et HomeScreen
  - 2. Repli sur useListPosts
  - 3. Handler RANKING_READY
  - 4. Codes d'explication (types seulement)
  - 5. Tests de non-régression
- **Critères propres** : Un compte neuf voit la liste normale puis la liste classée ; La carte fonctionne comme avant

### 6.1 E2E - jeu d'essai, calibrage des poids et démonstration du ranking

- **PR** : ms-ranking et dépôts concernés (tests), documentation
- **Ressources** : Testing, Backend, Documentation ; **Priority** : P1 ; **Difficulté** : Moyenne ; **Charge** : 3h ; **Date** : 2026-10-26
- **Bloqué par** : 5.3, 4.3
- **Objectif** : Valider que le classement respecte des étiquettes humaines et préparer la démonstration.
- **Tâches** :
  - 1. Données de test
  - 2. Jeu étiqueté et comparaison
  - 3. Ajustement des poids
  - 4. Scénario de démonstration
  - 5. Skills resynchronisées
- **Critères propres** : Le classement respecte les étiquettes ; FORMULA_VERSION incrémentée si les poids changent ; evolve.py plan ne liste plus rien

### 6.2 Workers - worker-ranking : adaptateur Jev derrière RankingScorer

- **PR** : workers-runners (worker-ranking)
- **Ressources** : Workers, Backend, Testing ; **Priority** : P1 ; **Difficulté** : Moyenne ; **Charge** : 3h ; **Date** : 2026-10-26
- **Bloqué par** : 6.1
- **Objectif** : Ajouter le scorer sémantique Jev, avec repli structurel si Jev est indisponible.
- **Tâches** :
  - 1. Client HTTP et configuration
  - 2. Résumé de goût et questions
  - 3. Erreurs, sous-lots, coupe-circuit
  - 4. Test des champs interdits
  - 5. Comparaison avec le structurel
- **Critères propres** : source = FULL quand Jev répond ; Repli structurel sur 401, 429 et 529 persistants ; Aucun champ interdit dans la requête

## 4. Création dans Notion

Chaque ticket est créé dans la base Backlogs avec le corps de [17](17-format-des-tickets-notion.md) section 4 (contexte, problème, tâche, aide, références, étapes à cocher, définitions de terminé, dépendances et estimation). **Statut : les 17 tickets ont été créés dans Notion le 2026-10-18** (EPIC `MS Ranking`, État `todo`), avec leurs relations `Bloqué par` et `Bloque` (relations doubles : renseigner un côté remplit l'autre). Le ticket `0.0` (setup du dépôt) a été ajouté après coup à la demande du Lead Dev. Toute modification ultérieure du plan se fait dans Notion et dans ce fichier.
