# 05 - Lecture et fallback

## Contrat de lecture

### RPC `ms-social`

Ajout **additif** à `ParticipationQueryService` dans `proto-registry/proto/volontariapp/social/social.services.proto` (à côté de `GetRecommendedEventIds`, ligne 96). Un ajout de RPC et de messages ne casse pas le format filaire ; à vérifier avec `buf breaking` et `analyze_grpc`.

```protobuf
rpc GetMatchedEventIds(GetMatchedEventIdsQuery) returns (GetMatchedEventIdsResponse);

message GetMatchedEventIdsQuery {
  Pagination pagination = 1;   // type de pagination existant dans le fichier
}

message MatchedEvent {
  string event_id = 1;
  double score = 2;
}

enum MatchingSource {
  MATCHING_SOURCE_UNSPECIFIED = 0;
  MATCHING_SOURCE_MATCHING = 1;          // liste Redis complete (structurel + Jev)
  MATCHING_SOURCE_STRUCTURAL_ONLY = 2;   // liste Redis sans Jev
  MATCHING_SOURCE_FALLBACK = 3;          // pas de liste, reco structurelle a la volee
}

message GetMatchedEventIdsResponse {
  repeated MatchedEvent events = 1;
  MatchingSource source = 2;
  string computed_at = 3;     // ISO 8601, vide en FALLBACK
  int32 total_count = 4;
}
```

L'identité de l'utilisateur vient du token interne (`@CurrentUser() user: AuthUser`), jamais du corps de la requête, comme pour `GetRecommendedEventIds`.

### Algorithme du handler de lecture

```text
1. essayer Redis :
     ids = ZREVRANGE matching:{userId} offset offset+limit-1 WITHSCORES
     meta = HGETALL matching:meta:{userId}
2. si Redis répond et que la liste n'est pas vide :
     renvoyer { events, source = meta.source, computedAt }
3. sinon (clé absente, liste vide, ou erreur Redis) :
     renvoyer le résultat de getRecommendedEventIds avec les filtres d'exclusion par défaut,
     source = FALLBACK, score = 0 pour chaque événement
```

Les erreurs Redis sont **attrapées et journalisées**, jamais propagées. Le chemin FALLBACK n'utilise que Neo4j, déjà requis par `ms-social`.

### Route API Gateway

Nouvelle route dans `api-gateway/src/modules/event/controllers/queries/event/event.query-controller.ts` (ou contrôleur voisin), à écrire selon la skill `volontariapp-api-gateway` :

```text
GET /events/matching?page=1&limit=20
```

Déroulé :

1. Appel `ms-social.GetMatchedEventIds` avec le token interne en métadonnée.
2. Si la réponse est vide, renvoyer `{ events: [], totalCount: 0 }` (même convention que `listEvents`).
3. Appel `ms-event` `searchEvents` avec `query.ids` = identifiants reçus (comme `listEvents`, ligne 103 et suivantes).
4. **Réordonner** le résultat selon l'ordre de `ms-social` (la recherche par identifiants ne garantit pas l'ordre), et **ignorer** les identifiants que `ms-event` ne renvoie pas (événement supprimé, terminé, non publié).
5. Enrichir avec la méthode existante `enrichSearchEventsResponse`.
6. Ajouter à la réponse un objet `matching: { source, computedAt }` et un `matchScore` par événement.

Le champ `source` permet à l'application mobile d'afficher un indicateur honnête (par exemple « recommandations personnalisées » ou « événements populaires » selon le cas) et de faire la démonstration du mode dégradé.

## Modes dégradés

| Panne | Comportement | Conséquence visible |
| :--- | :--- | :--- |
| Redis indisponible | `ms-social` attrape l'erreur, sert `FALLBACK` depuis Neo4j | liste correcte mais non personnalisée par Jev ; `source = FALLBACK` |
| Aucune liste pour l'utilisateur (compte neuf, expiration) | idem | idem ; le prochain déclencheur ou `RequestMatchingRefresh` produit la liste |
| Jev indisponible | le worker écrit une liste `STRUCTURAL_ONLY` | classement sans la dimension sémantique |
| `worker-social` arrêté | les jobs s'accumulent dans `social-queue` ; les listes existantes continuent d'être servies jusqu'à leur TTL | listes de plus en plus anciennes (visible dans `computedAt`) |
| Neo4j indisponible | `ms-social` ne peut plus servir ni le matching ni le repli : erreur gateway standard | hors périmètre, même panne que toutes les fonctions sociales |
| `ms-social` indisponible | la gateway renvoie la liste générale `searchEvents` sans tri personnalisé | dégradation totale mais l'écran reste utilisable |

La reconstruction après perte de Redis ne demande aucune action : les déclencheurs repeuplent progressivement, et `RequestMatchingRefresh` permet de forcer un utilisateur donné.

## Rafraîchissement manuel

Commande `RequestMatchingRefresh` (service de commande de `ms-social`, hors chemin de lecture) qui insère un job `social.compute_event_matching` avec `reason = MANUAL` dans `jobs_outbox`, dans la même transaction qu'une éventuelle écriture métier, et répond immédiatement. Exposée par la gateway en `POST /events/matching/refresh`. Elle contourne la garde de débounce (`MANUAL`) mais reste soumise à un plafond de fréquence côté gateway pour éviter qu'un client la martèle (par exemple 1 appel par minute et par utilisateur).

## Pagination

Le tri est fait par Redis (`ZREVRANGE` avec offset), pas en mémoire. Contrairement à `listEvents` qui demande 1000 identifiants à `ms-social` puis pagine en aval, la route de matching pagine à la source.
