# Volontariapp - Documentation

Documentation officielle de l'architecture de Volontariapp et de ses fonctionnalités structurantes.

Elle est organisée en deux parties : l'**architecture** (modèle C4, à lire de haut en bas, du plus macro au plus micro) et les **dossiers de fonctionnalités** (une conception par sujet, avec son statut d'avancement). Pour savoir ce qui existe réellement dans le code, le code et les skills `volontariapp-*` du dépôt [`meta`](https://github.com/Volontariapp/meta) font foi.

## Organisation du dépôt

```text
docs/
├── README.md                # Cet index
├── architecture/            # Modèle C4 et structure du monorepo
├── matching/                # Classement personnalisé (ms-ranking)
├── stockage-fichiers/       # Upload S3, quarantaine, scan, rattachement (ms-storage)
├── badges/                  # Attribution automatique des 13 badges
├── suppression-compte/      # Règles d'événements lors d'une suppression de compte
├── post-processors/         # Notes de conception sur les consommateurs de Redis Streams
├── coaching/                # Rapports de suivi (Word) et pièces associées
├── scripts/                 # Outils de génération des rapports
└── ci-tools/                # Sous-module Git (CI partagée, docker-compose local)
```

## Architecture (modèle C4)

1. **[C1 - System Context](architecture/C1-System-Context.md)** : la vue d'ensemble du système, ses acteurs et ses systèmes externes (stockage objet, Jev).
2. **[C2 - Containers](architecture/C2-Containers.md)** : l'intérieur de la boîte. Les six domaines (`user`, `event`, `post`, `social`, `storage`, `ranking`), les exceptions (Neo4j, S3 et ClamAV, WebSocket), le périmètre partagé, les ports.
3. **[C3 - Async Patterns & Flows](architecture/C3-Async-Patterns-And-Flows.md)** : le cœur du réacteur. Transactional Outbox, cycle de vie des jobs, trigger SQL `job_audit`, Scatter-Gather du WebSocket, et les flux concrets construits dessus.
4. **[C4 - Deployment & Infrastructure](architecture/C4-Deployment-And-Infrastructure.md)** : la vision GitOps. Kubernetes (K3s), ArgoCD, Sealed Secrets, Network Policies, organisation du dépôt `deploy`.
5. **[Structure Monorepo & NPM](architecture/Monorepo-Structure.md)** : les packages `@volontariapp/*`, le partage vertical par domaine, le cycle de publication et la règle du STOP.

## Fonctionnalités

| Dossier | Sujet | Statut (2026-10-28) |
| :--- | :--- | :--- |
| [matching](matching/README.md) | Classement personnalisé des événements et des posts (`ms-ranking`, scoring structurel, Jev, repli 206) | Implémenté, sauf la partie `ws-service` (RK-16) |
| [stockage-fichiers](stockage-fichiers/README.md) | Upload direct S3, quarantaine, scan ClamAV, rattachement des images aux posts, événements et avatars | Flux principaux implémentés ; purge des orphelins non réalisée |
| [badges](badges/README.md) | Attribution asynchrone des 13 badges et notification temps réel | Implémenté |
| [suppression-compte](suppression-compte/README.md) | Sort des événements quand un organisateur ou un participant supprime son compte | Proposition de conception |
| [post-processors](post-processors/README.md) | Fan-out des streams `user.deleted`, DLQ | Décision ouverte |

## Écosystème des dépôts

Tous les services sont hébergés dans l'organisation GitHub **[Volontariapp](https://github.com/Volontariapp)**.

### Points d'entrée (Gateways et clients)
- [**nativapp**](https://github.com/Volontariapp/nativapp) : application mobile React Native (Expo).
- [**api-gateway**](https://github.com/Volontariapp/api-gateway) : point d'entrée HTTP/REST unique, authentification, génération du token interne, routage gRPC, proxy WebSocket.
- [**ws-service**](https://github.com/Volontariapp/ws-service) : microservice WebSocket (notifications temps réel, Scatter-Gather).

### Microservices métiers (synchrones, gRPC)
- [**ms-user**](https://github.com/Volontariapp/ms-user) : identité, profil, badges, score d'impact, suppression de compte.
- [**ms-event**](https://github.com/Volontariapp/ms-event) : missions et événements, cœur de métier.
- [**ms-post**](https://github.com/Volontariapp/ms-post) : fil d'actualités, posts, commentaires.
- [**ms-social**](https://github.com/Volontariapp/ms-social) : graphe social (Neo4j), abonnements, participations, recommandations.
- [**ms-storage**](https://github.com/Volontariapp/ms-storage) : fichiers (URL signées, métadonnées, rattachement), seul propriétaire des octets.
- [**ms-ranking**](https://github.com/Volontariapp/ms-ranking) : classement personnalisé des événements et des posts.

### Infrastructure asynchrone (Event-Driven)
- [**outbox-runners**](https://github.com/Volontariapp/outbox-runners) : daemons d'extraction transactionnelle PostgreSQL vers Redis, un par domaine.
- [**workers-runners**](https://github.com/Volontariapp/workers-runners) : flotte de traitement des tâches d'arrière-plan (BullMQ), un worker par domaine (scan de fichiers, calcul de classement, ...).
- [**post-processors-runner**](https://github.com/Volontariapp/post-processors-runner) : consommation des Redis Streams, clôture des Sagas, badges, rattachement de fichiers.

### Outillage et déploiement
- [**npm-packages**](https://github.com/Volontariapp/npm-packages) : monorepo des librairies partagées `@volontariapp/*` (domaines, contrats, messagerie, framework interne).
- [**proto-registry**](https://github.com/Volontariapp/proto-registry) : registre unique des contrats Protocol Buffers (SSOT gRPC).
- [**deploy**](https://github.com/Volontariapp/deploy) : source de vérité GitOps (Kubernetes, ArgoCD, sécurité de l'infrastructure).
- [**ci-tools**](https://github.com/Volontariapp/ci-tools) : workflows et actions GitHub Actions partagés, infrastructure locale docker-compose.
- [**changelog-checker**](https://github.com/Volontariapp/changelog-checker) : validation automatisée des versions et des changelogs.
- [**mcp-meta-indexer**](https://github.com/Volontariapp/mcp-meta-indexer) : serveur MCP Rust déployé sur le cluster pour l'indexation de la codebase.
- [**meta**](https://github.com/Volontariapp/meta) : méta-dépôt d'orchestration (onboarding, environnement local, skills des agents, `AGENTS.md`).
