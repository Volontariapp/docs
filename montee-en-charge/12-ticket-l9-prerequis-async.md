# 12 - Ticket : prérequis de la phase `async` de L9 (ms-social « Postgres d'abord »)

Ticket rédigé le 2026-11-10, au format de [`matching/17-format-des-tickets-notion.md`](../matching/17-format-des-tickets-notion.md). Il n'est pas encore créé dans Notion.

`1.x NPM - domain-social : nettoyage de social_edge à la suppression et fin des erreurs d'outbox avalées (STOP)`

| Propriété | Valeur |
| :--- | :--- |
| EPIC | à choisir (aucune option « montée en charge » dans Backlogs) |
| État / Priority | `todo` / P1 : bloque la bascule `async`, sans effet tant que ms-social reste en `sync` |
| Ressources | `NPM-PACKAGE`, `Post-Processors`, `Postgres`, `Outbox` |
| Charge / Delais / Difficulté | `2h30` / `2h30` / Moyenne |
| Description | Faire que toute suppression d'un utilisateur, d'un post ou d'un événement nettoie aussi `social_edge`, et ne plus avaler les erreurs d'écriture de l'outbox dans `domain-social`. |
| Bloqué par | npm-packages#321 (fusionnée), ms-social#78 (phase 1, double écriture) |
| Bloque | bascule de ms-social en `SOCIAL_WRITE_MODE=async` |

> Contexte & Objectif : faire que toute suppression d'un utilisateur, d'un post ou d'un événement nettoie aussi `social_edge`, et ne plus avaler les erreurs d'écriture de l'outbox dans `domain-social`.

## Définition du problème

Phase 1 de L9 (ms-social#78) : chaque écriture Neo4j de ms-social est copiée dans la table Postgres `social_edge`, et les RPC `DeleteUserNode`, `DeletePostNode`, `DeleteEventNode` de ms-social appellent `deleteEdgesOfNode`. Deux trous restent, **sans effet tant que la table n'est pas lue** (mode `sync`), mais bloquants avant `async`, où `social_edge` devient la source de vérité des intentions :

1. **Suppressions faites hors de ms-social.** Les post-processors de `post-processor-social` appellent directement les services de `domain-social`, sans passer par ms-social, donc sans `deleteEdgesOfNode`. Les lignes `social_edge` de l'élément supprimé restent. En `async`, un nouveau like sur un post recréé avec le même id répondrait `ALREADY_EXISTS` à tort, et le backfill recompterait des liens morts.
2. **Erreurs d'outbox avalées.** Dans `domain-social`, l'écriture de l'événement dans `event_queue` est dans un `catch` qui journalise en `warn` et continue : un like peut exister dans Neo4j sans son `post.liked`. Le chemin `async` (`SocialEdgeApplyService`) ne le fait plus, mais l'ancien chemin reste utilisé en `sync` et en repli.

## Description de la tâche

1. Dans `domain-social`, faire nettoyer `social_edge` par les méthodes de suppression du package, pour que tous les appelants en profitent sans changement de leur côté :
   - `SocialUserService.purgeUser` : les lignes où l'utilisateur est `from_id` ou `to_id`, et celles de ses posts et événements, que la purge Neo4j détache aussi ;
   - `ParticipationService.deleteEventsBatch` : les lignes dont `to_id` est l'un des événements ;
   - `PublicationService.deletePosts` : les lignes dont `to_id` est l'un des posts.
   Réutiliser `PostgresSocialEdgeRepository` (`deleteByNode` existe, ajouter une variante par lot). Ordre : Neo4j d'abord, puis `social_edge`, comme `deleteEdgesOfNode` dans ms-social.
2. Supprimer les `catch` qui avalent l'erreur d'outbox, et laisser l'erreur remonter (l'appelant renvoie une erreur, le client réessaie) :
   - `interaction.service.ts` : `likePost` (`:70-74`) et `unlikePost` (`:114-118`) ;
   - `participation.service.ts` : `wishEvent` (`:293-297`), `unwishEvent` (`:339-343`), `pushAttendanceSet` (`:410-414`).
   À décider pendant le ticket : si l'écriture Neo4j a réussi et l'outbox échoue, compenser dans Neo4j (option A, chapitre 04 section 2 du dossier `optimisation-ecritures`) ou laisser la reprise E4 et `social_edge` réconcilier. Le noter dans la PR.
3. Copier la migration `social_edge` de ms-social (`src/migrations/domain/1794340000000-CreateSocialEdge.ts`) dans `packages/domain-social/src/test/migrations/domain/`, pour que les tests d'intégration du package tournent sur un schéma neuf.
4. Règle du STOP : build, tests, changeset, PR, arrêt. Après publication : `yarn up @volontariapp/domain-social` dans `post-processors-runner/post-processor-social` et dans ms-social.

## Aide

- Appelants vérifiés le 2026-11-10 sur `origin/main` de `post-processors-runner` (git grep) :
  - `post-processor-social/src/post-processors/users/user-deleted.post-processor.ts:52` : `purgeUser` (saga `user.deleted`) ;
  - `post-processor-social/src/post-processors/users/user-created.post-processor.ts:56` : `purgeUser` (compensation) ;
  - `post-processor-social/src/post-processors/events/event-deleted.post-processor.ts:71` : `deleteEventsBatch` ;
  - `post-processor-social/src/post-processors/events/event-created.post-processor.ts:105` : `deleteEventsBatch` (compensation) ;
  - `post-processor-social/src/post-processors/posts/post-deleted.post-processor.ts:68` : `publicationService.deletePosts` ;
  - `post-processor-social/src/post-processors/posts/post-created.post-processor.ts:113` : `publicationService.deletePosts` (compensation).
  Non vérifié : les appelants dans les autres repos. À refaire avec mesh-mcp (`analyze_impact` sur `user.deleted`, `event.deleted`, `post.deleted`) sur toutes les racines avant de coder.
- `post-processor-ranking` a son propre `purgeUser` (`domain-ranking`, `ranking-purge.service.ts`) : hors périmètre.
- Le nettoyage par lot doit tenir dans une requête par appel (`DELETE ... WHERE to_id = ANY($1)`), comme le reste de L9.
- Idempotence : le post-processor peut rejouer un message (E3, `post-processors` 3.7.0) ; un `DELETE` rejoué ne fait rien, c'est voulu.

## Références dans la codebase

- `npm-packages/packages/domain-social/src/services/social-user.service.ts:65` (`purgeUser`)
- `npm-packages/packages/domain-social/src/services/participation.service.ts:89` (`deleteEventsBatch`), `:259` (`wishEvent`), `:305` (`unwishEvent`), `:382` (`pushAttendanceSet`)
- `npm-packages/packages/domain-social/src/services/interaction.service.ts:41` (`likePost`), `:85` (`unlikePost`)
- `npm-packages/packages/domain-social/src/repositories/neo4j-social-user.repository.ts` (`purgeUser` Neo4j)
- `ms-social` PR #78 : `SocialEdgeMirrorService`, migration `CreateSocialEdge`
- Dossier `optimisation-ecritures/` : chapitre 06 (conception de L9), chapitre 04 (risques de cohérence)

## Étapes pour la réalisation

- [ ] 1. `analyze_impact` sur `user.deleted`, `event.deleted`, `post.deleted` (toutes les racines) : liste complète des appelants
- [ ] 2. Nettoyage de `social_edge` dans `purgeUser`, `deleteEventsBatch`, `deletePosts`, avec tests unitaires (mocks) et d'intégration (migration copiée)
- [ ] 3. Suppression des cinq `catch`, tests : une erreur d'outbox remonte à l'appelant
- [ ] 4. `yarn build`, `yarn test`, changeset, `yarn changeset version`, PR, STOP
- [ ] 5. Après publication : `yarn up` dans `post-processor-social` et ms-social, une PR par repo

## Definitions of done

- [ ] La PR est liée au ticket
- [ ] Une documentation est rattachée au ticket
- [ ] Quelqu'un a approuvé le changement
- [ ] Après suppression d'un utilisateur, d'un post ou d'un événement par le flux asynchrone, `social_edge` ne contient plus aucune ligne qui le cite (test d'intégration)
- [ ] Aucun `logger.warn` d'échec d'outbox ne subsiste dans `domain-social` ; une erreur d'outbox fait échouer l'opération (test unitaire)

## Dépendances et estimation

- Bloqué par : npm-packages#321 (fusionnée), ms-social#78
- Bloque : bascule `SOCIAL_WRITE_MODE=async`, recâblage des contrôleurs de ms-social vers `SocialEdgeIntentService`
- Estimation : 2h30. Responsable : à définir. Livraison prévue : à définir.
