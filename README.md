# Volontariapp — Documentation d'Architecture (Modèle C4)

Bienvenue dans la documentation officielle de l'architecture backend de Volontariapp.

Cette documentation a été pensée pour être lue **de haut en bas**, du plus macro (conceptuel) au plus micro (implémentation technique et flux asynchrones). Que vous soyez un nouvel arrivant (onboarding) ou un ingénieur sénior cherchant à comprendre le fonctionnement du Scatter-Gather, ces documents vous donneront toutes les clés.

Nous utilisons le formalisme d'inspiration **C4 Model** pour structurer cette connaissance.

## Navigation dans la documentation

1. **[C1 - System Context](C1-System-Context.md)** : La vue d'ensemble du système, ses acteurs (utilisateurs) et ses interactions macro.
2. **[C2 - Containers](C2-Containers.md)** : L'intérieur de la "boîte" Volontariapp. Découvrez la différence fondamentale entre les composants isolés (Microservices, Outbox) et partagés (Bases de données, Redis).
3. **[C3 - Async Patterns & Flows](C3-Async-Patterns-And-Flows.md)** : **(Crucial)** Le cœur du réacteur. Ce document explique en détail la chorégraphie asynchrone, le Transactional Outbox, le cycle de vie des Jobs, le SQL Trigger `job_audit`, et le pattern Scatter-Gather du WebSocket.
4. **[C4 - Deployment & Infrastructure](C4-Deployment-And-Infrastructure.md)** : La vision GitOps. Comment le code devient une infrastructure sécurisée (Kubernetes, ArgoCD, Sealed Secrets, Network Policies).
5. **[Structure Monorepo & NPM](Monorepo-Structure.md)** : Comment la logique métier est mutualisée via `@volontariapp/domain-*` sans enfreindre les règles d'isolation des microservices.

---

## Écosystème des Dépôts (Repositories)

Tous les services sont hébergés dans l'organisation GitHub **[Volontariapp](https://github.com/Volontariapp)**. Voici l'index complet pour accéder aux README techniques de chaque projet :

### Les Points d'Entrée (Gateways & Clients)
- [**nativapp**](https://github.com/Volontariapp/nativapp) : Application mobile React Native.
- [**api-gateway**](https://github.com/Volontariapp/api-gateway) : Point d'entrée HTTP, & REST, gestion de l'authentification.
- [**ws-service**](https://github.com/Volontariapp/ws-service) : Microservice externe pour le WebSockets (Pub/Sub, notifications temps réel).

### Les Microservices Métiers (Synchrones via gRPC)
- [**ms-user**](https://github.com/Volontariapp/ms-user) : Gestion de l'identité et du profil utilisateur.
- [**ms-event**](https://github.com/Volontariapp/ms-event) : Cœur de métier, gestion des missions et événements.
- [**ms-post**](https://github.com/Volontariapp/ms-post) : Gestion du fil d'actualités et du contenu.
- [**ms-social**](https://github.com/Volontariapp/ms-social) : Base de données orientée graphe (Neo4j) pour les abonnements et recommandations.

### L'Infrastructure Asynchrone (Event-Driven)
- [**outbox-runners**](https://github.com/Volontariapp/outbox-runners) : Daemons "Lean" garantissant l'extraction transactionnelle depuis PostgreSQL vers Redis.
- ️ [**workers-runners**](https://github.com/Volontariapp/workers-runners) : Flotte de traitement des tâches d'arrière-plan (BullMQ).
- [**post-processors-runner**](https://github.com/Volontariapp/post-processors-runner) : Flotte de consommation des Redis Streams pour la clôture des Sagas et la résilience.

### L'Outillage et le Déploiement
- ️ [**npm-packages**](https://github.com/Volontariapp/npm-packages) : Le Monorepo central contenant toutes les librairies partagées (`@volontariapp/*`), les contrats métiers, et les domaines.
- [**proto-registry**](https://github.com/Volontariapp/proto-registry) : Le registre unique des contrats Protocol Buffers (SSOT pour gRPC).
- [**deploy**](https://github.com/Volontariapp/deploy) : La source de vérité GitOps pour Kubernetes, ArgoCD et la sécurité de l'infrastructure.
