# Matching d'événements (recommandation asynchrone)

Ce dossier décrit le processus complet pour exposer un endpoint qui renvoie **les événements qui correspondent le mieux au profil de l'utilisateur connecté**, sans jamais calculer quoi que ce soit pendant la requête HTTP.

> [!NOTE]
> **Statut : proposition de conception.** Rien de ce qui est décrit ici n'est implémenté. Chaque fait sur le code existant est vérifié et référencé (fichier ou outil mesh-mcp). Tout ce qui est à créer est signalé comme tel, et tout ce qui reste à confirmer est listé dans [06 - Contrats, plan et questions ouvertes](06-contrats-et-plan.md).

## Principe en une phrase

Un calcul de score par couple (utilisateur, événement) est fait **en arrière-plan** par un job, à partir du graphe social de `ms-social` (Neo4j) et d'un jugement sémantique de Jev (TypeSafe AI). Le résultat est stocké dans Redis. L'endpoint ne fait que **lire** ce résultat, et retombe sur la recommandation structurelle existante si le résultat est absent ou si Redis est indisponible.

## Navigation

1. [01 - État des lieux](01-etat-des-lieux.md) : ce qui existe déjà et ce qui manque, avec preuves.
2. [02 - Architecture cible](02-architecture-cible.md) : composants, séquence, clés Redis.
3. [03 - Flux asynchrone](03-flux-asynchrone.md) : déclencheurs, contrat du job, handler pas à pas, idempotence.
4. [04 - Scoring et Jev](04-scoring-et-jev.md) : signaux, formule, port/adaptateur Jev, données envoyées.
5. [05 - Lecture et fallback](05-lecture-et-fallback.md) : RPC, route gateway, modes dégradés.
6. [06 - Contrats, plan et questions ouvertes](06-contrats-et-plan.md) : changements par dépôt, ordre de livraison (règle du STOP), tests, risques.

## Glossaire

| Terme | Sens dans ce dossier |
| :--- | :--- |
| Score structurel | Score issu du graphe (amis, historique, type d'événement). Déterministe, sans appel externe. |
| Score sémantique | Score issu de Jev : adéquation du texte d'un événement avec le goût déduit de l'historique. |
| Liste de matching | Sorted set Redis `matching:{userId}` : `eventId` en membre, score final en valeur. |
| Mode dégradé | Réponse construite sans liste de matching (Redis absent ou liste vide) : recommandation structurelle seule. |

## Décisions déjà prises avec le Lead Dev

- Calcul asynchrone obligatoire (jamais dans le chemin de la requête).
- Neo4j (`ms-social`) fournit les candidats et le signal social ; Jev reclasse sémantiquement.
- Redis sert de modèle de lecture, **jamais de source de vérité** : tout est recalculable.
- Un repli doit exister quand Redis est indisponible.
