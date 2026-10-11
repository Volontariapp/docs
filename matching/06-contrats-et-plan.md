# 06 - Contrats, plan et questions ouvertes

## Changements par dépôt

| # | Dépôt | Changement | Skill à ouvrir |
| :--- | :--- | :--- | :--- |
| 1 | `proto-registry` | RPC `GetMatchedEventIds`, messages et enum `MatchingSource` (additif) ; commande `RequestMatchingRefresh` | `volontariapp-proto-contract-evolution` |
| 2 | `npm-packages/messaging` | `SocialJobType.COMPUTE_EVENT_MATCHING` et `FANOUT_EVENT_MATCHING`, payloads, enregistrement dans `JobRegistry` | `volontariapp-implement-async-job-flow`, `volontariapp-shared-npm-package-change` |
| 3 | `npm-packages/domain-social` | port `MatchingScorer`, adaptateur Jev, service de calcul du score structurel ; (V2) émission d'événements pour participation et follow | `volontariapp-shared-npm-package-change` |
| 4 | `post-processors-runner/post-processor-social` | post-processors émetteurs de jobs pour les 4 déclencheurs V1 | `volontariapp-implement-async-event-flow` |
| 5 | `workers-runners/worker-social` | handlers de calcul et de fan-out, client gRPC vers `ms-event`, accès Redis (déjà présent) | `volontariapp-implement-async-job-flow` |
| 6 | `ms-social` | handler `GetMatchedEventIds`, accès Redis (nouveau), commande `RequestMatchingRefresh` | `volontariapp-grpc-microservice` |
| 7 | `api-gateway` | `GET /events/matching`, `POST /events/matching/refresh` | `volontariapp-api-gateway` |
| 8 | `deploy` | secret scellé de la clé Jev, variables Redis de `ms-social`, NetworkPolicy sortante vers l'API Jev pour `worker-social` | `volontariapp-deploy-gitops` |

## Ordre de livraison et règle du STOP

`AGENTS.md` section 1 impose deux arrêts. Les étapes ne sont **pas** parallélisables :

1. **`proto-registry`** (étape 1) : `buf lint` et `buf breaking`, puis STOP. La CI ouvre une PR dans `npm-packages` pour régénérer `contracts`. Attendre le merge et la publication.
2. **`npm-packages`** (étapes 2 et 3, regroupables en une seule branche) : `yarn build`, `yarn test`, `yarn changeset add`, `yarn changeset version`, puis STOP. Attendre la publication CI (version `snap` ou définitive).
3. Seulement ensuite, dans cet ordre : `worker-social` + `post-processor-social` (4, 5), `ms-social` (6), `api-gateway` (7), `deploy` (8). Mise à jour des dépendances par `yarn up`.

Le hook `.claude/hooks/stop-rule-guard.sh` verrouille mécaniquement les dépôts consommateurs après toute modification de `proto-registry` ou `npm-packages` ; le déverrouillage `release` appartient au Lead Dev uniquement.

## Tranches de livraison suggérées

| Tranche | Contenu | Résultat démontrable |
| :--- | :--- | :--- |
| T1 | Contrats (1 à 3) + `NoopMatchingScorer` + handlers (5) + lecture (6, 7), déclencheur `user:created` et `RequestMatchingRefresh` seulement | `GET /events/matching` renvoie une liste triée par score structurel, avec mode dégradé fonctionnel |
| T2 | Adaptateur Jev + garde-fous | classement hybride, `source = MATCHING`, scores affichés |
| T3 | Déclencheurs restants (wish, created, finished) | liste qui bouge quand l'utilisateur agit |
| T4 (V2) | Émission pour participation et follow dans `domain-social` | réactivité complète |

T1 est livrable et défendable sans accès à Jev.

## Tests

Respecter la section 3 de `AGENTS.md` : mocks dans `*.mock.ts`, données via `*.factory.ts`, `jest.spyOn()` avec `restoreAllMocks()`, aucun `any` ni `as unknown as`.

- **Score structurel** : tests unitaires purs (pondérations, utilisateur sans historique, plafonds).
- **Handler de calcul** : `MatchingScorer` et Redis mockés ; cas Jev en échec (liste `STRUCTURAL_ONLY`), cas Redis en échec à l'écriture, cas débounce, cas rejouabilité.
- **Lecture** : cas liste présente, absente, Redis en erreur (doit renvoyer `FALLBACK` et pas lever d'exception), pagination.
- **Gateway** : réordonnancement correct, identifiants disparus ignorés.
- **Trigger** : test d'intégration du post-processor (flux d'entrée vers ligne `jobs_outbox`).

## Questions ouvertes

1. **Clé et documentation de l'API Jev** : accès anticipé, non vérifiés ici. Bloquant pour T2 seulement.
2. **Redis ou relation Neo4j `MATCHES`** pour stocker les scores. Redis suit la décision du Lead Dev mais impose un client Redis dans `ms-social` et crée le mode « Redis indisponible ». La relation Neo4j évite les deux. Le choix n'affecte ni les déclencheurs ni le scoring.
3. **Historique récent** : les relations Neo4j n'ont pas d'horodatage et les requêtes n'ont pas de tri. Pour « les derniers événements du profil », il faut soit ajouter `createdAt` sur `PARTICIPATE` et `WISH_TO_PARTICIPATE` (changement `domain-social`), soit accepter un échantillon arbitraire de 20 identifiants. Le texte du goût est alors moins représentatif.
4. **Client gRPC `worker-social` vers `ms-event`** : `ms-event` et `post-processor-user` ont déjà des clients vers `ms-social` (`social-participation.query-client.ts`, `social-interaction.client.ts`) qui montrent le patron et la propagation du token interne. Le sens inverse (worker vers `ms-event`) n'existe pas et doit respecter `GrpcInternalGuard`. À préciser : quelle identité le worker présente-t-il, puisqu'il n'agit pas pour un utilisateur ?
5. **Émission de jobs depuis `post-processor-social`** : il écrit déjà dans `event_queue` via un repository TypeORM. Confirmer que sa base contient `jobs_outbox` et que `outbox-runners` surveille cette base pour `social-queue`.
6. **`bio` dans le profil de goût** : exclue par défaut. L'inclure améliorerait la pertinence mais envoie du texte libre à un tiers.
7. **Fan-out** : le plafond de 200 utilisateurs convient à une démonstration. Au-delà il faut un job par utilisateur.

## Risques

| Risque | Gravité | Atténuation |
| :--- | :--- | :--- |
| Données utilisateur envoyées à un tiers | Haute | liste blanche des champs ([04](04-scoring-et-jev.md)), aucune donnée identifiante |
| API Jev instable (accès anticipé) | Moyenne | port + repli structurel + timeouts |
| Dérive entre la formule et les listes stockées | Faible | champ `version` dans `matching:meta` |
| Coût d'appels Jev proportionnel aux déclencheurs | Moyenne | débounce 30 s, 30 candidats max, `matching:active` pour borner le fan-out |
| Bug connu `failure`/`failed` du post-processor de jobs | Faible ici | documenté en [03](03-flux-asynchrone.md), non spécifique au matching |

## Script de démonstration

1. Créer deux comptes, les rendre amis (suivi mutuel), faire participer l'un d'eux à deux événements écologiques et en souhaiter un troisième.
2. Appeler `GET /events/matching` pour le second compte : liste triée, `source = MATCHING`, scores visibles, un événement écologique ami en tête.
3. Arrêter Redis : relancer l'appel. `source = FALLBACK`, la liste reste servie. Montrer que rien n'est cassé.
4. Relancer Redis, appeler `POST /events/matching/refresh`, attendre quelques secondes : `source = MATCHING` de retour.
5. Dérouler dans `job_audit` la trace du job (`PROCESSING` puis `COMPLETED`) pour illustrer l'architecture asynchrone.
