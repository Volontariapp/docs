# Structure du Monorepo (NPM Packages)

L'architecture microservices de Volontariapp pose un défi majeur : comment partager du code métier (ex: le typage d'un Événement, la logique de validation, les algorithmes de filtrage) entre le `ms-event`, l'`outbox-event` et le `post-processor-event` sans dupliquer ce code dans 3 dépôts différents ?

La solution retenue est le **Monorepo central** hébergé dans le dépôt [**npm-packages**](https://github.com/Volontariapp/npm-packages).

## La Mutualisation par "Domaine"

Dans le diagramme de l'Image 4, le composant `DOMAIN_NPM` est classé dans la zone **PARTAGER (Shared)** de l'infrastructure. 
Il contient des packages métier (ex: `@volontariapp/domain-event`) qui encapsulent toute l'intelligence fonctionnelle.

### Qu'est-ce qu'un "Domain Package" ?
Un package de domaine (ex: `packages/domain-event`) n'est pas un serveur, il ne tourne pas. C'est une bibliothèque pure (Node.js/TypeScript) qui définit :
- Les **Entités** (ex: la classe `Event`).
- Les **Value Objects** (ex: `EventId`, `Location`).
- Les **Services Métier** (Logique métier pure, ex: `CalculateEventDistanceService`).
- Les **Repositories Abstraits** (Interfaces, implémentées ensuite par TypeORM dans les runners).

### Comment est-il consommé ?
Le Microservice (API) et les Runners (Outbox, Workers, Post-Processors) d'un même domaine installent ce package comme une simple dépendance via `yarn` (ex: `yarn add @volontariapp/domain-event`).

**Avantages :**
- **DRY (Don't Repeat Yourself)** : La logique de validation d'un champ ou de calcul n'est écrite qu'une seule fois.
- **Cohérence** : Les Workers d'arrière-plan utilisent rigoureusement les mêmes structures de données que le Microservice API. Si un champ est ajouté à une entité, TypeScript garantit que toutes les briques de la chaîne asynchrone s'alignent.

## Structure du Dépôt `npm-packages`

Ce dépôt contient également tous les utilitaires transverses du framework de Volontariapp :

```text
npm-packages/
├── packages/
│   ├── auth/              # Logique d'authentification (Tokens, Hachage)
│   ├── bridge/            # Couche d'accès DB optimisée
│   ├── config/            # Système de configuration centralisé (Env vars)
│   ├── contracts/         # Typages partagés et définitions de files BullMQ
│   ├── database/          # Utilitaires PostgreSQL / Neo4j
│   ├── domain-event/      # Intelligence fonctionnelle du domaine Event
│   ├── domain-social/     # Intelligence fonctionnelle du domaine Social
│   ├── domain-user/       # Intelligence fonctionnelle du domaine User
│   ├── errors/            # Registre centralisé des erreurs (Codes HTTP/gRPC)
│   ├── logger/            # Wrapper Winston pour la centralisation des logs
│   ├── messaging/         # Classes pour BullMQ / Redis Streams
│   ├── outbox/            # Le cœur du pattern Transactional Outbox (Polling, Retry)
│   ├── post-processors/   # Mécanismes de Circuit Breaker et DLQ
│   ├── shared/            # Utilitaires globaux (Dates, Arrays, Utils)
│   └── workers/           # Classes de base pour les Background Jobs (Audit)
└── ci-tools/              # Sous-module Git pour le outillage CI/CD et l'infra locale
```

## Couplage Modéré (Trade-off)

- En théorie puriste des Microservices, le partage de code est parfois déconseillé (principe du "Shared Nothing") pour éviter qu'une modification d'une librairie ne casse tous les services.
- **Le Compromis Volontariapp** : Le code partagé est limité à l'intérieur de **frontières bien définies**. Le `ms-user` n'utilise pas le `@volontariapp/domain-event`. Le partage s'effectue verticalement (API -> Worker -> Post-Processor d'un même domaine) plutôt qu'horizontalement. Quant aux librairies techniques (`@volontariapp/outbox`), elles s'apparentent à un framework interne d'entreprise, versionné et testé rigoureusement.
