# 01 - État des lieux

Relevé du 2026-11-07. Un constat sans ligne a été lu dans un fichier ouvert ce jour-là, sans numéro de ligne retenu. Une **inférence** est marquée comme telle.

## 1. Application (`nativapp`)

| Besoin | Existant | Où |
| :--- | :--- | :--- |
| Position de l'utilisateur | `useLocation()` : demande la permission au montage, **une seule lecture** (`getCurrentPositionAsync`) | `nativapp/src/hooks/use-location.ts` |
| Bouton central | Onglet `create` de la barre : le bouton (`AppIconsButton`, chevron) ouvre `QuickActionsModal` au lieu de naviguer | `nativapp/src/navigation/MainAppNavigator.tsx` |
| Actions rapides | Deux actions : "Créer" et "Gérer". Props `onSelectCreate` et `onSelectManage` | `nativapp/src/navigation/components/QuickActionsModal.tsx:21-26`, `:189-243` |
| Pile racine | `MainStackParamList` : `MainTabs`, `EventDetail`, `Settings`, `Ranks`, `Badges`, `PublicProfile`, `StorageDebug`, `EventManagement` | `nativapp/src/navigation/stacks/MainStack.tsx:16-27` |
| Pile de gestion | `ManageEvents`, `ManageHub`, `EventForm`, `MyEvents`, `EventManagement`, `PostForm`, `MyPosts` | `nativapp/src/navigation/stacks/CreateEventStack.tsx:15-23` |
| Carte | `react-native-maps` 1.20.1, tuiles OSM (`UrlTile`), `AppMap`, `EventMapPrevue` | `nativapp/package.json:77`, `nativapp/src/components/map/AppMap.tsx`, `nativapp/src/screens/main/ExploreScreen.tsx` |
| Recherche d'événements | `useGetEvents(params)` en `useInfiniteQuery` ; `params` est un `Partial<SearchEventsRequest>` | `nativapp/src/api/event/hooks/use-get-events.ts:12-41` |
| Modèle d'événement | `AppEvent` : `startAt`, `endAt` (chaînes ISO), `state`, `maxParticipants`, `currentParticipants`, `location?`, `organizerId?` | `nativapp/src/api/event/event.api.ts:29-54` |
| Dates | `formatTimestamp` : chaîne, `Date` ou `{seconds}` vers ISO. **Une date absente devient l'instant présent** | `nativapp/src/api/event/event.api.ts:62-71` |
| Règle "en direct" | `isEventLive` : `maintenant` entre `startAt` et `endAt`, **ou** état `IN_PROGRESS`. **Aucun contrôle d'état dans la plage horaire** : un événement `CANCELLED` ou `FINISHED` y est "en direct" | `nativapp/src/screens/event/manage-hub.utils.ts:54-61` |
| Participations en direct | `ParticipatedScope = 'all' | 'live' | 'upcoming'` déjà utilisé par `ManageHub` | `nativapp/src/screens/event/manage-hub.utils.ts:8`, `nativapp/src/screens/event/ManageHubScreen.tsx:42` |
| Statut affiché | Un événement `PUBLISHED` dont la date est passée s'affiche "Annulé" ; `IN_PROGRESS` s'affiche "En cours" | `nativapp/src/components/event/event-status.utils.ts:33-40`, `:59-66` |
| Démarrer ou terminer à la main | L'organisateur choisit `IN_PROGRESS` ou `FINISHED` dans le détail, avec une modale de confirmation | `nativapp/src/components/event/EventDetailsTab.tsx:217`, `:240` ; `nativapp/src/components/event/ConfirmStateChangeModal.tsx:43`, `:54` ; `nativapp/src/screens/event/EventManagementScreen.tsx:44-62` |
| Participer | `useUserSocialActions()` : `participate`, `unparticipate`, avec compteur optimiste | `nativapp/src/screens/main/EventDetailScreen.tsx:192`, `:239-259` |
| WebSocket | `socketService.connect(token)` : socket.io, chemin `/api/v1/socket.io`, jeton en paramètre de requête, rafraîchi après `connect_error`. Pas de méthode `emit` : le socket s'obtient par `getSocket()` ; il est créé dans `NotificationContext` | `nativapp/src/services/socket.service.ts:27-61`, `:111` ; `nativapp/src/context/NotificationContext.tsx` |
| Requête de recherche | Les `params` axios portent `area` (objet) et `statuses` (tableau), comme le fait déjà Explore | `nativapp/src/screens/main/hooks/explore-search.utils.ts:26-37`, `nativapp/src/api/client.ts:79` |
| Texte de permission | "Nous avons besoin de votre position pour vous montrer les événements à proximité." ; la clé `locationAlwaysAndWhenInUsePermission` est déclarée sans usage en arrière-plan | `nativapp/app.json:37-40` |
| Création d'un événement | Le formulaire accepte un début à partir d'aujourd'hui 00:00, donc déjà passé dans la journée ; le back exige seulement début avant fin | `nativapp/src/api/event/event.schema.ts:26-35` ; `npm-packages/packages/domain-event/src/services/event.service.ts:81` |
| Réception | Un seul hook `useNotificationHandlers(socket, notify)` enregistre un handler par type de message et invalide les caches (anti-rafale 500 ms) | `nativapp/src/hooks/useNotificationHandlers.ts:36-71` |
| Calcul d'itinéraire | **Non trouvé** dans `nativapp/src` ni `nativapp/package.json` (recherche : osrm, openrouteservice, routes.googleapis, maplibre) | |

## 2. Recherche d'événements (back-end)

| Constat | Preuve |
| :--- | :--- |
| La route REST est `GET /events` (`listEvents`) ; elle applique d'abord le filtre social, puis appelle `searchEvents` en gRPC, puis enrichit les compteurs | `api-gateway/src/modules/event/controllers/queries/event/event.query-controller.ts:56-80`, `:187-193` |
| Le DTO gateway expose `area`, `statuses`, `startDateFrom`, `startDateTo`, `onlyAvailable`, `page`, `limit`. `startDateFrom` et `startDateTo` n'ont qu'`@ApiProperty`, **aucun validateur** ; `statuses` est converti en nombres par `@Transform` | `api-gateway/src/modules/event/dto/request/search-events.request.dto.ts:13-111` (dates `:44-48`, statuts `:50-56`, `toQuery()` `:92-111`) |
| Le `ValidationPipe` global est `{ transform: true }`, sans `whitelist` : un paramètre inconnu est ignoré, jamais rejeté | `api-gateway/src/main.ts:71` |
| La gateway conserve l'ordre renvoyé par `ms-event` (`map` puis enrichissement en place) | `api-gateway/src/modules/event/dto/response/search-events.response.dto.ts:16` ; `event-participants.service.ts` (`enrichAll`) |
| Le type de requête REST est écrit à la main dans le paquet `contracts` (pas généré depuis le proto) ; la CI de `proto-registry` ne touche jamais `src/gateway/` | `npm-packages/packages/contracts/src/gateway/event/request/search-events.request.ts:3-32` ; `ci-tools/.github/workflows/proto-sync.yml:115`, `:166`, `:174` |
| Pagination : défaut 10, **plafond 100 par écrêtage** (une valeur plus grande est ramenée à 100, jamais rejetée) | `api-gateway/src/common/pagination/pagination.constants.ts` ; `docs/architecture/ADR-Pagination.md` section 3 |
| `SearchEventsQuery` (proto) a 13 champs ; le suivant libre est le **14** | `proto-registry/proto/volontariapp/event/event.query.proto` |
| `ms-event` convertit `area` en lat, lng, rayon et passe tout à `searchAdvanced` | `ms-event/src/modules/event/controllers/queries/event.query.controller.ts:65-114` (construction de `SearchAdvancedVO` aux lignes 83-104) |
| `SearchAdvancedVO` a 14 paramètres positionnels, le dernier étant `excludedOrganizerIds`. **Seul appel de production** : `event.query.controller.ts:83` ; les autres sont des tests de `domain-event` | `npm-packages/packages/domain-event/src/value-objects/search-advanced.value-object.ts:4-20` ; `find_dependents SearchAdvancedVO` (tests compris, toutes racines) |
| Zone : `ST_DWithin` en **géographie**, rayon en mètres (à vol d'oiseau), tri par `ST_Distance` croissante puis par `id` (ordre stable) | `npm-packages/packages/domain-event/src/repositories/postgres-event.repository.ts:379-387` |
| Filtre d'état : `event.state IN (...)` | `postgres-event.repository.ts:397-399` |
| Filtres de date : **sur `startAt` seulement** (`>=` et `<=`) ; **aucun filtre sur `endAt`** | `postgres-event.repository.ts:409-415` |
| `onlyAvailable` signifie seulement `state = PUBLISHED` ; **aucun filtre de capacité** | `postgres-event.repository.ts:417-421` |
| Le filtre social est facultatif : sans option, scope `none` ; `excludeBlockedUsers` masque les événements des utilisateurs bloqués dans les deux sens | `api-gateway/src/modules/event/services/event-social-filter.service.ts:55-76` |
| Les événements reçoivent leurs coordonnées par **géocodage asynchrone** de l'adresse, dans `worker-event` (le champ `location` est réservé dans la commande de création). La colonne `location` est nullable ; un échec passe la saga de création en `FAILED`. **Inférence** : un événement sans coordonnées échoue à `ST_DWithin`, il est donc invisible dans la recherche par zone, y compris juste après sa création | `proto-registry/proto/volontariapp/event/event.command.proto:14` ; `npm-packages/packages/domain-event/src/services/geocoding/geocoding.service.ts:16-27` ; `workers-runners/worker-event/src/app.module.ts:92-95` ; `npm-packages/packages/domain-event/src/models/event.model.ts:38-44` ; `ws-service/src/post-processors/events/geocoding-failed.post-processor.ts` |
| Un événement créé est `PUBLISHED` d'emblée | `ms-event/src/modules/event/transformers/event.transformer.ts:54` |

## 3. Participation et capacité

| Constat | Preuve |
| :--- | :--- |
| `participateEvent` vérifie : l'événement existe, la participation n'existe pas encore ; il supprime un souhait éventuel puis crée la participation. **Aucun contrôle de capacité, aucun contrôle d'état** | `npm-packages/packages/domain-social/src/services/participation.service.ts:160-184` |
| `ms-event` ne compte pas les participants. La gateway remplit `currentParticipants` depuis `ms-social` (`CountEventParticipants`), avec `+1` pour le créateur (participant implicite) | `api-gateway/src/modules/event/services/event-participants.service.ts:17-19`, `:62-68` |
| Si le comptage échoue, l'erreur est seulement journalisée et la valeur reçue de `ms-event` reste (**inférence** : 0, donc un événement complet paraît libre) | `event-participants.service.ts:55-60` |
| `maxParticipants` vaut au moins 1 **à la création**. Des données anciennes peuvent valoir 0 : la gateway (ranking) traite 0 comme "sans limite". Règle retenue (décision D19) : complet signifie `maxParticipants > 0` et `currentParticipants >= maxParticipants` | `ms-event/src/modules/event/dto/request/command/create-event.command.dto.ts:44-46` ; `api-gateway/src/test/unit/modules/ranking/ranking-helpers.unit.spec.ts:146` |
| Il n'existe **aucun RPC booléen** "cet utilisateur participe-t-il à cet événement". RPC de lecture : `GetUserEvent` (mes événements créés), `GetUserParticipateEvent` (mes participations, paginé), `GetEventParticipants` (ids paginés d'un événement), `CountEventParticipants`, `GetEventAttendees` (présences). La gateway parcourt déjà `GetUserParticipateEvent` avec `fetchAllPages` pour l'appelant | `proto-registry/proto/volontariapp/social/social.services.proto:89-104` ; `social.query.proto:119-122`, `:170-173` ; `api-gateway/src/modules/event/services/event-social-filter.service.ts:105-110` |

## 4. États d'un événement

| Constat | Preuve |
| :--- | :--- |
| `EventState` : `UNSPECIFIED`, `DRAFT`, `PUBLISHED`, `IN_PROGRESS`, `FINISHED`, `CANCELLED` | `proto-registry/proto/volontariapp/event/event.proto:14-21` |
| `changeState` est **réservé à l'organisateur ou à un admin** ; aucune transition automatique | `npm-packages/packages/domain-event/src/services/event.service.ts:199-245` (contrôle aux lignes 208-210) |
| Le seul job qui change un état est `fallback-change-event-state` : repli `withFallback` de la route de changement d'état, il rejoue le `changeState` demandé quand `ms-event` est indisponible (sans `actorId`, donc sans contrôle d'organisateur, par construction) | `workers-runners/worker-event/src/workers/handlers/fallback/fallback-change-event-state.handler.ts:36-37` ; `api-gateway/src/modules/event/controllers/commands/event/event.command-controller.ts:106` |
| Couverture de la recherche d'un autre changement d'état : `analyze_grpc ChangeEventState` (1 client : la gateway ; 1 handler : `ms-event`) ; recherche des états `IN_PROGRESS` et `FINISHED` hors tests, migrations et contrats, **dépôt par dépôt** sur les 12 dépôts de code (`npm-packages`, `api-gateway`, `ms-event`, `ms-post`, `ms-social`, `ms-storage`, `ms-user`, `ms-ranking`, `ws-service`, `outbox-runners`, `post-processors-runner`, `workers-runners`) ; `CronJob` de `deploy` (seul `ms-storage` en a un, pour la purge). `FINISHED` : posé par `changeState`, le repli ci-dessus et le seed. **Non vérifié** : un `UPDATE` SQL d'état hors migrations | recherches du 2026-11-07 ; `api-gateway/src/modules/system/services/interaction-seed.service.ts:376` pour le seed ; `deploy/apps/base/ms-storage/cronjob-purge.yaml` |

**Conséquence :** un événement `PUBLISHED` ne passe jamais de lui-même à `IN_PROGRESS` ni à `FINISHED`. Les événements expirés restent `PUBLISHED` (l'app les affiche "Annulé"). La recherche doit donc se faire sur une fenêtre de dates et filtrer la fin côté client.

## 5. WebSocket

| Constat | Preuve |
| :--- | :--- |
| `ws-service` authentifie **à la connexion seulement** (jeton interne ou jeton d'accès), place le socket dans la **room du `userId`**, ferme les sockets précédents du même utilisateur (un seul appareil connecté à la fois). `client.data.userId` est posé en fin de `handleConnection`, après plusieurs `await` | `ws-service/src/gateways/app.gateway.ts:37-84` (fermeture `:60-68`, join `:70`, `userId` `:71`), lu sur `origin/main` |
| Le jeton interne porte l'identité d'un **utilisateur** (`signInternal(user)`), pas celle d'un service ; il circule dans toutes les métadonnées gRPC | `npm-packages/packages/auth/src/services/jwt.service.ts:118` ; `npm-packages/packages/auth/src/services/grpc-metadata.helper.ts:15` |
| `ws-service` n'a aucun contrôleur HTTP aujourd'hui, mais tourne sur un serveur Express Nest (`NestFactory.create`, `app.listen`, adaptateur Redis pour socket.io) | `ws-service/src/main.ts` ; dépendance `@nestjs/platform-express` |
| **Aucun handler entrant** (`SubscribeMessage`) dans `ws-service/src` hors tests ; pas de room par événement | recherche du 2026-11-07 |
| Envoi : `notifyUser(userId, type, payload)`, `broadcast`, `broadcastExcept` ; `notifyUser` ignore un utilisateur non suivi dans Redis | `ws-service/src/gateways/notification.service.ts:15-45` |
| Redis : `SocketManagerService` suit les utilisateurs connectés (clé `ws_users`) via `NestRedisProvider` | `ws-service/src/core/services/socket-manager.service.ts` |
| Le registre de contrats WebSocket ne contient que des messages **serveur vers client** ; types regroupés par domaine (`events`, `users`, `posts`, `storage`, `common`) | `npm-packages/packages/messaging/src/websockets/index.ts` (`WebsocketEventRegistry`, `WebsocketMessagingType`) |
| Le proxy de la gateway intercepte la montée en protocole, vérifie le jeton, fabrique un jeton interne (`signInternal`) et le transmet. Il n'est monté que sur `socket.io` et `socket.io/*`, et réécrit le chemin vers `/socket.io`. **Inférence, non testée** : ensuite c'est un tunnel, donc les messages entrants le traversent | `api-gateway/src/modules/ws-proxy/ws-proxy.middleware.ts:39-46`, `:93-144` ; `ws-proxy.module.ts:14-17` |
| Le journal masque des clés (`password`, `token`, `email`...) et trois motifs (e-mail, JWT, Bearer). **Ni `latitude` ni `longitude`**. Les clés sont cherchées par sous-chaîne ; la configuration accepte des clés supplémentaires (`masking.keys`) | `npm-packages/packages/logger/src/masking.ts:4-28`, `:75-78` ; `logger.ts:11-12` |
| La gateway connaît l'URL de `ws-service` (`msWsUrl`) | `ws-proxy.middleware.ts:35` |

## 6. Réseau en production

| Constat | Preuve |
| :--- | :--- |
| Sortie autorisée de la gateway : `ms-user`, `ms-post`, `ms-social`, `ms-event`, `ws-service`, `ms-storage`, `ms-ranking`, plus le DNS. **Pas de Redis** | `deploy/infrastructure/security/network-policies/overlays/prod/api-gateway.yaml:18-47` |
| Entrée autorisée de `ws-service` : `api-gateway`, mais aussi les `ms-*`, workers et post-processors (21 sources). Sortie : `ms-event`, `ms-post`, `ms-social`, `ms-user`, PostgreSQL, **Redis** (`ws-service-redis` et `redis`), DNS | `deploy/infrastructure/security/network-policies/overlays/prod/ws-service.yaml:14-47`, `:48-81` |
| La sortie de la gateway vers `ws-service` n'a pas de restriction de port | `api-gateway.yaml:32-34` |
| `api-gateway/package.json` déclare `@volontariapp/bridge-nest` (lignes 47 et 79) mais aucun fichier de `api-gateway/src` ne mentionne Redis | recherche du 2026-11-07 |

## 7. Données de démo

Le seed d'événements tire la date de début soit entre **1 et 90 jours dans le passé**, soit entre **1 et 180 jours dans le futur**, avec une durée de 2 à 5 heures : **jamais un événement en cours** (`api-gateway/src/modules/system/services/event-seed.service.ts:95-106`, création aux lignes 137-155). Les adresses viennent d'une liste d'Île-de-France et sont géocodées de façon asynchrone par `worker-event` (section 2). Le formulaire de l'app permet aussi de créer un événement en cours (section 1).

## 8. Trajet à pied : mesure du 2026-11-07

Même trajet (2.3522,48.8566 vers 2.3376,48.8606, Paris), requêtes avec un User-Agent explicite :

| Hôte | Distance | Durée | Vitesse moyenne | Lecture |
| :--- | :--- | :--- | :--- | :--- |
| `router.project-osrm.org/route/v1/foot/...` | 1140 m | 205,8 s | environ 20 km/h | **voiture** : le profil `foot` est ignoré |
| `routing.openstreetmap.de/routed-foot/route/v1/foot/...` | 1256,5 m | 1007,5 s | environ 4,5 km/h | marche |

Relecture du 2026-11-07 (une requête chacune) : `route` avec `overview=full&geometries=geojson` renvoie `code: Ok`, 1256,5 m, 1007,5 s et une `LineString` de 118 points **en ordre [longitude, latitude]** ; `table` avec `sources=0&annotations=duration` renvoie `durations [[0, 1005.5, 2381.2]]` pour trois points.

Vitesse de repli retenue si OSRM est indisponible : **1,25 m/s** (valeur mesurée ci-dessus). D'après le wiki OSRM : 1 requête par seconde au plus, usage raisonnable et non commercial, aucune garantie de disponibilité, User-Agent identifiant l'application. D'après la page des plans d'OpenRouteService : offre gratuite de 2000 requêtes par jour et 40 par minute pour les directions (non confirmé pour le profil piéton).

## 9. Non vérifié

Voir [06](06-risques-et-verifications.md).
