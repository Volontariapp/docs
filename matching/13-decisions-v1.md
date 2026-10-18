# 13 - Décisions de la V1 (2026-10-18)

Ce fichier consigne les décisions prises avec le Lead Dev le 2026-10-18 et les conséquences techniques à en tirer. Il prime sur les fichiers 01 à 12 quand ils divergent. Les faits sont référencés (`fichier:ligne`) ; ce qui n'a pas été vérifié est dit.

## 1. Décisions validées

| # | Décision |
| :--- | :--- |
| 1 | Le service s'appelle `ms-ranking` (`ms-affinity` n'était qu'un nom de travail ; `ms-rank` est écarté car `nativapp/src/shared/lib/impact-ranks.ts` utilise déjà « rank » pour les niveaux d'impact). Dérivés : `domain-ranking`, `outbox-ranking`, `worker-ranking`, `post-processor-ranking`, tables `ranking_*`, streams `ranking:job:outbox:success` et `:failure`, routes `/ranking/*`. |
| 2 | Événements **et** posts dès la V1. Tranche T1 sans Jev, Jev en T2 (une clé API est disponible). |
| 3 | À Jev, on n'envoie que du texte d'événements et de posts publics : aucune donnée personnelle (pas de pseudo, d'identifiant, de bio). |
| 4 | Géographie : pour les **événements seulement** (un post n'est pas géolocalisé). Zone d'origine déduite de l'historique (option c) **et** position stockée de l'utilisateur (option b). |
| 5 | Position : route dédiée `PUT /ranking/location` appelée à l'ouverture de l'application ; arrondie à 1 km ; chiffrée au repos ; un recalcul n'est demandé qu'après un déplacement de plus de 10 km. |
| 6 | L'utilisateur ne doit voir que des événements **publiés, non commencés et non terminés** (`PUBLISHED` et `startAt > now`). Le statut `DRAFT` est exclu. |
| 7 | Un événement souhaité ou participé est **exclu** de la liste d'événements. En revanche, un post lié à un événement **futur** souhaité est favorisé. |
| 8 | Un post déjà liké ou déjà commenté est rétrogradé (facteur unique de 0,6, sans cumul). |
| 9 | Le swipe à gauche est enregistré (`PASS`) en lot, avec exclusion de l'événement pendant 30 jours (`RANKING_PASS_COOLDOWN_DAYS`). |
| 10 | Un événement populaire gagne en poids : composante `popularity` de 0,10 dans le score structurel (section 5). |
| 11 | L'explication du classement est une liste de **codes** renvoyée à l'application, qui les traduit en texte (section 6). |
| 12 | Suppression de compte : stream `user:deleted:ranking` et purge dans `ms-ranking`, avec participation au gather de `ws-service` (section 7). Cela modifie `domain-user` et `ws-service`. |
| 13 | Démarrage à froid : 206 + job à la demande + notification WebSocket. Un compte neuf voit les événements proches et à venir, triés par date. |
| 14 | Fraîcheur : 24 h pour les événements, 2 h pour les posts. Un rafraîchissement explicite de l'utilisateur renouvelle la liste (section 4). |
| 15 | Base PostgreSQL dédiée (nécessaire aux tables `jobs_outbox`, `job_audit`, `event_queue` du patron outbox). |
| 16 | Dimensionnement : 1 000 utilisateurs actifs. `RANKING_MAX_FANOUT` passe de 500 à 1 000. |
| 17 | Pas d'environnement de staging ni de déploiement progressif : l'indicateur `RANKING_FEED_ENABLED` de [11](11-feed-conception.md) section 11 est supprimé. Le STOP et la CI restent. |
| 18 | Les RPC `Admin*` sans contrôle de rôle sont une limite connue, non bloquante. `worker-ranking` signe un jeton interne `ADMIN`, comme `post-processor-user`. Un garde de rôle est un chantier séparé (`auth`, donc STOP). |
| 19 | Le complément `GLOBAL` du feed est conservé comme repli, après les posts personnels. |
| 20 | Les faux utilisateurs avec historiques sont en cours de préparation par l'équipe (jeu d'essai pour valider le classement). |
| 21 | Le feed existant `GET /api/v1/social/feed/me` n'est consommé par aucun écran (section 9) : on ne le touche pas. |

## 2. Poids initiaux

Ils remplacent ceux de [05](05-scoring-et-jev.md) et de [11](11-feed-conception.md) là où ils divergent. Ce sont des valeurs de départ, versionnées par `FORMULA_VERSION` ; elles seront ajustées avec le jeu d'essai.

**Événements** (score structurel, détail dans [05](05-scoring-et-jev.md)) :

| Composante | Poids | Définition |
| :--- | :--- | :--- |
| Proximité | 0,27 | `exp(-distance / 15 km)` ; coupure dure à 100 km (`RANKING_MAX_DISTANCE_KM`) |
| Amis | 0,23 | booléen : l'événement est touché par au moins un ami |
| Affinité de type et de tags | 0,22 | part du `type` dans l'historique et recouvrement des tags |
| Imminence | 0,18 | proche du jour de début |
| Popularité | 0,10 | signal global (section 5) |

Les poids validés (0,30 / 0,25 / 0,25 / 0,20) ont été réduits de 10 % chacun pour libérer 0,10 à la popularité.

**Posts** :

| Composante | Poids | Définition |
| :--- | :--- | :--- |
| Lien avec un événement | 0,30 | fort si l'événement est futur et souhaité ou participé ; plus faible s'il est passé, avec décroissance |
| Affinité d'auteur | 0,30 | auteur suivi (+0,25), ami (+0,15), interactions passées (like 1, commentaire 2) |
| Fraîcheur du post | 0,30 | demi-vie d'environ 33 h |
| Proximité de l'événement lié | 0,10 | 0 pour un post sans événement lié |

Rétrogradation : score ×0,6 pour un post déjà liké ou commenté.

Fait : `SearchEventsQuery` a un filtre `area` de type `GeoCircle` (`proto-registry/proto/volontariapp/event/event.query.proto:11`) et un événement a un `location` de type `Point` (`event.proto:52`). La coupure à 100 km se fait donc côté `ms-event`, à la génération des candidats ([04](04-flux-asynchrone.md) étape 4), avec `statuses = [PUBLISHED]` et `start_date_from = now`. La gateway re-filtre à la lecture les événements commencés, terminés ou complets ([06](06-lecture-et-206.md) section 4).

## 3. Position de l'utilisateur

Faits : l'écran de swipe utilise déjà la position de l'appareil (`useLocation`, `expo-location`, `nativapp/src/screens/main/hooks/use-swipe-screen.ts:6,12,66`). Aucun champ de position n'a été trouvé dans `proto-registry/proto/volontariapp/user/user.proto` (recherche limitée à ce fichier).

Conception :

- Table `ranking_user_location` ([03](03-modele-de-donnees.md) section 2 bis). `lat` et `lng` sont arrondis à 1 km avant stockage et chiffrés au repos (`AGENTS.md` section 6). Le mécanisme de chiffrement reste à choisir (le paquet `npm-packages/packages/crypto` existe, non évalué).
- `PUT /ranking/location` (gateway) vers une commande gRPC `UpdateUserLocation`. Si la nouvelle position est à plus de 10 km de la précédente (`RANKING_LOCATION_REFRESH_KM`), une demande `STALE_REFRESH` est écrite.
- Repli sans position (permission refusée) : zone d'origine déduite de l'historique, c'est-à-dire le centre des événements déjà souhaités ou participés (option c). Sans historique ni position, le terme de proximité est neutre (0,5).
- La purge de la position fait partie du post-processor de suppression de compte.

## 4. Interface de swipe

Faits (`nativapp/src/screens/main/hooks/use-swipe-screen.ts`) :

- L'écran appelle la recherche d'événements existante (`useGetEvents`) avec `limit: 20`, les exclusions de créés, souhaités et participés, les statuts `PUBLISHED` **et `DRAFT`**, et `startDateFrom = now` (lignes 50-60, 31). Avec la décision 6, `DRAFT` devra être retiré côté application, ou l'écran migrer vers `GET /ranking/events`.
- Un préchargement est déclenché quand il reste moins de 10 cartes (ligne 30).
- Un swipe à droite appelle `wish` (lignes 88-96).
- Un swipe à gauche ne fait qu'avancer à la carte suivante : **rien n'est enregistré** (lignes 98-101).

Conception retenue :

1. **Signal négatif.** `POST /ranking/events/feedback` enregistre en lot les swipes à gauche (`PASS`) ; l'application les envoie groupés à la fin d'un lot ou toutes les N cartes. Table `ranking_event_feedback`. Le souhait (swipe à droite) reste porté par le graphe.
2. **Exclusion temporaire.** Un événement `PASS` est exclu pendant 30 jours (`RANKING_PASS_COOLDOWN_DAYS`), puis peut revenir.
3. **Ajustement entre deux lots.** L'application consomme par lots de 20. À chaque lecture d'un nouveau lot, `ms-ranking` réordonne le reste du pool précalculé (100 éléments) en pénalisant le type et les tags des événements récemment passés. C'est un calcul léger à la lecture, sans job de worker. Les souhaits continuent de déclencher un recalcul complet (coalescence de 30 s).
4. **Pagination par curseur.** `GET /ranking/events?cursor=...&limit=20` avec `listVersion` pour détecter un changement de liste ([11](11-feed-conception.md) section 8).
5. **Rafraîchissement façon Instagram.** `GET /ranking/events?refresh=true` (et son équivalent pour le feed), appelé au rafraîchissement du profil ou au redémarrage de l'application, demande un recalcul (`MANUAL`, file de repli) et sert le pool actuel en attendant la notification WebSocket. Une limite de fréquence par utilisateur est nécessaire (valeur proposée : une demande par minute).

## 5. Popularité

Décision : un événement très populaire gagne en poids dans le classement, tant qu'il est publié et non commencé. Spécification complète et formule dans [05](05-scoring-et-jev.md) (section « Popularité »).

Entrées, toutes disponibles sans scheduler ni appel par événement :

| Entrée | Source | Fait vérifié |
| :--- | :--- | :--- |
| Souhaits | table `ranking_event_wish`, alimentée par `EVENT_SOCIAL_WISHED` et `EVENT_SOCIAL_UNWISHED` | le payload contient `eventId` (`npm-packages/packages/messaging/src/events/social/payloads.ts:49-50`) |
| Passes | table `ranking_event_feedback` | n'existe pas encore (section 4) |
| Taux de remplissage | `currentParticipants / maxParticipants`, renvoyés par `ms-event` | champs de `EventEntity` (`domain-event/src/entities/event.entity.ts:19-20`) |
| Mentions | table `ranking_event_mention`, alimentée par `POST_CREATED` | le payload porte un `eventId` optionnel et le `userId` de l'auteur (`IPostCreatedPayload`) |

Limites assumées : les souhaits et mentions antérieurs au déploiement ne sont pas rétro-alimentés ; on compte des auteurs distincts pour limiter la manipulation ; un événement sans vote reste neutre.

## 6. Codes d'explication

Chaque ligne de classement porte au plus deux codes (`reasons`), choisis parmi les composantes qui contribuent le plus au score et dépassent un seuil. L'application traduit les codes en texte ; l'identité d'un ami n'est pas exposée.

| Liste | Codes |
| :--- | :--- |
| Événements | `FRIEND_INVOLVED`, `NEAR_YOU`, `MATCHES_INTERESTS`, `STARTING_SOON`, `TRENDING` |
| Posts | `FOLLOWED_AUTHOR`, `FRIEND_AUTHOR`, `ENGAGED_AUTHOR`, `LINKED_EVENT_WISHED`, `LINKED_EVENT_JOINED`, `NEARBY_EVENT`, `RECENT` |

Côté contrat, un `enum` proto (par exemple `RankingReason`) évite les chaînes libres. Colonne `reasons` dans `ranking_score` ([03](03-modele-de-donnees.md)).

## 7. Suppression de compte : participation au gather

Faits (lus le 2026-10-18) :

- `requestDeletionWithUserDeleted` écrit `user.deleted` dans `event_queue` vers 5 streams : `USER_DELETED`, `SOCIAL_USER`, `USER_DELETED_POST`, `USER_DELETED_EVENT`, `USER_DELETED_STORAGE` (`domain-user/src/repositories/postgres-user.repository.ts:90-111`).
- `ws-service` crée un état de gather à la réception de `user.deleted` (`ws-service/src/post-processors/users/user-deleted.post-processor.ts:9-19`). Sa config déclare pour ce déclencheur quatre acquittements attendus (`USER_SOCIAL_DELETED`, `USER_POST_DELETED`, `USER_EVENT_DELETED`, `USER_STORAGE_DELETED`), l'événement de succès `user.deletion_successfull` et l'événement d'échec `user.deletion_failed` (`ws-service/config/default.config.json`, section `scatterGather`).
- Chaque domaine consomme son stream, purge, puis écrit un événement d'acquittement dans `event_queue` vers `ws:user-deleted-feedback` ; en cas d'échec définitif (DLQ), il écrit un événement d'échec (modèle : `post-processor-storage/src/post-processors/user-deleted.post-processor.ts:32-171`).
- Une clé non acquittée dans les 60 s est marquée en échec par le reaper, qui tourne toutes les 10 s (`ws-service/src/core/services/gather-reaper.service.ts:45-47,58-81`).
- `finalizeDeletion` n'est appelé qu'à réception de `user.deletion_successfull` (`post-processor-user/.../user-deletion-success.post-processor.ts:54`) et ne supprime que les comptes encore `PENDING_DELETION`.
- Outils : `analyze_impact user:deleted` (profondeur 3) liste les 4 post-processors de domaine (`event`, `post`, `social`, `storage`) et leurs consommateurs `ws-service`.

Étapes pour `ms-ranking` :

1. `shared` : `Streams.USER_DELETED_RANKING = 'user:deleted:ranking'`.
2. `messaging` : types `USER_RANKING_DELETED` et `USER_RANKING_DELETION_FAILED` avec payloads `{ userId }` et `{ userId, errorReason }` (modèle : `StorageEventMessagingType.USER_STORAGE_DELETED`).
3. `domain-user` : ajouter le stream aux `targetServices` de `requestDeletionWithUserDeleted`.
4. `post-processor-ranking` : `UserDeletedPostProcessor` qui purge `ranking_score`, `ranking_post_score`, `ranking_run`, `ranking_request`, `ranking_like_log`, `ranking_event_feedback`, `ranking_event_wish`, `ranking_event_mention` (par `author_id`) et `ranking_user_location`, puis écrit l'acquittement ; surcharge de `sendMessageToDlq` pour l'événement d'échec.
5. `ws-service` : ajouter `USER_RANKING_DELETED` aux `expects` de `user.deleted`, et créer les post-processors et options de feedback correspondants (modèle : `user-storage-deleted*.post-processor.ts` et `ws-user-storage-deleted*.options.ts`, enregistrés dans le module).

**Ordre de déploiement critique.** Si `ws-service` attend `USER_RANKING_DELETED` avant que `post-processor-ranking` existe, chaque suppression de compte échoue au bout de 60 s (inférence d'après le reaper, non testée) et le compte reste `PENDING_DELETION`, puisque `finalizeDeletion` n'est appelé que sur le succès. Il faut donc déployer `post-processor-ranking` d'abord, puis la config de `ws-service`.

Vérifié : aucune surcharge du gather dans `deploy/apps` ni `deploy/infrastructure` (recherche de `scatterGather`, `USER_STORAGE_DELETED`, `expects`, aucun résultat).

## 8. Plafonds et dimensionnement

- `RANKING_MAX_FANOUT = 1000` (événements).
- Un nouvel événement crée jusqu'à 1 000 demandes de calcul, réduites par la coalescence. Avec Jev actif, l'ordre de grandeur est de 5 M de tokens d'entrée par événement créé (estimation de [05](05-scoring-et-jev.md) section 7, chiffres du fournisseur non vérifiés). Les limites de débit de Jev sont inconnues : à mesurer avant d'activer Jev sur le fan-out.
- `RANKING_WORKER_CONCURRENCY` n'est pas câblé dans les workers existants (`npm-packages/packages/workers/src/interfaces/worker-app-config.interface.ts:5` ne contient que l'interface) : à câbler dans `@Processor`.

## 9. Écarts corrigés depuis la rédaction de 01 à 12

| Sujet | Avant | Constat du 2026-10-18 |
| :--- | :--- | :--- |
| Suppression de compte | `user:deleted` sans producteur | `requestDeletionWithUserDeleted` écrit `user.deleted` vers 5 streams ; chaque domaine a son stream de purge et un acquittement vers le gather de `ws-service` |
| Médias des posts | `mediaStatus` jamais renseigné | `ms-post` renseigne `media` et `mediaStatus` (`ms-post/src/modules/post/transformers/post.transformer.ts:41-69`) |
| Modèle de scaffolding | `ms-social` | `ms-storage` est le domaine le plus récent et traite `user.deleted` (`post-processor-storage`) |
| Feed existant | « aucun écran ne l'utilise » | confirmé : `GET_FEED_SELF` n'est que déclaré dans `nativapp/src/api/endpoints/social.endpoints.ts:318-323` (aucune autre occurrence dans `nativapp/src` pour `GET_FEED` et `GET_FEED_SELF`) |
| `sync-migrations.sh` | `ms-storage` absent | confirmé : `SERVICES=("user" "social" "post" "event")` ; ajouter `"ranking"` |
| Écran de swipe | non analysé | swipe gauche non enregistré, statut `DRAFT` inclus (section 4) |

## 10. Points encore ouverts

1. Mécanisme de chiffrement de la position (section 3).
2. Limite de fréquence du rafraîchissement explicite : une demande par minute proposée.
3. Config de `ws-service` : aucune surcharge du gather trouvée dans `deploy/apps` ni `deploy/infrastructure` (recherche de `scatterGather`, `USER_STORAGE_DELETED`, `expects`) ; la modification se fait donc dans `ws-service/config/default.config.json`.
4. Limites de débit et coût réel de Jev sur un fan-out de 1 000 utilisateurs.
5. Périmètre front : les changements de `nativapp` (route de position, envoi des `PASS`, écran de swipe branché sur `/ranking/events`, traduction des codes) relèvent-ils de ce chantier ? Les règles de `nativapp/CLAUDE.md` imposent la lecture de ses skills React Native avant toute tâche front.
6. Valeurs de départ de la popularité et des poids : à calibrer avec le jeu d'essai.
