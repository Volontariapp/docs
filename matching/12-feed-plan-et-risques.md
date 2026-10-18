# 12 - Feed de posts : plan, risques, questions ouvertes

Complète [09](09-plan-de-livraison.md). Le feed s'appuie sur la même fondation : **il ne peut être livré qu'après les tranches T0 et T1 des événements** (squelettes, coalescence, 206, notification, post-processors communs). Il en reprend les limites connues (chemin d'échec défectueux, `Admin*` sans contrôle de rôle, suppression de compte non couverte, perte possible d'événements de flux).

## 1. Changements par dépôt (en plus de [07](07-creation-du-microservice.md))

| Dépôt | Changement |
| :--- | :--- |
| `proto-registry` | `post.services.proto` / `post.query.proto` : RPC `ListRecentPostsByAuthors`, `ListPostsByIds`, `ListCommentsByAuthor` (additifs) ; `ranking.*.proto` : `GetRankingPosts`, `list_kind` dans `RequestRankingRefresh`, `RANKING_SOURCE_COLD_START`, `list_version`/`version_changed` |
| `npm-packages/messaging` | `RankingJobType.COMPUTE_USER_FEED`, `IComputeUserFeedPayload`, `IFanoutRankingPayload` généralisé (`trigger`), `RankingQueue.FEED` ; **second mapping WebSocket** |
| `npm-packages/domain-ranking` | entités `RankingLikeLog`, `RankingPostScore` ; migration avec `list_kind` dès l'origine ; service de score du feed ; réconciliation des likes |
| `npm-packages/domain-post` | implémentation des trois lectures ; filtre sur `mediaStatus` |
| `ms-post` | handlers des trois RPC ; **migration d'index** `CREATE INDEX ... ON posts ("authorId", "createdAt" DESC)` (`src/migrations/domain/`, resynchronisée par `sync-migrations.sh`) et tests de migration ; résolution de `eventId` via `ms-social` quand un jeton est transmis |
| `ms-ranking` | `GetRankingPosts`, demande `ON_DEMAND` pour `list_kind = POST`, nettoyage de rétention dans la transaction d'écriture |
| `post-processor-ranking` | deux post-processors de plus (**`POST_CREATED`**, **`POST_LIKED`/`POST_UNLIKED`** qui écrivent le journal) ; `UserCreated` écrit désormais **deux** demandes (EVENT et POST) dans une seule transaction ; options de flux et groupes de consommateurs |
| `worker-ranking` | `ComputeUserFeedHandler`, client gRPC `ms-post`, extension du fan-out (`trigger = POST_CREATED`), file `ranking-feed-queue` |
| `api-gateway` | `GET /ranking/feed`, client `ms-post` (`BasePostGrpcController`, `POST_PACKAGE` existent), filtre de blocage à la lecture, plafond de `limit` |
| `deploy` | NetworkPolicy `worker-ranking` vers `ms-post:3000` ; CronJob de purge des utilisateurs inactifs |
| `ci-tools` | `e2e-matrix.json` de `ms-post` (liste de tous les dépôts) |
| `nativapp` | écran de feed, hook `useRankingFeed`, gestion du 206, bandeau « nouveaux posts », handler de notification |

## 2. Ordre de livraison (règle du STOP)

Les trois RPC `ms-post` et les messages `ranking` se regroupent **dans la même PR `proto-registry`** que les contrats d'événements, pour ne pas multiplier les cycles. Ensuite : `npm-packages` (STOP), puis **`ms-post` doit être publié avant `worker-ranking` et `api-gateway`** (ils en dépendent), puis `ms-ranking` et ses runners, la gateway, `deploy`, `nativapp`.

## 3. Tranches

| Tranche | Contenu | Démontrable |
| :--- | :--- | :--- |
| F0 | RPC et index `ms-post`, tables du feed, journal de likes alimenté, réconciliation | les likes sont datés ; `ListCommentsByAuthor` fonctionne |
| F1 | Candidats suivis et engagés, score structurel, `ComputeUserFeedHandler`, lecture, 206, notification | `GET /ranking/feed` renvoie une liste classée sans Jev |
| F2 | Complément `GLOBAL` + démarrage à froid, diversité, lien événement, blocage à la lecture | un compte neuf voit des posts ; un auteur bloqué disparaît immédiatement |
| F3 | Fan-out sur nouveau post, coalescence, rafraîchissement périodique, bandeau côté client | le feed bouge quand quelqu'un publie, sans se reclasser en lecture |
| F4 (optionnelle) | Composante Jev derrière `RANKING_FEED_JEV_ENABLED` | classement sémantique, après décision |
| F5 (V2) | Événements de follow/unfollow/block dans `domain-social` ; câblage des médias dans `ms-post` | réactivité complète, filtre média strict |

F1 est livrable sans Jev.

## 4. Tests spécifiques

- **Journal de likes** : like puis unlike donne une pierre tombale ; **unlike reçu avant like** ne réactive pas le like plus ancien ; doublon de flux sans effet ; réconciliation (like du journal absent du graphe : pierre tombale ; like du graphe absent du journal : ajouté en `BACKFILL`) ; `occurred_at` pris dans l'enveloppe, pas l'horloge locale ; like sur son propre post ignoré ; payload où `userId` est absent (acteur = `authorId` / `emitterId`).
- **Commentaires** : plusieurs commentaires du même utilisateur sur un post comptent chacun ; un commentaire supprimé disparaît au calcul suivant ; commentaire sur son propre post ignoré.
- **Score** : décroissance (un signal de 14 jours pèse la moitié) ; `K = 6` ne sature pas avec un like et un commentaire ; normalisation avec et sans Jev, `score` toujours dans [0, 1] ; un auteur suivi sans interaction passe devant un auteur non suivi du même âge ; rétrogradation d'un post déjà liké ; diversité (pas plus de 3 consécutifs, un seul auteur sans troncature).
- **Candidats** : plafond par auteur (un auteur prolifique n'affame pas les autres) ; auteurs engagés prioritaires sur les suivis au-delà du plafond ; complément `GLOBAL` placé après les posts personnels ; `COLD_START` ; posts liés à un événement hors fenêtre d'âge ; `mediaStatus = UNSPECIFIED` toléré, `PENDING`/`REJECTED` exclus.
- **Fan-out** : pagination des abonnés jusqu'au plafond sans doublon, intersection avec les utilisateurs actifs, abonné dormant ignoré.
- **Indépendance des deux `list_kind`** : coalescence, version de formule, verrou consultatif et anti-écrasement n'interfèrent pas entre événements et posts ; le 206 porte le bon type de job.
- **Gateway** : réordonnancement, posts absents ignorés, blocage appliqué même si la liste précalculée contient un auteur bloqué après coup, plafond de `limit`, `versionChanged`.
- **Stabilité** : pas de doublon ni de saut de page quand le calcul remplace la liste entre deux pages (via `listVersion`).
- **Confidentialité** : aucun texte de post envoyé quand Jev est désactivé ; test d'absence de champs interdits quand il est activé.

## 5. Observabilité (en plus de [08](08-tests-observabilite-securite.md))

`ranking.feed.candidates`, `ranking.feed.truncated` (taux de plafonnement à 300), `ranking.feed.origin{FOLLOWED,ENGAGED,EVENT,GLOBAL}`, `ranking.feed.list.age`, `ranking.feed.fanout.size`, `ranking.likelog.lag` (`now - event.createdAt`), `ranking.likelog.reconciled{added,deleted}` (fantômes détectés), erreurs par dépendance (`ms-post`, `ms-social`). L'alerte sur `COLD_START` est affinée : elle ne vaut que pour des utilisateurs qui suivent des comptes **actifs** (un utilisateur qui ne suit que des comptes inactifs est légitimement en démarrage à froid). Ne pas journaliser ensemble `userId`, `postId` et `authorId` hors niveau debug (cela reconstitue un comportement).

## 6. Risques

| Risque | Gravité | Atténuation |
| :--- | :--- | :--- |
| Blocage non appliqué à la lecture : un auteur bloqué reste visible jusqu'au prochain recalcul | **Haute** (sécurité de l'utilisateur) | filtre de blocage dans la gateway à chaque lecture (F2) |
| Contenu non modéré montré à un compte neuf (aucune modération ni signalement dans `ms-post`) | **Haute** | complément `GLOBAL` désactivable tant qu'un signalement n'existe pas ; à signaler |
| Profil de goûts envoyé à un tiers (si Jev activé) | Haute | Jev désactivé par défaut |
| Journal de likes : donnée comportementale primaire, non recalculable, sans effacement de compte | Haute (conformité) | rétention, suppression avec le compte (T5 des événements), question de chiffrement au repos |
| Fan-out amplifié et abonnés tronqués | Moyenne | pagination, intersection avec les actifs, coalescence, file dédiée |
| Médias non implémentés dans `ms-post` | Moyenne | filtre en exclusion (`PENDING`/`REJECTED`) |
| Rafale d'`ON_DEMAND` au déploiement (aucun utilisateur n'a de liste) | Moyenne | `RANKING_FEED_ENABLED`, concurrence bornée, file fallback |
| Feed qui se reclasse pendant la lecture | Moyenne | pas de recalcul sur signal, `listVersion`, bandeau côté client |
| Index absent sur `posts` : lectures coûteuses | Moyenne | migration d'index avec les RPC |
| Pas de découverte : le feed ne remonte aucun auteur inconnu | Faible à Moyenne (produit) | nommer honnêtement ; part d'exploration en question ouverte |
| Chambre d'écho | Faible à ce volume | rétrogradation des posts déjà aimés, diversité d'auteurs |
| Horloges : `requestedAt` d'un hôte comparé à `started_at` d'un autre | Moyenne | utiliser l'horloge de la base `ms-ranking` pour les deux ([04](04-flux-asynchrone.md)) |
| Mêmes dettes que les événements | Haute | voir [09](09-plan-de-livraison.md) |

## 7. Questions ouvertes

### Tranchées par la revue (vérifiées dans le code)

| # | Question | Réponse |
| :--- | :--- | :--- |
| 6 | Sens de `authorId` / `userId` dans les payloads | `authorId` = acteur (liker ou auteur du commentaire) ; `userId` jamais renseigné ; l'auteur du post est absent ; acteur et date dans l'enveloppe (`emitterId`, `createdAt`) |
| 7 | Tri de `ListPosts` | Aucun : à ne pas utiliser pour le complément |
| 8 | Comment `nativapp` récupère le contenu d'un feed | Il ne le fait pas : `feed/me` n'est utilisé par aucun écran |
| 9 | Préfixe de route | `GET /api/v1/social/feed/me` |
| 10 | Compteur de likes | Inexistant |
| 11 | Visibilité d'un post | Public, aucun champ de visibilité |
| - | Enrichissement de la gateway | Aucun |
| - | Statut des médias | Non renseigné par `ms-post` |

### À décider par l'équipe

1. **Jev pour le feed** : proposition, désactivé par défaut.
2. **Posts déjà likés** : rétrogradation à 0,6 (proposée) ou exclusion.
3. **Part d'exploration** (auteurs inconnus) et **nom** du feed : sans exploration, « feed d'abonnements » est plus honnête que « Pour toi ».
4. **Complément `GLOBAL`** pour les comptes neufs, malgré l'absence de modération.
5. **Chiffrement au repos** du journal de likes (`AGENTS.md` section 6 : toute donnée personnelle doit être chiffrée).
6. **Recalcul sur like/commentaire** : désactivé par défaut ; l'activer avec un délai de 5 minutes pour la démonstration ?
7. **Correction du feed existant** (aucun `ORDER BY`) : à traiter à part.

### À vérifier dans le code avant d'implémenter

8. Le travail média en cours éventuel dans une autre branche de `ms-post` / `ms-storage` (la revue a lu `main`).
9. Le comportement réel de l'ordre Neo4j sur `SKIP/LIMIT` sans `ORDER BY` (déduit du Cypher, non mesuré) et l'effet réel d'un fan-out sur la page 1 des abonnés.
10. Si `JOB_TO_EVENT_MAPPING` accepte un enum dédié `ranking` ou impose `EventEventMessagingType`.
11. La lecture complète de `neo4j-event-post-link.repository.ts` (lignes 24-35 non lues) et des écrans `nativapp` autres que `post.api.ts` / `social.endpoints.ts`.
12. Politique de conservation des données de TypeSafe AI (déjà ouverte).

## 8. Définition de « terminé » pour le feed

- F0 à F3 livrées, tests verts, STOP respectés.
- Le blocage est appliqué à la lecture ; aucun texte de post n'est envoyé à un tiers sans décision explicite.
- Démonstration : trois comptes `A`, `B`, `C` ; `C` suit `A` et like deux de ses posts ; `A` publie un nouveau post ; le feed de `C` le place en tête après le délai de coalescence ; `D` (compte neuf) reçoit le démarrage à froid puis une liste après notification ; `C` bloque `A` : les posts de `A` disparaissent immédiatement sans recalcul.

## 9. Journal des corrections issues de la revue

| Gravité | Constat | Traitement |
| :--- | :--- | :--- |
| Bloquant | Sens des champs `authorId`/`userId` inversé ; registre impossible à alimenter | [10](10-feed-etat-des-lieux.md) section 4, [11](11-feed-conception.md) section 3 : acteur lu dans le payload/l'enveloppe, `author_id` retiré du journal, résolu au calcul |
| Bloquant | Filtre média `NONE`/`READY` exclurait tout (statut jamais renseigné) | Obsolète depuis le 2026-10-18 : `ms-post` renseigne `mediaStatus`, filtre strict `NONE`/`READY` |
| Majeur | `ListPosts` sans tri pour le démarrage à froid | `all_authors` dans `ListRecentPostsByAuthors` |
| Majeur | Noms de colonnes et index `ms-post` | `"authorId"`, `"createdAt"`, migration d'index |
| Majeur | `author_id` des likes et liens d'événements sans N+1 | `ListPostsByIds` ; posts liés chargés directement |
| Majeur | Clé primaire du registre de commentaires | registre de commentaires supprimé, `ListCommentsByAuthor` |
| Majeur | Ordre like/unlike non garanti | pierres tombales datées + réconciliation avec le graphe |
| Majeur | Blocage non appliqué à la lecture | filtre dans la gateway |
| Majeur | Plafonds et priorités de candidats, seuil de démarrage à froid | plafond par auteur, auteurs engagés d'abord, `MIN_ITEMS` |
| Majeur | Fan-out mal borné | pagination, intersection avec les actifs, payload dédié |
| Majeur | Changement de clé `(user_id, kind)` | `list_kind` dès la première migration, requêtes et versions par type |
| Majeur | Feed qui se reclasse pendant la lecture | pas de recalcul sur signal, `listVersion`, bandeau |
| Majeur | Registre contredit le principe « verdicts dérivés » | principe amendé, rétention, effacement, chiffrement en question |
| Majeur | Rétention sans planificateur | purge dans la transaction + CronJob |
| Majeur | Pas de découverte | nom et exploration en question ouverte |
| Majeur | Posts déjà likés ; contenu non modéré | rétrogradation ; risque Haute |
| Mineur | Formule : normalisation, `K`, plafond des non évalués | `K = 6`, normalisation par somme des poids actifs, règle de [05](05-scoring-et-jev.md) reprise |
| Mineur | `eventId` non stocké ; `ListPostsByIds` non spécifié ; configuration ; file de fond ; sens de `kind` ; horloges ; déploiement à chaud ; tests | traités dans 11 et 12 |
