# Post-processors

Ce dossier regroupe les notes de conception et décisions ouvertes sur les post-processors (consommateurs de Redis Streams) et leur alimentation par l'outbox `event_queue`.

## Navigation

| # | Document | Contenu |
| :--- | :--- | :--- |
| 01 | [Fan-out des streams (`user.deleted`)](01-fan-out-streams-user-deleted.md) | Pourquoi un événement est copié dans N streams, comparaison avec 1 stream et N consumer groups, DLQ, décision ouverte. |

## Voir aussi

- [C3 - Async Patterns & Flows](../architecture/C3-Async-Patterns-And-Flows.md) pour le Transactional Outbox et les Redis Streams.
