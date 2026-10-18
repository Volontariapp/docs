# 13 - Décisions de la V1 (2026-10-18)

Ce fichier consigne les décisions prises avec le Lead Dev et les conséquences techniques à en tirer. Il prime sur les fichiers 01 à 12 quand ils divergent. Les faits sont référencés (`fichier:ligne`) ; ce qui n'a pas été vérifié est dit.

## 1. Décisions validées

| # | Décision |
| :--- | :--- |
| 1 | Le service s'appelle `ms-ranking` (`ms-affinity` n'était qu'un nom de travail ; `ms-rank` est écarté car `nativapp/src/shared/lib/impact-ranks.ts` utilise déjà « rank » pour les niveaux d'impact). Dérivés : `domain-ranking`, `outbox-ranking`, `worker-ranking`, `post-processor-ranking`, tables `ranking_*`, streams `ranking:job:outbox:success` et `:failure`, routes `/ranking/*`. |
| 2 | Événements **et** posts dès la V1. Tranche T1 sans Jev, Jev en T2 (une clé API est disponible). |
| 3 | À Jev, on n'envoie ni identifiant, ni pseudo, ni bio, ni e-mail : seulement du texte d'événements publics. **Le résumé de goût (événements souhaités ou participés) est un profil agrégé** : il est envoyé tel quel, trié de façon stable, après obtention de la politique de conservation du fournisseur (décision 33). |
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
| 22 | Les changements de `nativapp` font partie du chantier, **en dernier** ([15](15-nativapp.md)). La **carte** reste en dehors du ranking pour l'instant et ne doit pas être cassée : `useGetEvents` n'est pas modifié. |
| 23 | Rafraîchissement : route **`POST /ranking/refresh`** avec corps `{listKind}` ; `?refresh=true` est supprimé (un GET ne doit pas avoir d'effet de bord). Limite de **5 par minute et par utilisateur**, **un seul seau `REFRESH` partagé** entre événements et posts (simple, et il protège la capacité de calcul). Au-delà, la liste actuelle est servie sans recalcul et sans erreur (`refreshThrottled`). |
| 24 | Chiffrement de la position : `@volontariapp/crypto` (AES-256-GCM) avec trois précautions (section 3 bis). Pas de nouvelle bibliothèque. |
| 25 | Le feed de posts porte lui aussi des codes d'explication (`reasons`). Ils ne sont pas affichés par l'application pour l'instant. |
| 26 | Jev avant les embeddings ; la base vectorielle est écartée ([16](16-jev-ou-embeddings.md)). |
| 27 | Le travail est à but éducatif : pas de contrainte de production, mais les règles du STOP, de la CI et de la sécurité s'appliquent. |
| 28 | Ordre de travail : documentation complète -> tickets Notion générés depuis [14](14-plan-d-implementation.md) -> implémentation point par point. Aucun code avant les tickets. |
| 29 | `contracts/src/gateway/` est **écrit à la main** (contrats entre l'application, la gateway et les DTO web) ; tout le reste de `contracts` est **généré** depuis les `.proto` (contrats gRPC entre microservices). Les DTO web du ranking s'écrivent donc à la main dans `npm-packages/packages/contracts/src/gateway/ranking/`. |
| 30 | Le journal de likes n'est **pas chiffré** (exception documentée à `AGENTS.md` section 6, section 3 bis) : chiffrer notre copie n'apporterait pas de protection réelle et compliquerait tout. Mesures de compensation : rétention de 90 jours, purge à la suppression du compte, accès base restreint. |
| 31 | `ci-tools` est reporté, on en parlera plus tard. |
| 32 | `PUT /ranking/location` est limité par un seau `LOCATION` d'**1 appel par minute** et par utilisateur. Un lot de `PASS` est plafonné à **50 éléments** (`RANKING_FEEDBACK_MAX_BATCH`). |
| 33 | Résumé de goût envoyé à Jev (**confirmé par le Lead Dev le 2026-10-18**) : **tel quel**, trié de façon stable par identifiant (un ordre aléatoire n'apporte rien et empêche de reproduire un appel), texte public uniquement. Condition avant d'activer Jev (RK-21) : obtenir la politique de conservation de TypeSafe AI. |
| 34 | Posts : **pas de composante « proximité de l'événement lié »** en V1 (elle imposerait un appel de plus à `ms-event` et un post n'est pas géolocalisé). Poids : lien événement 0,35, affinité d'auteur 0,30, fraîcheur 0,35. Le code `NEARBY_EVENT` est supprimé. |
| 35 | Curseur de pagination **opaque** `(listVersion, lastRank)`. L'ajustement lié aux `PASS` ne touche que les rangs non encore servis (section 4). |
| 36 | Déploiement en **deux vagues** : `post-processor-ranking` d'abord, la configuration du gather de `ws-service` ensuite (section 7). |
| 37 | L'ancien RK-18 est scindé en quatre tickets (RK-18a à RK-18d) et une configuration par environnement est ajoutée (RK-12b), voir [14](14-plan-d-implementation.md). |

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

**Posts** (somme 1,00) :

| Composante | Poids | Définition |
| :--- | :--- | :--- |
| Lien avec un événement | 0,35 | fort si l'événement est futur et souhaité ou participé ; plus faible s'il est passé, avec décroissance |
| Affinité d'auteur | 0,30 | auteur suivi (+0,25), ami (+0,15), interactions passées (like 1, commentaire 2) |
| Fraîcheur du post | 0,35 | demi-vie d'environ 33 h |

Rétrogradation : score ×0,6 pour un post déjà liké ou commenté. Si Jev est actif pour le feed (désactivé par défaut) : `0,85 × structurel + 0,15 × sémantique`.

Fait : `SearchEventsQuery` a un filtre `area` de type `GeoCircle` (`proto-registry/proto/volontariapp/event/event.query.proto:14`) et un événement a un `location` de type `Point` (`event.proto:52`). Le rayon se donne en **mètres** : 100 km = 100000. La coupure se fait côté `ms-event`, à la génération des candidats ([04](04-flux-asynchrone.md) étape 4), avec `statuses = [PUBLISHED]` et `start_date_from = now`. La gateway re-filtre à la lecture les événements commencés, terminés ou complets ([06](06-lecture-et-206.md) section 4).

## 3. Position de l'utilisateur

Faits : l'écran de swipe utilise déjà la position de l'appareil (`useLocation`, `expo-location`, `nativapp/src/screens/main/hooks/use-swipe-screen.ts:6,12,66`). Aucun champ de position n'a été trouvé dans `proto-registry/proto/volontariapp/user/user.proto` (recherche limitée à ce fichier).

Conception :

- Table `ranking_user_location` ([03](03-modele-de-donnees.md) section 2 bis). `lat` et `lng` sont arrondis à 1 km avant stockage et chiffrés au repos (`AGENTS.md` section 6). Chiffrement : `@volontariapp/crypto` avec les précautions de la section 3 bis.
- `PUT /ranking/location` (gateway) vers une commande gRPC `UpdateUserLocation`, limitée à 1 appel par minute (décision 32). Si la nouvelle position est à plus de 10 km de la précédente (`RANKING_LOCATION_REFRESH_KM`), une demande `STALE_REFRESH` est écrite.
- Repli sans position (permission refusée) : zone d'origine déduite de l'historique, c'est-à-dire le centre des événements déjà souhaités ou participés (option c). Sans historique ni position, le terme de proximité est neutre (0,5).
- La purge de la position fait partie du post-processor de suppression de compte.

## 3 bis. Chiffrement et limites de débit

**Évaluation de `@volontariapp/crypto`** (`npm-packages/packages/crypto`, utilisé uniquement par `domain-user`, 3 fichiers d'après `find_dependents`) :

| Point | Constat | Source |
| :--- | :--- | :--- |
| Algorithme | AES-256-GCM, IV aléatoire de 12 octets, étiquette d'authentification ; format `iv:tag:donnée` en hexadécimal | `src/symmetric/cipher.ts:8-26` |
| Clé | une clé de 32 octets est utilisée telle quelle ; tout autre secret est haché par SHA-256 sans sel | `src/symmetric/kdf.ts:4-14` |
| Usage éprouvé | chiffrement déterministe des e-mails dans `domain-user` | `postgres-user.repository.ts:15,32,39,44` |
| Manques | pas de données authentifiées additionnelles (AAD), pas d'identifiant de version de clé | `cipher.ts` |

Verdict : **utilisable tel quel** pour la position, avec trois précautions qui évitent de modifier le paquet (donc le STOP) :

1. Fournir une **clé de 32 octets aléatoires** (secret scellé `RANKING_LOCATION_KEY`), jamais un mot de passe : la dérivation SHA-256 sans sel ne convient pas à un secret de faible entropie. Une clé donnée en chaîne de 32 caractères est prise comme octets UTF-8 ; une clé hexadécimale de 64 caractères est hachée, ce qui reste acceptable si elle est aléatoire.
2. Utiliser `encrypt` (IV aléatoire), pas `encryptDeterministic` : la position n'est jamais recherchée en SQL.
3. **Lier le chiffré à la ligne** : le texte chiffré est `v1|<userId>|<lat>|<lng>` ; au déchiffrement, vérifier la version et le `userId`. Cela empêche de déplacer un chiffré d'un utilisateur à un autre et prépare une rotation de clé (`v2`).

Amélioration possible plus tard, hors V1 : ajouter l'AAD et un identifiant de clé au paquet (modification de `npm-packages`, donc STOP).

**Journal de likes : non chiffré (décision 30).** Raisons :

1. La même relation utilisateur -> post existe en clair dans le graphe (les nœuds ne portent que des identifiants et la relation `LIKE` relie deux identifiants : [10](10-feed-etat-des-lieux.md) section 2). Chiffrer notre copie n'apporte pas de protection réelle (on n'a pas vérifié un éventuel chiffrement du volume).
2. Un chiffrement déterministe avec une clé globale donne le même chiffré pour un même post chez tous les utilisateurs : une jointure entre utilisateurs resterait possible en base. Un chiffrement aléatoire casserait la clé primaire et les comparaisons.
3. Il faudrait chiffrer en mémoire tous les identifiants lus dans le graphe à chaque réconciliation et perdre la lisibilité des diagnostics SQL.

Compensations : rétention de 90 jours et pierres tombales de 7 jours, purge à la suppression du compte (section 7), accès à la base limité par les NetworkPolicies, aucun identifiant dans les journaux applicatifs. C'est une **exception documentée** à `AGENTS.md` section 6 (« toute donnée personnelle doit être chiffrée »), prise par le Lead Dev. Les tables `ranking_event_feedback`, `ranking_event_wish` et `ranking_event_mention` ne sont pas non plus chiffrées, pour les mêmes raisons.

**Limites de débit.** Ni la gateway ni les `ms-*` n'utilisent Redis ou un limiteur de débit (recherche de `Throttler`, `rate limit` et `ioredis` dans `api-gateway/src` et les `package.json`, aucun résultat) ; les seaux vivent donc dans PostgreSQL, dans `ms-ranking`, sans nouvelle infrastructure.

| Seau | Capacité | Fenêtre | Protège |
| :--- | :--- | :--- | :--- |
| `REFRESH` | 5 (`RANKING_REFRESH_BUCKET_CAPACITY`) | 60 s | `POST /ranking/refresh`, partagé entre événements et posts |
| `LOCATION` | 1 (`RANKING_LOCATION_BUCKET_CAPACITY`) | 60 s | `PUT /ranking/location` |

Table `ranking_rate_bucket(user_id uuid, bucket varchar(20), tokens numeric(6,3), updated_at timestamptz)`, clé `(user_id, bucket)`. Prélèvement atomique (paramètres : `$1` utilisateur, `$2` nom du seau, `$3` capacité, `$4` fenêtre en secondes). **Les conversions `::numeric` sont obligatoires** : sans elles, PostgreSQL déduit des entiers et `5 / 60` vaut `0` (aucune recharge) :

```sql
INSERT INTO ranking_rate_bucket AS b (user_id, bucket, tokens, updated_at)
VALUES ($1, $2, $3::numeric - 1, now())
ON CONFLICT (user_id, bucket) DO UPDATE
  SET tokens = LEAST($3::numeric, b.tokens + EXTRACT(EPOCH FROM (now() - b.updated_at)) * ($3::numeric / $4::numeric)) - 1,
      updated_at = now()
  WHERE LEAST($3::numeric, b.tokens + EXTRACT(EPOCH FROM (now() - b.updated_at)) * ($3::numeric / $4::numeric)) >= 1
RETURNING tokens;
```

Une ligne retournée = autorisé ; aucune ligne = limité. Dans ce dernier cas, `ms-ranking` n'écrit aucun job et renvoie `refreshThrottled = true` (HTTP 200) pour le rafraîchissement ; pour la position, il ignore la mise à jour. `TooManyRequestsError` (429) existe dans `@volontariapp/errors` mais n'est pas utilisée ici, pour que l'application n'affiche pas d'erreur. Tests d'intégration obligatoires : recharge d'un jeton après 12 s (capacité 5, fenêtre 60 s), six appels en rafale dont le sixième est refusé, et un test d'inférence de types sur un vrai PostgreSQL (non testé à ce jour). Les lignes sont purgées avec le compte et celles inactives depuis plus d'un jour sont supprimées lors d'une écriture.

## 4. Interface de swipe

Faits (`nativapp/src/screens/main/hooks/use-swipe-screen.ts`) :

- L'écran appelle la recherche d'événements existante (`useGetEvents`) avec `limit: 20`, les exclusions de créés, souhaités et participés, les statuts `PUBLISHED` **et `DRAFT`**, et `startDateFrom = now` (lignes 50-60, 31). Avec la décision 6, `DRAFT` devra être retiré côté application, ou l'écran migrer vers `GET /ranking/events`.
- Un préchargement est déclenché quand il reste moins de 10 cartes (ligne 30).
- Un swipe à droite appelle `wish` (lignes 88-96).
- Un swipe à gauche ne fait qu'avancer à la carte suivante : **rien n'est enregistré** (lignes 98-101).

Conception retenue :

1. **Signal négatif.** `POST /ranking/events/feedback` enregistre en lot les swipes à gauche (`PASS`), 50 éléments au plus ; l'application les envoie groupés toutes les 5 cartes, au passage en arrière-plan et au démontage. Table `ranking_event_feedback`. Le souhait (swipe à droite) reste porté par le graphe.
2. **Exclusion temporaire.** Un événement `PASS` est exclu pendant 30 jours (`RANKING_PASS_COOLDOWN_DAYS`), puis peut revenir.
3. **Ajustement entre deux lots.** L'application consomme par lots de 20. À chaque lecture, `ms-ranking` réordonne les rangs **non encore servis** du pool précalculé (100 éléments) en pénalisant le type et les tags des événements récemment passés. Les cartes déjà servies ne bougent jamais. C'est un calcul léger à la lecture, sans job de worker. Les souhaits continuent de déclencher un recalcul complet (coalescence de 30 s).
4. **Curseur opaque.** `GET /ranking/events?cursor=...&limit=20`. Le curseur encode `(listVersion, lastRank)` : la liste est une file numérotée, le curseur mémorise la version de la liste et le dernier rang servi. Comme les pénalités ne touchent que les rangs au-delà de `lastRank`, aucune carte n'est servie deux fois ni sautée. Si `listVersion` a changé (nouveau calcul), le serveur répond `versionChanged = true` et l'application repart du début ([11](11-feed-conception.md) section 8).
5. **Rafraîchissement façon Instagram.** `POST /ranking/refresh` avec `{listKind}`, appelé au rafraîchissement du profil, en fin de pile de swipe ou au redémarrage de l'application ; il demande un recalcul (`MANUAL`, file de repli) et l'application continue de lire le pool actuel en attendant la notification WebSocket. Limite : seau `REFRESH` (section 3 bis).

## 5. Popularité

Décision : un événement très populaire gagne en poids dans le classement, tant qu'il est publié et non commencé. Spécification complète et formule dans [05](05-scoring-et-jev.md) (section « Popularité »).

Entrées, toutes disponibles sans scheduler ni appel par événement :

| Entrée | Source | Fait vérifié |
| :--- | :--- | :--- |
| Souhaits | table `ranking_event_wish`, alimentée par `EVENT_SOCIAL_WISHED` et `EVENT_SOCIAL_UNWISHED` | le payload contient `eventId` (`npm-packages/packages/messaging/src/events/social/payloads.ts:49-50`) ; l'utilisateur se lit dans `userId` ou, à défaut, dans l'`emitterId` de l'enveloppe |
| Passes | table `ranking_event_feedback` | n'existe pas encore (section 4) |
| Taux de remplissage | `currentParticipants / maxParticipants`, renvoyés par `ms-event` | champs de `EventEntity` (`domain-event/src/entities/event.entity.ts:19-20`) |
| Mentions | table `ranking_event_mention`, alimentée par `POST_CREATED` | le payload porte un `eventId` optionnel et le `userId` de l'auteur (`IPostCreatedPayload`) |

Paramètres initiaux (confiance déléguée au Lead Dev pour la fenêtre et la pondération) :

| Paramètre | Valeur | Raison |
| :--- | :--- | :--- |
| Fenêtre des mentions | 14 jours | un événement est en général annoncé quelques semaines avant ; plus court, le signal est trop bruité |
| A priori sur les votes | +2 souhaits, +2 passes fictifs | un événement à deux votes ne devient pas extrême ; sans vote, `interest` = 0,5 |
| Saturation des mentions | 10 auteurs distincts | au-delà, un auteur de plus n'apporte presque rien (échelle logarithmique) |
| Poids dans la popularité | intérêt 0,4, remplissage 0,3, mentions 0,3 | l'intérêt exprimé directement pèse plus qu'un signal indirect |
| Poids dans le score | 0,10 | un coup de pouce, jamais un facteur dominant : la proximité et le goût restent premiers |
| Remise à zéro | dès que l'événement n'est plus candidat | un événement terminé ou commencé ne gagne plus rien |

Limites assumées : les souhaits et mentions antérieurs au déploiement ne sont pas rétro-alimentés ; on compte des auteurs distincts pour limiter la manipulation ; un événement sans vote reste neutre.

## 6. Codes d'explication

Chaque ligne de classement porte au plus deux codes (`reasons`), choisis parmi les composantes qui contribuent le plus au score et dépassent un seuil. L'application traduit les codes en texte ; l'identité d'un ami n'est pas exposée.

| Liste | Codes |
| :--- | :--- |
| Événements | `FRIEND_INVOLVED`, `NEAR_YOU`, `MATCHES_INTERESTS`, `STARTING_SOON`, `TRENDING` |
| Posts | `FOLLOWED_AUTHOR`, `FRIEND_AUTHOR`, `ENGAGED_AUTHOR`, `LINKED_EVENT_WISHED`, `LINKED_EVENT_JOINED`, `RECENT` |

Côté contrat, un `enum` proto (par exemple `RankingReason`) évite les chaînes libres. Colonne `reasons` dans `ranking_score` et `ranking_post_score` ([03](03-modele-de-donnees.md), [11](11-feed-conception.md)).

## 7. Suppression de compte : participation au gather

Faits (lus le 2026-10-18) :

- `requestDeletionWithUserDeleted` écrit `user.deleted` dans `event_queue` vers 5 streams : `USER_DELETED`, `SOCIAL_USER`, `USER_DELETED_POST`, `USER_DELETED_EVENT`, `USER_DELETED_STORAGE` (`domain-user/src/repositories/postgres-user.repository.ts:90-125`).
- `ws-service` crée un état de gather à la réception de `user.deleted` (`ws-service/src/post-processors/users/user-deleted.post-processor.ts:9-19`). Sa config déclare pour ce déclencheur quatre acquittements attendus (`USER_SOCIAL_DELETED`, `USER_POST_DELETED`, `USER_EVENT_DELETED`, `USER_STORAGE_DELETED`), l'événement de succès `user.deletion_successfull` et l'événement d'échec `user.deletion_failed` (`ws-service/config/default.config.json`, section `scatterGather`).
- Chaque domaine consomme son stream, purge, puis écrit un événement d'acquittement dans `event_queue` vers `ws:user-deleted-feedback` ; en cas d'échec définitif (DLQ), il écrit un événement d'échec (modèle : `post-processor-storage/src/post-processors/user-deleted.post-processor.ts:32-171`).
- Une clé non acquittée dans les 60 s est marquée en échec par le reaper, qui tourne toutes les 10 s (`ws-service/src/core/services/gather-reaper.service.ts:45-47,58-81`).
- `finalizeDeletion` n'est appelé qu'à réception de `user.deletion_successfull` (`post-processor-user/.../user-deletion-success.post-processor.ts:54`) et ne supprime que les comptes encore `PENDING_DELETION`.
- Outils : `analyze_impact user:deleted` (profondeur 3) liste les 4 post-processors de domaine (`event`, `post`, `social`, `storage`) et leurs consommateurs `ws-service`.

Étapes pour `ms-ranking` :

1. `shared` : `Streams.USER_DELETED_RANKING = 'user:deleted:ranking'`.
2. `messaging` : types `USER_RANKING_DELETED` et `USER_RANKING_DELETION_FAILED` avec payloads `{ userId }` et `{ userId, errorReason }` (modèle : `StorageEventMessagingType.USER_STORAGE_DELETED`).
3. `domain-user` : ajouter le stream aux `targetServices` de `requestDeletionWithUserDeleted`.
4. `post-processor-ranking` : `UserDeletedPostProcessor` qui purge, **pour le `user_id` du compte**, la **liste canonique** suivante : `ranking_score`, `ranking_post_score`, `ranking_run`, `ranking_request`, `ranking_like_log`, `ranking_event_feedback`, `ranking_event_wish`, `ranking_user_location`, `ranking_rate_bucket`, ainsi que `ranking_event_mention` (par `author_id`). Puis il écrit l'acquittement ; surcharge de `sendMessageToDlq` pour l'événement d'échec. Critère de test : après `user.deleted`, plus aucune ligne pour ce compte dans aucune table `ranking_*`.
5. `ws-service` : ajouter `USER_RANKING_DELETED` aux `expects` de `user.deleted`, et créer les post-processors et options de feedback correspondants (modèle : `user-storage-deleted*.post-processor.ts` et `ws-user-storage-deleted*.options.ts`, enregistrés dans le module).

**Déploiement en deux vagues (décision 36).** Si `ws-service` attend `USER_RANKING_DELETED` avant que `post-processor-ranking` existe, chaque suppression de compte échoue au bout de 60 s (inférence d'après le reaper, non testée) et le compte reste `PENDING_DELETION`, puisque `finalizeDeletion` n'est appelé que sur le succès. Vague 1 : déployer `post-processor-ranking`. Vague 2 : déployer la configuration de `ws-service`. Le code de `ws-service` s'écrit après la publication des paquets (G2, règle du STOP) mais ne se déploie qu'en vague 2.

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
| Tri de `ListPosts` | « aucun tri » | `orderBy('post.createdAt','DESC')` est présent (`domain-post/src/repositories/postgres-post.repository.ts:106`) ; le besoin de `ListRecentPostsByAuthors` reste (plusieurs auteurs, plafond par auteur) |
| Modèle de scaffolding | `ms-social` | `ms-storage` est le domaine le plus récent et traite `user.deleted` (`post-processor-storage`) |
| Feed existant | « aucun écran ne l'utilise » | confirmé : `GET_FEED_SELF` n'est que déclaré dans `nativapp/src/api/endpoints/social.endpoints.ts:318-323` |
| `sync-migrations.sh` | `ms-storage` absent | confirmé : `SERVICES=("user" "social" "post" "event")` (ligne 15) ; ajouter `"ranking"` |
| Écran de swipe | non analysé | swipe gauche non enregistré, statut `DRAFT` inclus (section 4) |
| `withFallback` | ignore 400, 404, 409 | ignore aussi 403 (`ms-event/.../base.command.controller.ts:13-16`) |

## 10. Points encore ouverts

1. Politique de conservation des données de TypeSafe AI : à obtenir avant d'activer Jev (RK-21, décision 33).
2. Limites de débit et coût réel de Jev sur un fan-out de 1 000 utilisateurs : à mesurer (RK-21).
3. Valeurs de départ des poids et de la popularité : à calibrer avec le jeu d'essai (RK-20), en cours de préparation par l'équipe.
4. Hébergement d'un modèle d'embeddings, seulement si RK-22 est réalisé ([16](16-jev-ou-embeddings.md)).
5. Comportement réel des requêtes SQL de [03](03-modele-de-donnees.md) (demande) et de la section 3 bis (seau) : non testé sur un vrai PostgreSQL.
