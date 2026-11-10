# 04 - Risques de cohérence

Les optimisations du chapitre 03 changent quand et combien de fois un événement est livré. Ce chapitre dit ce qui peut casser, et dans quel ordre faire les lots pour que rien ne casse.

## 1. Ce que garantit l'outbox aujourd'hui

| Situation | Ce qui se passe (FAIT, lecture du code) | Garantie |
| :--- | :--- | :--- |
| Le push Redis échoue | `markAsFailed` : ligne `FAILED`, `attempts = 1` (`outbox.consumer.ts:130-136`, `outbox.dispatcher.ts:35-53`) | Jamais relancée (chapitre 01, N2) : **perdue** |
| Le runner meurt après le claim | Les lignes du lot restent `PROCESSING` | Jamais reprises : **perdues** |
| L'UPDATE de `markAsCompleted` échoue | `markAsFailed` lève, la boucle s'arrête, le reste du lot reste `PROCESSING` (N3) | **Perdues** |
| Le push réussit en partie (plusieurs streams cibles) | Le pipeline lève à la première erreur (`event-queue.pusher.ts:118-126`), la ligne passe `FAILED` alors que certains streams ont reçu le message | Livrée à une partie des consommateurs |

Conclusion : l'outbox est aujourd'hui **« au plus une fois »**. La mesure du 2026-11-10 le confirme : 147 lignes perdues le 2026-11-07 (chapitre 02). Les post-processors, eux, sont écrits pour « au moins une fois » (retries, DLQ, verrou d'idempotence) : c'est l'outbox qu'il faut aligner.

## 2. Idempotence sur l'id de l'événement

### Le verrou actuel

- Clé : `idempotency:post-processor:<groupe>:<id du message Redis>` (`post-processors/src/core/helpers/redis-stream.helper.ts:108-110`), posée par `SET ... processing NX EX 86400` avant le traitement (`:116-125`).
- **Défaut 1, doublons non vus.** Un même événement poussé deux fois par l'outbox reçoit deux ids de message Redis (`XADD ... *`, `event-queue.pusher.ts:85-90`) : deux clés, deux traitements. Aujourd'hui l'outbox ne repousse jamais (section 1), donc le défaut ne se voit pas. **Dès que L4 (reprise) ou L5 (lot) arrive, il se verra.** D'où l'ordre : L3 avant L4 et L5.
- **Défaut 2, message sauté après la mort d'un consommateur.** Le verrou est posé avant le traitement et vaut 24 h. Si le pod meurt pendant le traitement, le message reste en attente dans le groupe ; un autre consommateur le réclame après 60 s (`base.post-processor.ts:485-516`, `claimMinIdleTimeMs` 60 000) ; le `SET NX` échoue parce que la clé existe ; le message est **acquitté sans être traité** (`batch.post-processor.ts:59-67`). Le nom du consommateur contient le nom du pod (`base.post-processor.ts:52,66`), qui change à chaque redémarrage : le cas arrive à chaque redémarrage pendant un traitement (INFERENCE sur la fréquence).
- Le verrou est bien relâché en cas d'erreur métier (`batch.post-processor.ts:238-240`, `single.post-processor.ts:183-190`) : les retries fonctionnent.

### Ce que change L3

- La clé porte l'id de l'événement (`fields.id`, l'id de la ligne `event_queue`), stable d'un push à l'autre.
- Deux valeurs : `processing` (durée courte, celle du claim) et `done` (24 h). Un `processing` trouvé ne fait pas acquitter : le message attend l'expiration et sera retraité.
- Limite connue : deux lignes `event_queue` différentes pour un même fait métier (par exemple un like rejoué par le client) ne sont pas dédoublonnées par ce verrou. C'est le rôle des règles métier (`SOCIAL_RELATIONSHIP_ALREADY_EXISTS`, tables de dédoublonnage des badges `badge_progress_dedup`).
- Les consommateurs qui écrivent doivent rester idempotents même avec le verrou : il expire après 24 h, et Redis peut perdre des clés (redémarrage sans persistance, NON VERIFIE sur la configuration AOF de `redis-master`).

## 3. Lots d'outbox et fenêtre de panne

Avec L5, un lot de 50 lignes est poussé en un pipeline, puis marqué `COMPLETED` en un UPDATE.

| Panne | Avant L5 | Après L5 (avec L4) |
| :--- | :--- | :--- |
| Le runner meurt entre le push et l'UPDATE | 1 ligne poussée et restée `PROCESSING` (perdue aujourd'hui) | Jusqu'à 50 lignes poussées et restées `PROCESSING`, reprises par L4 après 5 min, **poussées deux fois** |
| Redis refuse une partie du pipeline | La ligne en cours passe `FAILED` | Les entités en échec passent `FAILED` une à une (résultat par entité de `pipeline.exec()`), les autres `COMPLETED` |
| L'UPDATE `COMPLETED` échoue | Le reste du lot reste bloqué (N3) | Tout le lot reste `PROCESSING`, repris par L4, poussé deux fois |

Ordre obligatoire : **L3 (dédoublonnage), puis L4 (reprise), puis L5 (lot).** Faire L5 sans L3 multiplie par 50 la taille des doublons ; faire L4 sans L3 transforme chaque reprise en double traitement.

Ordre des événements : la reprise remet en `PENDING` des lignes anciennes, qui repartent avant les plus récentes (le claim trie par `created_at`), mais après des lignes plus récentes déjà livrées. Un consommateur qui reçoit `post.deleted` puis, en reprise, `post.created` du même post doit l'ignorer. NON VERIFIE pour chaque consommateur : à lire avant L4 avec `analyze_impact` sur chaque type présent dans les lignes bloquées.

## 4. Atomicité Neo4j et outbox dans ms-social

Aujourd'hui (FAIT) : `likePost` écrit le like dans Neo4j (`interaction.service.ts:49`), puis la ligne `event_queue` dans Postgres (`:66`) ; une erreur Postgres est avalée en `warn` (`:70-74`). Même chose pour l'unlike, le souhait et son retrait. Conséquence : un like sans `post.liked`, donc sans badge, sans notification, sans effet sur le classement. Autre défaut : `createLike` ne vérifie pas que le `MERGE` a créé quelque chose (`neo4j-interaction.repository.ts:26-35`) ; si le nœud `SocialPost` n'existe pas encore (créé de façon asynchrone par `post-processor-social` à partir de `post.created`), aucun like n'est écrit mais `post.liked` part quand même.

Il n'y a pas de transaction commune à Neo4j et Postgres. **Décision du 2026-11-10 : option « Postgres d'abord » (proche de B, sans changer le contrat de l'API), conception au chapitre 06.** Les trois options d'origine :

| Option | Principe | Fenêtre d'incohérence | Coût |
| :--- | :--- | :--- | :--- |
| A. Postgres englobe Neo4j (recommandée, L9) | BEGIN ; INSERT `event_queue` ; écriture Neo4j ; COMMIT ; compensation Neo4j si le COMMIT échoue | Un COMMIT qui échoue après Neo4j et une compensation qui échoue aussi : rare, journalisé en `error` | Une connexion Postgres tenue pendant l'appel Neo4j |
| B. Outbox d'abord, Neo4j par l'événement | ms-social n'écrit que `event_queue`, un post-processor écrit Neo4j | Aucune, mais le like n'est pas visible tout de suite (lecture après écriture cassée) | Change le contrat de l'API |
| C. Neo4j d'abord, outbox reprise par réconciliation | Garder l'ordre, ne plus avaler l'erreur, et un job de réconciliation compare Neo4j et les événements | Jusqu'au passage du job | Un job de plus, difficile à écrire juste |

## 5. Triggers SQL et changements de forme des écritures

Des triggers écrivent dans `event_queue` (chapitre 01, N5). Toute optimisation qui change le **nombre** d'UPDATE ou d'INSERT change le nombre d'événements émis :

- `update()` sans `save` (L6) écrit même quand rien ne change : sans garde `IS DISTINCT FROM`, chaque appel émet un `event.changed`.
- Le passage de saga par lot (L8) émet un `event.changed` par ligne modifiée, comme avant ; la garde `saga_status IS DISTINCT FROM` évite les événements inutiles.
- Les INSERT multi-lignes dans `event_tags` (L7) émettent un `event.tag_linked` par ligne, comme `save`.
- `job_audit` n'émet que sur `UPDATE OF status` vers `COMPLETED` ou `FAILED` (`ms-ranking/src/migrations/common/1792000000000-FixJobAuditStatusTriggerEmitterIdSafe.ts`) : `recordAuditStart` (INSERT ON CONFLICT) n'émet rien tant que le statut n'est pas final.

## 6. Autres points relevés

- Géocodage (`post-processor-event/.../event-created.post-processor.ts:94-147`) : `update()` de l'événement puis écriture du retour dans `event_queue`, hors transaction commune ; un échec du second laisse l'événement géocodé sans retour, et le rejeu du lot refait le géocodage des événements déjà traités (INFERENCE : le service tiers est appelé deux fois).
- Succès de job (`job-outbox-success.post-processor.ts:89-93`) : une erreur d'INSERT dans la transaction est avalée en `debug` ; dans Postgres, la transaction est alors abandonnée et le `COMMIT` annule aussi le `DELETE` (INFERENCE sur le comportement de TypeORM au `COMMIT` d'une transaction en erreur, non testé).
