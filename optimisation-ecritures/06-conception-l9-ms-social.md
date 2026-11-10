# 06 - Conception de L9 : ms-social, Postgres d'abord

Chapitre écrit le 2026-11-10, avant toute ligne de code, pour le lot L9. Il remplace l'option A du chapitre 04 (section 4) et la description de L9 du chapitre 03, qui renvoient ici.

**Décision** (Victor, transmise par l'orchestrateur le 2026-11-10) : option « Postgres d'abord ». La latence d'application dans le graphe est acceptée. Les autres options sont en section 8.

Légende : **FAIT** (ligne lue sur `origin/main` le 2026-11-10 ou sortie d'outil), **INFERENCE**, **NON VERIFIE**.

## 1. Le principe

1. Like, unlike, follow, unfollow, souhait, retrait du souhait, participation et départ écrivent, dans **une seule transaction Postgres** de ms-social, l'état voulu de la relation (table `social_edge`, section 3) et une ligne d'outbox.
2. Un handler de `worker-social` applique l'état dans Neo4j avec un Cypher idempotent, réessaie jusqu'au succès, et finit en DLQ en dernier recours.
3. Aucun nouveau relais : l'outbox-runner `outbox-social` pousse déjà `event_queue` et `jobs_outbox` (FAIT : `outbox-runners/outbox-social/src/runners/social-event-queue.runner.ts` et `social-jobs-outbox.runner.ts`) ; `worker-social` existe, est déployé (1 réplique, FAIT : `kubectl get deploy`) et a déjà Postgres `ms_social` et Neo4j dans sa configuration (FAIT : `workers-runners/worker-social/config/default.config.json`). Son seul handler, `FOLLOW_USER`, ne fait rien (FAIT : `worker-social/src/workers/handlers/follow-user.handler.ts:19-24`).

Gain sur Neo4j : le chemin de requête d'un like passe de 2 sessions Neo4j (lecture puis écriture) à 0. L'écriture Neo4j est faite plus tard, à un débit borné par la concurrence du worker (section 6). C'est ce qui compte depuis l'incident du démarrage à froid (dossier `montee-en-charge`, chapitre 09) : le test à froid du 2026-11-10 donne encore 52 % d'erreurs, Neo4j saturé à 2 CPU avec 64 connexions, délais d'acquisition du pool et transactions coupées à 1,8 s, pour 21 Mo de données (le coût est celui du JVM et des plans, pas du disque).

## 2. Ce que la réponse gRPC doit continuer à dire

FAIT : les réponses des huit RPC sont vides (`proto-registry/proto/volontariapp/social/social.responses.proto:14-17`, `:91-94`, `:113-120`). Ce qui dépend aujourd'hui de l'état du graphe, ce sont les **erreurs** :

| RPC | Erreur | D'où vient-elle aujourd'hui (FAIT) | D'où viendra-t-elle |
| :--- | :--- | :--- | :--- |
| `PostLikePost` | `SOCIAL_RELATIONSHIP_ALREADY_EXISTS` | `likeExists` Neo4j (`domain-social/src/services/interaction.service.ts:46`) | `INSERT ... ON CONFLICT DO NOTHING RETURNING` sur `social_edge` : 0 ligne = déjà liké |
| `DeleteLikePost` | `SOCIAL_RELATIONSHIP_NOT_FOUND` | `likeExists` Neo4j (`:90`) | `DELETE ... RETURNING` sur `social_edge` : 0 ligne = pas liké |
| `PostFollowUser`, `DeleteFollowUser` | idem | `relationshipExists` (`relationship.service.ts:31`, `:48`) | idem |
| `PostUserWishEvent`, `DeleteUserWishEvent` | `SOCIAL_WISH_ALREADY_EXISTS`, `SOCIAL_WISH_NOT_FOUND` | `wishExists` (`participation.service.ts`) | idem |
| `PostUserParticipateEvent`, `DeleteUserParticipateEvent` | `SOCIAL_PARTICIPATION_ALREADY_EXISTS`, `_NOT_FOUND` | `participationExists` | idem |
| Souhait, participation | `SOCIAL_EVENT_NOT_FOUND` | `eventExists` Neo4j (`participation.service.ts:168`, `:190`) | voir ci-dessous |

nativapp s'appuie sur le 409 : `useLikePost` corrige son +1 optimiste quand le serveur répond `ALREADY_EXISTS` (FAIT : `nativapp/src/api/social/hooks/use-like-post.ts:57-72`). Le contrat d'erreur doit donc rester exact, d'où un état en Postgres et non un simple journal d'intentions.

**Existence de l'événement** (souhait, participation) : ms-social n'a aucune table métier en Postgres (FAIT : `ms-social/src/migrations` ne contient que `common/`), donc ne connaît pas les événements. Deux choix :

- **Retenu pour L9** : garder une seule lecture Neo4j, `eventExists`, sur ces deux routes (4 sessions aujourd'hui pour une participation, 1 après). Le like et le follow n'ont aucune lecture de ce type aujourd'hui (le `MERGE` ne vérifie rien, FAIT : `neo4j-interaction.repository.ts:26-35`), ils n'en auront pas.
- Plus tard, si la mesure le justifie : une projection Postgres des événements connus, alimentée par le post-processor qui crée déjà les nœuds `SocialEvent`.

## 3. Le modèle Postgres

Une table, migration `domain` dans ms-social (première migration de cette partition, suivre `volontariapp-db-migration`) :

```sql
CREATE TABLE social_edge (
  kind       text        NOT NULL,  -- 'LIKE' | 'FOLLOW' | 'WISH' | 'PARTICIPATE'
  from_id    uuid        NOT NULL,  -- utilisateur
  to_id      uuid        NOT NULL,  -- post, utilisateur ou événement
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (kind, from_id, to_id)
);
CREATE INDEX social_edge_to_idx ON social_edge (kind, to_id);
```

La table porte l'**état voulu**, pas l'historique. Une relation présente doit exister dans Neo4j, une relation absente ne doit pas y exister. Le compteur et la liste restent servis par Neo4j (`GetPostsLikeSummary`, `GetPostLikers`) : aucun chemin de lecture ne change dans L9.

Une seule transaction par écriture :

```sql
BEGIN;
INSERT INTO social_edge (kind, from_id, to_id) VALUES ('LIKE', $user, $post)
  ON CONFLICT DO NOTHING RETURNING created_at;      -- 0 ligne : ROLLBACK, 409
INSERT INTO jobs_outbox (...) VALUES (...);          -- job SOCIAL_EDGE_APPLY (section 4)
COMMIT;
```

Le participer supprime en plus la ligne `WISH` du même couple dans la même transaction (règle actuelle, `participation.service.ts:174-177`), et le job dit d'appliquer les deux.

Nettoyage : quand un utilisateur, un post ou un événement est supprimé, le handler qui fait aujourd'hui le `DETACH DELETE` du nœud supprime aussi ses lignes `social_edge` (sinon un nouveau like renverrait `ALREADY_EXISTS` à tort). À relire avant de coder : `SocialUserNodeCommandService.DeleteUserNode`, `DeletePostNode`, `DeleteEventNode` et la saga `user.deleted` (skill `volontariapp-user-account-deletion`).

## 4. L'application dans Neo4j

Job BullMQ `SOCIAL_EDGE_APPLY` sur la file `SocialQueue.SOCIAL` (nouveau type dans `@volontariapp/messaging`), charge utile `{ kind, fromId, toId, action, intentAt }`.

Le handler ne rejoue pas la commande, il **fait converger** : il relit la ligne `social_edge` du couple et applique l'état trouvé.

```cypher
// ligne présente
MATCH (u:SocialUser {userId: $fromId})
MATCH (p:SocialPost {postId: $toId})
MERGE (u)-[:LIKE]->(p)
RETURN count(*) AS applied
// ligne absente
MATCH (:SocialUser {userId: $fromId})-[r:LIKE]->(:SocialPost {postId: $toId})
DELETE r
```

Pourquoi relire l'état plutôt qu'appliquer l'action du job : un like puis un unlike rapprochés donnent deux jobs, que BullMQ peut traiter dans le désordre dès que la concurrence dépasse 1. En appliquant l'état courant, l'ordre n'a plus d'importance : les deux jobs convergent vers le dernier état écrit en Postgres. Un job rejoué (reprise L4, réessai BullMQ) ne fait rien de plus. L'identifiant du job est l'id de la ligne `jobs_outbox` (FAIT : `outbox/src/pushers/jobs-outbox.pusher.ts:43`, `jobId: entity.id`), donc une ligne poussée deux fois ne crée qu'un job, et `BaseWorker` saute un job déjà `COMPLETED` (FAIT : `workers/src/core/base.worker.ts:95-140`).

Nœud absent (`applied = 0` alors que la ligne existe) : le `SocialPost` ou le `SocialUser` est créé de façon asynchrone par `post.created` ou `user.created`. Le handler lève une erreur réessayable ; le job repasse plus tard. Aujourd'hui, le même cas écrit un `post.liked` sans like (chapitre 04, section 4) : c'est une correction.

Réessais : le pusher fixe aujourd'hui `attempts: 3` pour tous les jobs (FAIT : `jobs-outbox.pusher.ts:24-25`). Pour ce job, il en faut plus : 12 tentatives en exponentiel à partir de 1 s couvrent environ 68 min (INFERENCE, somme de 1 à 2 048 s), assez pour un redémarrage de Neo4j ou un nœud créé en retard. Au-delà : `job_audit` en `FAILED`, ligne en DLQ, alerte. Le choix des options par type de job demande une évolution de `@volontariapp/outbox` (NON VERIFIE : relire `jobOptions`, `jobs-outbox.pusher.ts:101`).

## 5. L'ordre entre l'événement et le graphe

Question posée : que fait chaque consommateur s'il traite l'événement avant que le graphe soit à jour ?

| Événement | Consommateur | Lit-il le graphe ? (FAIT) | Effet d'un événement en avance |
| :--- | :--- | :--- | :--- |
| `post.liked`, `post.unliked` | `post-processor-ranking` | Non : journal de likes (`post-liked.post-processor.ts:30-45`) | Aucun |
| `post.liked` | `post-processor-user` (badges) | Non : résout l'auteur par ms-post et compte en Postgres (`badge-evaluator.service.ts:96-139`) | Aucun |
| `post.liked`, `post.unliked` | `ws-service`, puis nativapp | ws-service non (`post-liked.post-processor.ts:27-59`) ; **nativapp oui** : `handlePostLiked` invalide `likes-summary` et `post-likers` (`nativapp/src/hooks/useNotificationHandlers.ts:136-147`), et `likes-summary` est lu dans Neo4j | **Le like peut disparaître** : l'app relit le résumé, Neo4j n'a pas encore le like, `likedByMe` repasse à faux jusqu'au prochain rafraîchissement. Même chose chez les autres utilisateurs qui regardent le post (`broadcastExcept`) |
| `event.social.wished` | `post-processor-ranking` (`RankingWishService.addWish`), badges | Non | Aucun |
| `event.finished` (pas émis par L9) | badges | **Oui** : `getAllEventParticipantIds` (`badge-evaluator.service.ts:173-181`) | Une participation encore non appliquée au moment de la fin de l'événement n'est pas comptée. Fenêtre de quelques secondes (INFERENCE) |

Conséquence : si l'événement part dans la même transaction que l'intention (consigne initiale), il arrive à ws-service à peu près en même temps que le job arrive au worker (les deux passent par le même runner), et nativapp peut relire le graphe avant l'application. Le scintillement est probable sous charge, et certain pendant un démarrage à froid de Neo4j.

**Variante recommandée (écart à la consigne, à confirmer)** : la transaction de ms-social écrit `social_edge` et le job, et c'est le handler du worker qui écrit l'événement métier (`post.liked`, `event.social.wished`...) dans `event_queue` de ms-social, **après** l'écriture Neo4j réussie, avec un id déterministe dérivé de l'id du job (`INSERT ... ON CONFLICT (id) DO NOTHING`). Propriétés :

- Tout consommateur qui reçoit l'événement voit le graphe à jour : plus de scintillement, et la participation est dans le graphe avant tout événement qui en dépend.
- Toujours « au moins une fois » : si le worker meurt entre Neo4j et l'INSERT, le job est réessayé, le `MERGE` ne fait rien, l'INSERT est fait. Si l'INSERT est fait deux fois, l'id déterministe l'absorbe, et L3 absorbe un double push.
- Coût : un passage d'outbox de plus avant les consommateurs (de l'ordre de 1 s avec L2, INFERENCE), accepté par Victor.
- Le worker écrit dans la base de ms-social : c'est déjà sa base (configuration lue plus haut), et `BaseWorker` y écrit `job_audit`.

Variante conforme à la consigne, si elle est maintenue : l'événement part avec l'intention, et nativapp ne relit plus `likes-summary` quand l'événement vient de lui-même (`isEmitter = true`, l'optimiste suffit). Le scintillement reste possible chez les autres spectateurs du post. Demande une version de nativapp.

## 6. Concurrence du worker et charge de Neo4j

| Réglage | Valeur proposée | Raison |
| :--- | :--- | :--- |
| `concurrency` de `worker-social` | 4, variable `WORKER_CONCURRENCY` (modèle : `worker-ranking`, `config.ranking.workerConcurrency` passé à `@Processor`, FAIT : `worker-ranking/src/workers/ranking.worker.ts:20`) | 4 transactions d'écriture courtes en parallèle laissent l'essentiel des 64 connexions et des 2 CPU aux lectures. À froid, c'est 4 transactions en attente au plus, au lieu d'une par requête HTTP |
| Limiteur BullMQ | `limiter: { max: 100, duration: 1000 }` | Plafonne le débit d'écriture même si la file est pleine après une panne ; à régler par la mesure |
| Répliques | 1 | La concurrence suffit ; deux pods doublent la pression sur Neo4j au redémarrage |
| Réessais | section 4 | Un Neo4j froid fait échouer des jobs : ils repassent avec un délai croissant au lieu de faire échouer la requête de l'utilisateur |

Charge de Neo4j attendue (INFERENCE, à mesurer pendant la rampe d'écriture L1) :

- Chemin synchrone : 0 session Neo4j pour like, unlike, follow, unfollow ; 1 lecture pour souhait, retrait, participation, départ (au lieu de 2 à 5 sessions). Les erreurs à froid de ces routes ne viennent plus que de cette lecture.
- Chemin asynchrone : 1 transaction d'écriture par job, plus 1 lecture Postgres. Le débit d'écriture vers Neo4j est plafonné à 4 en parallèle, quelle que soit la rafale.
- Les lectures (`events-list-app`, `GetSearchExclusions`, `likes-summary`) ne sont pas changées par L9. Le froid de ces routes n'est pas résolu par L9 : il dépend du préchauffage du JVM et des plans (chapitre 09 de `montee-en-charge`).

## 7. Mise en place sans coupure

Expand, puis contract (skill `volontariapp-db-migration`) :

1. **Paquets** (`npm-packages`, STOP) : `messaging` (type de job et charge utile), `domain-social` (repository Postgres de `social_edge`, services réécrits derrière un réglage `socialWriteMode: 'sync' | 'async'`, défaut `sync`), `outbox` si les options de job par type sont nécessaires.
2. **ms-social** : migration `social_edge`, `yarn up`, mode `sync` : on écrit Neo4j comme aujourd'hui **et** `social_edge` dans la même requête (double écriture), l'outbox ne change pas.
3. **Rattrapage** : copier les relations existantes de Neo4j vers `social_edge` (`INSERT ... ON CONFLICT DO NOTHING`, par lots). Volume faible (21 Mo de données Neo4j). Écriture en prod : lancée par Victor, procédure à écrire avec le code.
4. **worker-social** : handler `SOCIAL_EDGE_APPLY`, concurrence, réessais ; `deploy` : variables.
5. **Bascule** : `socialWriteMode=async` dans `deploy`. Retour arrière : repasser à `sync` (la table reste juste, le graphe aussi, puisque les jobs en vol convergent).
6. **Contract** : supprimer les `catch` qui avalent l'erreur d'outbox (`interaction.service.ts:70-74`, `:114-118`, `participation.service.ts:293-297` et le retrait du souhait) dès l'étape 2 ; supprimer le mode `sync` une fois l'`async` stable.

Le blocage (`PostBlockUser`) reste synchrone : rare, et il change ce que voient les lectures tout de suite.

## 8. Options écartées

| Option | Pourquoi elle est écartée |
| :--- | :--- |
| Outbox dans Neo4j (nœud `:OutboxEvent` créé dans la transaction Neo4j, relais vers Redis Streams) | Retenue un temps par l'orchestrateur, puis remplacée. Un nouveau relais à écrire, à déployer et à surveiller, et plus d'écritures sur Neo4j (un nœud d'outbox, puis sa mise à jour en livré, en plus de la relation), au moment où Neo4j est la ressource saturée à froid |
| Postgres englobe Neo4j (BEGIN, outbox, écriture Neo4j, COMMIT, compensation) | Ancienne option A du chapitre 04. Une connexion Postgres tenue pendant l'appel Neo4j, et l'écriture Neo4j reste sur le chemin de la requête : à froid, la requête échoue comme aujourd'hui |
| Commit en deux phases (XA) | Neo4j et TypeORM n'offrent pas de coordinateur commun ; complexité sans rapport avec le besoin |
| Neo4j d'abord et réconciliation par un job | Fenêtre d'incohérence jusqu'au passage du job, et un job de comparaison difficile à écrire juste |

## 9. Tests prévus

- `domain-social`, unitaires (mocks dans `*.mock.ts`) : like créé, déjà présent (409), unlike absent (404) ; la transaction contient `social_edge` et le job ; aucun appel Neo4j en mode `async` pour like et follow ; un échec de l'INSERT du job annule la transaction.
- `domain-social`, intégration Postgres : `ON CONFLICT` sous 20 likes concurrents du même couple donne 1 ligne et 19 erreurs 409.
- `worker-social`, unitaires : état présent donne `MERGE`, état absent donne `DELETE` ; nœud absent lève une erreur réessayable ; l'événement métier est écrit après Neo4j avec un id déterministe, et un second passage ne crée pas de seconde ligne.
- Intégration Neo4j de test (docker-compose de `ci-tools`) : like puis unlike traités dans le désordre convergent vers « pas de like ».

## 10. Non vérifié

| Point | Comment le vérifier |
| :--- | :--- |
| Options de job par type dans `@volontariapp/outbox` (`attempts`, `backoff`) | Lire `jobs-outbox.pusher.ts:15-110` avant de coder |
| Handlers de suppression de nœuds (`DeleteUserNode`, `DeletePostNode`, `DeleteEventNode`, saga `user.deleted`) | `analyze_grpc` sur chaque RPC, puis lecture |
| Effet de `SetEventAttendance` (pointage) sur une participation pas encore appliquée | Lire le contrôle de `SetEventAttendance` dans `domain-social` ; INFERENCE : il lit la relation `PARTICIPATE` et échouerait pendant quelques secondes |
| Lectures de nativapp juste après une participation (écran de l'événement, live) | Lire les hooks de participation de nativapp |
