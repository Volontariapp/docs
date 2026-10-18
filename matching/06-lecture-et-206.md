# 06 - Lecture et 206

## 1. Principe

| Cas | Réponse | Données |
| :--- | :--- | :--- |
| Une liste existe et n'est pas périmée | **200** | liste ordonnée |
| Une liste existe mais est périmée (âge ou version de formule) | **200** | liste ordonnée, et une demande `STALE_REFRESH` est enregistrée |
| Aucune liste pour cet utilisateur | **206 `FALLBACK_ACTIVATED`** | aucune ; une demande `ON_DEMAND` est enregistrée ; le client attend le WebSocket |
| `ms-ranking` indisponible | erreur gateway standard | aucune |

Une liste ne disparaît jamais par vieillissement : elle est **servie périmée plutôt que supprimée**. Le 206 est réservé au démarrage à froid.

## 2. Contrat gRPC (`proto-registry/proto/volontariapp/ranking/`)

Nouveau paquet sur le modèle de `social/` (`ranking.proto`, `.query`, `.command`, `.responses`, `.services`). Voir la skill `volontariapp-proto-contract-evolution`. Schéma de conception, pas du code prêt à compiler (les types communs et l'organisation exacte sont à aligner sur `proto/volontariapp/common/` et `social/social.query.proto`).

```protobuf
syntax = "proto3";
package volontariapp.ranking;

message GetRankingEventsQuery {
  volontariapp.common.PaginationRequest pagination = 1;
}

message RankingEvent {
  string event_id = 1;
  double score = 2;
  double structural_score = 3;
  optional double semantic_score = 4;
}

enum RankingSource {
  RANKING_SOURCE_UNSPECIFIED = 0;
  RANKING_SOURCE_FULL = 1;
  RANKING_SOURCE_STRUCTURAL_ONLY = 2;
  RANKING_SOURCE_COLD_START = 3;   // feed de posts sans candidat personnel
}

message GetRankingEventsResponse {
  repeated RankingEvent events = 1;
  RankingSource source = 2;
  string computed_at = 3;   // ISO 8601
  int32 total_count = 4;    // lignes de la liste, independant de la page
  bool has_more = 5;        // base sur le rang dans la liste, pas sur la longueur de la page
  bool stale = 6;           // un recalcul a ete demande
}

message RequestRankingRefreshCommand {}
message RequestRankingRefreshResponse { bool accepted = 1; }

service RankingQueryService {
  rpc GetRankingEvents(GetRankingEventsQuery) returns (GetRankingEventsResponse);
}
service RankingCommandService {
  rpc RequestRankingRefresh(RequestRankingRefreshCommand) returns (RequestRankingRefreshResponse);
}
```

L'identité vient du token interne (`@CurrentUser()`), **jamais du corps de la requête**.

## 3. Handler de lecture (`ms-ranking`)

```text
1. userId := identité du token interne
2. run := SELECT ... FROM ranking_run WHERE user_id = userId
3. si run absent :
       demander un calcul ON_DEMAND (ranking_request + jobs_outbox, file FALLBACK_RANKING),
         DANS SA PROPRE TRANSACTION, VALIDEE AVANT l'étape suivante
       lancer FALLBACK_ACTIVATED(jobType(list_kind), 'RANKING_NOT_READY')
         ou jobType('EVENT') = 'ranking.compute_user_ranking' et jobType('POST') = 'ranking.compute_user_feed'
4. lignes := SELECT ... FROM ranking_score WHERE user_id = userId ORDER BY rank LIMIT .. OFFSET ..
5. si run est périmé (âge > RANKING_STALE_AFTER_HOURS ou formula_version différente) :
       demander un calcul STALE_REFRESH (file RANKING, scheduled_at = now + 30 s)
6. renvoyer { lignes, source, computedAt, totalCount, hasMore, stale }
```

Points de rigueur (vérifiés par la revue) :

- **Le job doit être écrit hors de toute transaction qui serait annulée par la levée de l'exception.** `withFallback` (`ms-event/.../base.command.controller.ts:15-58`) écrit le job avec `repo.create` puis lève l'erreur ; si l'implémentation d'affinité enveloppe la lecture dans une transaction, l'exception annule l'insertion. On ne réutilise pas `withFallback` tel quel : l'absence de liste n'est pas une exception mais un état. On utilise la fabrique `FALLBACK_ACTIVATED` de `@volontariapp/errors-nest`.
- **Déduplication.** Un client qui réessaie en boucle ne doit pas multiplier les jobs. La table `ranking_request` ([03](03-modele-de-donnees.md) section 2) fait office de verrou de demande : un second appel, tant qu'un job récent existe pour cet utilisateur, met seulement `requested_at` à jour. Les statuts de `jobs_outbox` ne servent pas à dédupliquer, car la ligne est `COMPLETED` dès le push et n'est supprimée que par le post-processor de succès.
- **Un job peut être perdu** (section 6) ; `RANKING_REQUEST_TTL_SECONDS` permet de le réémettre à la lecture suivante.
- Un effet de bord dans une lecture est un choix assumé (même logique que `withFallback`).

## 4. Route de la gateway

Skill `volontariapp-api-gateway`. **Chemin choisi : `GET /ranking/events`** et `POST /ranking/refresh`, dans un contrôleur `@Controller('ranking')` séparé.

Raison : `EventQueryController` déclare `@Controller('events')` avec `@Get(':id')` (`api-gateway/.../event.query-controller.ts`). Une route `GET /events/ranking` enregistrée après lui serait captée par `getEvent('ranking')`. Un préfixe distinct supprime le risque ; ajouter un test de non-régression de routage.

Déroulé de `GET /ranking/events` :

1. Appel `ms-ranking.GetRankingEvents`. Un `FALLBACK_ACTIVATED` remonte tel quel (la gateway le sérialise en 206 : `errors-nest/src/filters/global-exception.filter.ts`, `PartialContentError` définie dans `errors/src/exceptions/partial-content.error.ts`).
2. Si `events` est vide, renvoyer `{ events: [], totalCount: 0 }`.
3. Appel `ms-event.searchEvents` avec `query.ids` et une **pagination explicite** égale à la taille de la page (la valeur par défaut du repository est 10).
4. **Réordonner** selon l'ordre reçu (la recherche ne garantit pas l'ordre ; son tri par défaut est `createdAt DESC`).
5. **Ignorer** les identifiants que `ms-event` ne renvoie pas.
6. **Filtrer** les événements terminés, commencés ou complets (`currentParticipants >= maxParticipants`), car aucun filtre de capacité n'existe côté `ms-event`.
7. Enrichir (`enrichSearchEventsResponse`).
8. Ajouter `ranking: { source, computedAt, stale, hasMore }` et un `rankingScore` et une liste `reasons` (codes d'explication, [13](13-decisions-v1.md) section 6) par événement.

Pagination : l'ordre vient de `rank`. Après filtrage une page peut être plus courte que `limit` ; le client **ne déduit pas la fin de liste de la longueur de la page** mais de `hasMore`, calculé à la source (`rank` suivant existant).

## 5. Comportement du client (`nativapp`)

Constats de la revue sur `nativapp/src/api/client.ts:55` : sur un 206, axios **résout** (statut 2xx), le bus global `syncPendingBus.emit(true)` est déclenché, et `response.data as TResponse` est retourné. **Le hook reçoit le corps d'erreur typé comme s'il s'agissait de données.**

| Étape | Comportement |
| :--- | :--- |
| 1 | `useRankingEvents` appelle `GET /ranking/events` (TanStack Query) |
| 2 | Le hook **discrimine** la réponse : si `data.code === 'FALLBACK_ACTIVATED'`, ce n'est pas une liste |
| 3 | 200 : afficher la liste ordonnée |
| 4 | 206 : afficher immédiatement la liste normale de la recherche d'événements existante (`GET /events`) ; noter que `syncPendingBus` a été déclenché, ce qui est probablement voulu mais à confirmer |
| 5 | À réception de la notification WebSocket de fin de job : invalider la requête et la relancer. Le handler est **idempotent** et regroupe les invalidations rapprochées (une rafale de calculs produit une rafale de notifications) |
| 6 | Si aucune notification n'arrive après 30 s : relancer une fois, puis rester sur la liste normale |

L'étape 6 est nécessaire à cause du chemin d'échec défectueux ([04](04-flux-asynchrone.md) section 10).

**À vérifier** : le format de la notification issue de `ws:jobs-outbox-success` côté `nativapp` (`src/hooks/useNotificationHandlers.ts` : `handleEventCreated`, `handleUserCreated`). Côté serveur, la notification n'est émise que si le mapping messaging existe et que `originalPayload.userId` est présent ([04](04-flux-asynchrone.md) section 9).

### Point à challenger : un 206 pour un GET

Le 206 `FALLBACK_ACTIVATED` est défini par la plateforme comme « échec non client + job de repli » (skill gateway, ligne 99), pas comme « état froid ». L'utiliser pour un GET (a) détourne son sens, (b) ajoute un effet de bord à une lecture, (c) oblige le client à discriminer le corps. Une alternative est un **200** avec `{ status: 'PENDING' }` et la même mécanique de job et de notification. La décision du Lead Dev (206) est retenue ici ; l'alternative reste documentée pour la soutenance.

## 6. Pannes et dégradations (corrigé)

Correction : la version précédente affirmait que, Redis arrêté, « les jobs restent `PENDING` et l'outbox les pousse à la reprise ». **C'est faux.** Dans `database/src/outbox/consumers/outbox.consumer.ts`, `fetchPendingItems` fait passer les lignes `PENDING` à `PROCESSING` (lignes 26-50), puis `processItems` appelle `markAsFailed` si le push vers BullMQ échoue. Le consumer ne relit que les lignes `PENDING` : **un job dont le push a échoué reste `FAILED` et n'est jamais repoussé**. Un crash entre les deux étapes laisse la ligne en `PROCESSING` indéfiniment.

| Panne | Effet | Récupération |
| :--- | :--- | :--- |
| Jev indisponible | listes `STRUCTURAL_ONLY` | automatique au calcul suivant |
| `worker-ranking` arrêté | les jobs s'accumulent dans BullMQ ; les listes existantes sont servies ; `computedAt` vieillit | traitement au redémarrage |
| **Redis (BullMQ) indisponible** | les lectures continuent (base seule) ; **les jobs dont le push échoue sont perdus** (`FAILED`) ; un utilisateur sans liste reste en attente | la lecture suivante réémet une demande une fois `RANKING_REQUEST_TTL_SECONDS` écoulé ; les listes périmées sont rafraîchies par `STALE_REFRESH` ; **alerter sur les lignes `jobs_outbox` en `FAILED` ou `PROCESSING` depuis plus de N minutes** |
| Base de `ms-ranking` indisponible | service indisponible | hors périmètre |
| `ms-social` indisponible | les calculs échouent et sont réessayés ; les lectures continuent | automatique |
| `ms-event` indisponible | calculs en échec ; la lecture gateway échoue aussi (contenu indisponible) | automatique |
| Aucune liste | 206, liste normale, notification | le calcul à la demande |

Une panne de Redis ne casse donc plus la **lecture**, mais elle peut faire perdre des demandes de calcul : le mécanisme de réémission par la lecture suivante est la compensation.

## Compléments du 2026-10-18

Routes ajoutées par les décisions de [13](13-decisions-v1.md) :

| Route | Rôle |
| :--- | :--- |
| `PUT /ranking/location` | l'application envoie la position à l'ouverture ; arrondie à 1 km, chiffrée, recalcul seulement après un déplacement de plus de 10 km |
| `POST /ranking/events/feedback` | enregistre en lot les swipes à gauche (`PASS`) |
| `GET /ranking/events?cursor=...&limit=20` | lecture par lot de 20 avec curseur et `listVersion` (à la place d'un `OFFSET`) |
| `GET /ranking/events?refresh=true` | demande un recalcul (`MANUAL`) et sert le pool actuel en attendant la notification ; limité à 5 par minute et par utilisateur (seau à jetons, [13](13-decisions-v1.md) section 3 bis) ; au-delà, `refreshThrottled = true`, HTTP 200, aucun recalcul |
| `GET /ranking/feed` | feed de posts, mêmes règles de lecture ([11](11-feed-conception.md) section 8) |
