# 03 - nativapp

Périmètre : tout ce qui change dans `nativapp`. Avant toute tâche front, lire les huit skills exigées par `nativapp/CLAUDE.md` (`rn-architecture`, `rn-clean-code`, `rn-data-fetching`, `rn-forms`, `rn-styling`, `rn-verification`, `react-doctor`, `rn-stability`). Mocks dans `*.mock.ts`, factories dans `*.factory.ts`, `jest.spyOn` avec `restoreAllMocks()`, aucun `any`, aucun `as unknown as`.

## 1. Parcours

```mermaid
flowchart TD
  A[Bouton central] --> B[QuickActionsModal : action Rejoindre un direct]
  B --> C[Ecran LiveEvent]
  C --> D{Permission position ?}
  D -->|refusee| E[Message : localisation refusee]
  D -->|accordee| F[Position fraiche]
  F --> G[GET events : zone 2 km, fenetre de dates]
  G --> H[Filtre client : en cours, assez de temps]
  H --> I[Durees de marche OSRM]
  I --> J{Resultat ?}
  J -->|aucun| K[Message : aucun evenement en direct autour de vous]
  J -->|au moins un| L[Liste : 3 joignables plus complets en grise]
  L --> M[POST participate]
  M --> N[Section Mon evenement : trace et temps restant]
```

## 2. Fichiers

Les chemins suivent les conventions existantes (`src/api/event/hooks/use-*.ts`, `*.utils.ts`, écrans exportés par `@/screens`).

| Action | Fichier | Rôle |
| :--- | :--- | :--- |
| Créer | `src/api/event/live-events.utils.ts` | Constantes, distance à vol d'oiseau, filtre et séparation joignables / complets (fonctions pures) |
| Créer | `src/services/routing.service.ts` | Client OSRM piéton : durées (une requête), tracé (une requête), file d'attente, cache, repli |
| Créer | `src/hooks/use-current-position.ts` | Position fraîche **à la demande** (`refresh()`), états de permission |
| Créer | `src/api/event/hooks/use-nearest-live-events.ts` | Orchestration : position, recherche, filtre, durées, séparation |
| Créer | `src/screens/event/LiveEventScreen.tsx` et `src/screens/event/hooks/use-live-event-screen.ts` | Écran commun et sa logique |
| Créer | `src/components/event/live/` : `LiveCandidateCard.tsx`, `LiveFullEventsSection.tsx`, `LiveMyEventSection.tsx`, `LiveRouteMap.tsx` | Composants de l'écran |
| Modifier | `src/navigation/components/QuickActionsModal.tsx` | Props `onSelectLive` et `hasLiveParticipation` ; troisième action |
| Modifier | `src/navigation/MainAppNavigator.tsx` | Handler `navigation.navigate('LiveEvent')` ; calcul de `hasLiveParticipation` |
| Modifier | `src/navigation/stacks/MainStack.tsx` | Route `LiveEvent: undefined` dans `MainStackParamList` et dans le navigateur |
| Modifier | `src/screens/index.ts` | Export de `LiveEventScreen` |
| Palier 4 | `src/hooks/use-live-sharing.ts`, `src/hooks/use-live-organizer-positions.ts`, `src/api/live/live.api.ts` | Partage de position et carte de l'organisateur |

## 3. Types et constantes

```ts
// src/api/event/live-events.utils.ts
export const LIVE_SEARCH_RADIUS_M = 2000;
export const LIVE_SEARCH_LIMIT = 30; // maximum accepté par la gateway : 100
export const LIVE_START_LOOKBACK_MS = 24 * 60 * 60 * 1000;
export const LIVE_MIN_USEFUL_PRESENCE_MS = 15 * 60 * 1000; // décision Q5
export const LIVE_MAX_WALK_S = 30 * 60; // décision Q4
export const LIVE_MAX_JOINABLE = 3;
export const LIVE_MAX_FULL_SHOWN = 2; // décision Q6
export const LIVE_MAX_ROUTING_CANDIDATES = 8;
export const WALKING_SPEED_MPS = 1.25; // repli, mesuré le 2026-11-07

export type LiveCandidateAvailability = 'JOINABLE' | 'FULL';

export interface LiveEventCandidate {
  event: AppEvent;
  distanceMeters: number;
  walkSeconds: number;
  availability: LiveCandidateAvailability;
  /** true quand OSRM est indisponible : durée estimée à vol d'oiseau. */
  isEstimated: boolean;
}

export interface LiveEventsResult {
  joinable: LiveEventCandidate[]; // trié par walkSeconds croissant, LIVE_MAX_JOINABLE au plus
  full: LiveEventCandidate[]; // LIVE_MAX_FULL_SHOWN au plus
}

export type LiveScreenStatus =
  | 'locating'
  | 'searching'
  | 'ready'
  | 'empty'
  | 'permission_denied'
  | 'error';
```

```ts
// src/services/routing.service.ts
export interface Coordinates { latitude: number; longitude: number }

export interface WalkingRoute {
  distanceMeters: number;
  durationSeconds: number;
  geometry: Coordinates[]; // pour <Polyline>
}

export interface WalkingDurations {
  /** Même ordre que les destinations ; null si OSRM n'a pas pu router cette destination. */
  durationsSeconds: (number | null)[];
}

export interface RoutingService {
  fetchWalkingDurations(origin: Coordinates, destinations: Coordinates[], signal?: AbortSignal): Promise<WalkingDurations>;
  fetchWalkingRoute(origin: Coordinates, destination: Coordinates, signal?: AbortSignal): Promise<WalkingRoute>;
}
```

## 4. Requête de recherche

Route : `GET /events`, via `eventApi.getEvents` et `useGetEvents` (le hook existant est une `useInfiniteQuery` ; pour ce besoin une page suffit, donc créer un hook dédié `use-nearest-live-events` qui appelle `eventApi.getEvents` avec `page: 1`).

| Paramètre | Valeur | Raison |
| :--- | :--- | :--- |
| `area` | centre : position fraîche ; `radiusMeters`: 2000 | D2 |
| `statuses` | `[EVENT_STATE_PUBLISHED, EVENT_STATE_IN_PROGRESS]` | aucun job ne passe à `IN_PROGRESS` : un événement en cours est souvent encore `PUBLISHED` |
| `startDateFrom` | maintenant moins 24 h (ISO 8601) | écarter les événements anciens restés `PUBLISHED` |
| `startDateTo` | maintenant (ISO 8601) | l'événement a commencé |
| `endAtFrom` | maintenant (ISO 8601), **après le palier 3 seulement** | supprime la troncature ; avant, le filtre de fin est fait côté client |
| `onlyAvailable` | `false` | il n'accepte que `PUBLISHED` et ne filtre pas la capacité |
| `excludeBlockedUsers` | `true` | sécurité : événements des utilisateurs bloqués masqués |
| `excludeParticipatedByMe`, `excludeCreatedByMe` | `true` | ces événements sont dans "Mon événement" |
| `page`, `limit` | `1`, `30` | maximum gateway : 100 |

**Limite connue :** avec `startDateTo = maintenant`, un événement que l'organisateur a démarré **avant** son heure de début n'est pas trouvé. Rare ; accepté.

## 5. Règle de sélection

Pure, testée, dans `live-events.utils.ts`.

1. Garder `isEventLive(event, now)` **et** `endAt > now` (garde-fou : `isEventLive` compte aussi un `IN_PROGRESS` dont la fin est dépassée) **et** `location` définie.
2. Trier par distance à vol d'oiseau croissante, garder `LIVE_MAX_ROUTING_CANDIDATES`.
3. Obtenir les durées de marche d'OSRM (une requête pour tous les candidats). En cas d'échec : `distance / WALKING_SPEED_MPS`, `isEstimated = true`.
4. Écarter si `walkSeconds > LIVE_MAX_WALK_S`.
5. Écarter si `endAt - now < walkSeconds * 1000 + LIVE_MIN_USEFUL_PRESENCE_MS`.
6. `availability = FULL` si `currentParticipants >= maxParticipants`, sinon `JOINABLE`.
7. Trier chaque groupe par `walkSeconds`, tronquer à `LIVE_MAX_JOINABLE` et `LIVE_MAX_FULL_SHOWN`.

## 6. Écrans

```text
Bouton central : actions rapides

+------------------------------------------+
| ACTIONS RAPIDES                      x   |
| Que souhaitez-vous faire ?               |
|                                          |
| [+]  Créer                               |
|      Organiser un événement ou un post   |
|                                          |
| [=]  Gérer                               |
|      Mes événements, participations      |
|                                          |
| [>]  Rejoindre un direct                 |
|      Événement en cours autour de vous   |
+------------------------------------------+
```

Si `hasLiveParticipation` : titre "Mon événement en direct", sous-titre "Voir le trajet, le temps restant". La carte est ancrée en bas : l'ajout d'une ligne ne déplace pas le bouton.

```text
Écran LiveEvent (racine de MainStack, plein écran, sans barre d'onglets)

+------------------------------------------+
| <  Événements en direct                  |
+------------------------------------------+
| MON ÉVÉNEMENT (si je participe)          |
|  Nettoyage des berges        EN COURS    |
|  Fin dans 1 h 20 - 42 participants       |
|  [ Trajet ]  [ Détail ]  [ Mes évts ]    |
+------------------------------------------+
| AUTOUR DE MOI (2 km à pied)              |
|  1. Collecte alimentaire    8 min  12/20 |
|  2. Atelier vélo           14 min   9/10 |
|  3. Cueillette urbaine     19 min   3/15 |
|                                          |
| Autres événements (complets)             |
|  -  Marche solidaire       11 min  25/25 |
+------------------------------------------+
```

Les noms et chiffres sont fictifs. Réutilisations : `isEventLive` et `getEventStatusConfig` (badge "En cours"), `useUserSocialActions` (`participate`), `AppMap` et `EventMapPrevue`, `use-get-participated-events` et `use-get-my-events` pour la section "Mon événement". Le bouton "Mes évts" ouvre `ManageHub` (onglet participations) ; filtrer sur la portée "en direct" demande d'ajouter la portée aux paramètres de navigation (aujourd'hui `MainStackParamList.MainTabs` n'accepte que `initialTab`).

États (`LiveScreenStatus`) : `locating`, `searching`, `ready`, `empty` ("Aucun événement en direct autour de vous"), `permission_denied` (même présentation que `ExploreScreen`), `error` (bouton "Réessayer").

## 7. Service de trajet (OSRM)

| Point | Valeur |
| :--- | :--- |
| Hôte | `https://routing.openstreetmap.de/routed-foot` (jamais `router.project-osrm.org` : il calcule en voiture) |
| Coordonnées | ordre **longitude,latitude** dans l'URL |
| Durées | un appel au service `table` avec la source et toutes les destinations (**à tester**, [06](06-risques-et-verifications.md) V4) ; repli : un appel `route` par candidat, espacés |
| Tracé | un appel `route` avec `overview=full&geometries=geojson` (**à tester**) pour le seul candidat choisi |
| Cadence | une requête à la fois, 1,1 s au minimum entre deux requêtes (limite publique : 1 par seconde) |
| En-tête | `User-Agent` identifiant l'application (exigé par la politique d'usage ; **à vérifier** que React Native l'envoie tel quel) |
| Cache | 60 s par couple (origine arrondie à 4 décimales, destination) |
| Échec | repli à vol d'oiseau (`WALKING_SPEED_MPS`), `isEstimated = true`, indication "estimé" dans l'interface |

## 8. Partage de position (palier 4)

Côté personne qui partage :

- bascule "Partager ma position avec l'organisateur" sur la carte de l'événement suivi, **désactivée par défaut**, avec le texte de consentement : "Partager ma position avec l'organisateur jusqu'à mon arrivée. Position approximative (environ 100 m), visible de l'organisateur seul, jamais conservée." ;
- activation : `PUT /live/events/:eventId/sharing` puis, en cas de succès, `Location.watchPositionAsync` avec un intervalle de 30 s (Q7) ;
- chaque position est **arrondie à 3 décimales** (environ 111 m en latitude) avant envoi, puis émise par `socket.emit('live.position', { eventId, latitude, longitude })` ;
- arrêt automatique : réception de `live.sharing_stopped`, passage de l'app en arrière-plan (`AppState`), départ de l'événement, fin de l'événement, démontage de l'écran. L'arrêt appelle `DELETE /live/events/:eventId/sharing` ;
- permission **foreground uniquement** (déjà utilisée) : aucune permission d'arrière-plan.

Côté organisateur : dans `EventManagementScreen` (onglet participants), une carte affiche les positions reçues via `live.positions_updated` quand l'événement est en direct. La carte démarre vide et se remplit à chaque mise à jour (au plus 30 s de délai pour le premier point).

Branchement : un hook dédié (`use-live-organizer-positions`) enregistre ses handlers sur le socket. Ne pas agrandir `useNotificationHandlers.ts` (fichier déjà très long, un seul gros effet).

## 9. Tests

- `live-events.utils.test.ts` : chaque étape de la règle de sélection, cas limites (`endAt` manquant, `IN_PROGRESS` expiré, complet exactement à la capacité, aucun candidat, tous écartés par la marche).
- `routing.service.test.ts` : parsing de la réponse OSRM, file d'attente et cadence, cache, repli sur erreur réseau et sur code OSRM différent de `Ok`.
- `use-nearest-live-events.test.tsx` : états du hook avec React Query de test, annulation au démontage.
- `LiveEventScreen` : un test par état de `LiveScreenStatus`.
- `QuickActionsModal` : libellé selon `hasLiveParticipation`, appel de `onSelectLive`.
- Pas de test E2E en local : pousser et lire le job CI `e2e`.

## 10. Critères d'acceptation

- Sans événement en cours dans 2 km : message "Aucun événement en direct autour de vous".
- Avec trois événements joignables et un complet : trois cartes triées par temps de marche, et le complet dans la section grisée, sans bouton de participation.
- Un événement qui finit avant l'arrivée plus 15 min n'apparaît pas.
- OSRM coupé : la liste s'affiche avec la mention "estimé".
- Permission refusée : message, aucune requête envoyée.
- Participer met à jour le compteur et fait apparaître l'événement dans "Mon événement".
