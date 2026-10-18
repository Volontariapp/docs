# 15 - Application (`nativapp`) : périmètre et plan

Ticket RK-19 de [14](14-plan-d-implementation.md). **À faire en dernier**, après la publication de l'API (RK-17) : l'application consomme des routes qui doivent exister. Règle de `nativapp/CLAUDE.md` : lire d'abord les skills de `nativapp/.agents/skills/` (`rn-architecture`, `rn-clean-code`, `rn-data-fetching`, `rn-forms`, `rn-styling`, `rn-verification`, `react-doctor`, `rn-stability`) et lancer `graphify update .` après modification.

## 1. Périmètre

| Dans le chantier | Hors chantier (ne pas casser) |
| :--- | :--- |
| Écran de swipe branché sur le classement | La **carte** (`ExploreScreen`, `use-explore-screen.ts`) : reste telle quelle |
| Feed de posts de l'accueil | Recherche d'événements, sélecteur d'événement d'un post, profil public |
| Position, retour `PASS`, rafraîchissement, notification | Affichage des codes d'explication (décision : on les reçoit, on ne les montre pas pour l'instant) |

## 2. État actuel (faits relevés le 2026-10-18)

- `useGetEvents` (`src/api/event/hooks/use-get-events.ts`) appelle `GET /events` par pages et est partagé par l'écran de swipe (`use-swipe-screen.ts:10,62`), la carte (`use-explore-screen.ts:11`), le profil public et le sélecteur d'événement (`components/post/use-event-picker-search.ts`). **Il ne doit pas changer de signature.** Le classement passe par de nouveaux hooks.
- Swipe : lots de 20, préchargement quand il reste 10 cartes, statuts `PUBLISHED` **et `DRAFT`**, swipe à droite appelle `wish`, swipe à gauche n'enregistre rien (`use-swipe-screen.ts:30-31,50-60,88-101`).
- Position de l'appareil : `useLocation` (`@/hooks/use-location`), déjà utilisé par le swipe et la carte.
- Accueil : `HomeScreen.tsx` lit les posts avec `useListPosts` (`src/api/post/hooks/use-list-all-posts.ts`, import ligne 8).
- Client HTTP : `apiFetch` (`src/api/client.ts`) ; sur un **206**, il émet `syncPendingBus.emit(true)` et **retourne le corps comme s'il s'agissait de données** (lignes 55 à 59). Le hook doit donc discriminer `data.code === 'FALLBACK_ACTIVATED'`.
- Notifications WebSocket : `src/hooks/useNotificationHandlers.ts`, un `socket.on(WebsocketMessagingType.X, handler)` par type.
- Le feed existant `GET_FEED_SELF` (`src/api/endpoints/social.endpoints.ts:318-323`) n'est utilisé nulle part : le laisser.

## 3. Changements

| # | Changement | Détail |
| :--- | :--- | :--- |
| N1 | Couche API `src/api/ranking/` | `ranking.api.ts` (via `apiFetch`, jamais `axios`), types issus de `@volontariapp/contracts`, hooks `use-ranking-events` (infini, par curseur), `use-ranking-feed`, `use-record-event-feedback`, `use-update-location`, `use-request-ranking-refresh`. Clés de requête : `['ranking', 'events']`, `['ranking', 'feed']` |
| N2 | Gestion du 206 | si `data.code === 'FALLBACK_ACTIVATED'` : afficher la liste normale (`useGetEvents` pour les événements, `useListPosts` pour les posts) en attendant `RANKING_READY` |
| N3 | Écran de swipe | source des cartes = `use-ranking-events` ; **retirer `DRAFT`** ; le swipe à droite garde `wish` ; le swipe à gauche met l'identifiant dans un tampon envoyé en lot (`POST /ranking/events/feedback`) toutes les 5 cartes, au passage en arrière-plan et au démontage ; en cas d'échec le tampon est conservé et renvoyé |
| N4 | Position | à l'ouverture et au retour au premier plan, si la permission est accordée, `PUT /ranking/location` ; aucun appel si la permission est refusée ; la position n'est pas arrondie côté application (le serveur arrondit à 1 km) |
| N5 | Rafraîchissement | tirer pour rafraîchir sur l'accueil, fin de pile sur le swipe, redémarrage de l'application : `refresh=true`. La réponse porte `refreshThrottled` : si vrai, afficher la liste actuelle sans message d'erreur |
| N6 | Notification `RANKING_READY` | nouveau `socket.on` : invalider `['ranking']` avec un regroupement d'environ 1 s ; **ne pas recharger automatiquement une liste en cours de lecture** : afficher un bandeau ou recharger au retour sur l'écran ([11](11-feed-conception.md) section 8) |
| N7 | Accueil | `HomeScreen` lit `use-ranking-feed` avec repli sur `useListPosts` en cas de 206 ou d'erreur |
| N8 | Codes d'explication | types et table de correspondance code -> texte présents dans le code, **non affichés** en V1 |
| N9 | Non-régression | tests existants de la carte, du sélecteur d'événement et du profil public inchangés ; `useGetEvents` non modifié |

## 4. Parcours à vérifier à la main

1. Compte neuf : l'accueil et le swipe affichent la liste normale (206), puis basculent après la notification.
2. Utilisateur avec historique : le swipe montre d'abord les événements proches et populaires ; un swipe à gauche ne revient pas avant 30 jours.
3. Refus de la géolocalisation : le swipe fonctionne, sans appel à `PUT /ranking/location`.
4. Six rafraîchissements en une minute : le sixième ne recalcule pas et n'affiche aucune erreur.
5. Ouvrir la carte : comportement identique à avant.
