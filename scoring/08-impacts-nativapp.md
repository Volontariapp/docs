# 08 - Impacts nativapp

Chemins sous `nativapp/src`. Marqués "exploré" : non relus ce jour.

## 1. Formulaire de création

| Fichier | Changement |
| :--- | :--- |
| `components/forms/EventInfoGrid.tsx` (exploré) | Retirer la ligne "Score d'impact" (presets 25 à 500, libre 0 à 10 000) et sa modale. Remplacer par un encart en lecture seule : "Points estimés pour les participants et pour toi". |
| `screens/event/EventFormScreen.tsx` (exploré) | Retirer `awardedImpactScore: 100` des valeurs par défaut. |
| `api/event/event.schema.ts` (exploré) | Retirer `awardedImpactScore` du schéma de création. Garder `maxParticipants` en `min(1)`. |
| `api/event/hooks/use-create-event.ts` (exploré) | Ne plus envoyer le score. |

**Estimation avant l'événement** : l'encart appelle la fonction pure `computeEventScoring` (importée de `@volontariapp/shared`) avec la durée choisie et la capacité, et un `N` supposé égal à `beta` pour afficher le maximum. Libellé honnête : "jusqu'à", car `N` réel dépend des présents.

## 2. Écran de check-in

- Dans `screens/event/EventManagementScreen.tsx` (exploré) : onglet "Participants" (`components/event/EventParticipantsTab.tsx`) avec une case par participant, active en `IN_PROGRESS`.
- Afficher le rang d'inscription provisoire parmi les cochés ("#3") pour que le créateur comprenne la règle. Le rang définitif n'est connu qu'à la clôture.
- Bouton "Terminer" : la modale de confirmation (`ConfirmStateChangeModal.tsx:58`, exploré) dit déjà que les points seront attribués aux participants confirmés. Y ajouter le nombre de présents cochés et rappeler que le check-in sera verrouillé.
- Verrouillé en lecture seule dès `FINISHED`.

## 3. Affichages de points

| Élément | Changement |
| :--- | :--- |
| `ImpactScoreBadge` sur `EventCard` et `EventDetailScreen` | Ne plus lire `awardedImpactScore` pour les nouveaux événements. Afficher "jusqu'à N points" (estimation) avant, et les points réels après `FINISHED`. |
| `ParticipantCard.tsx` | Afficher les points gagnés et, après clôture, le rang d'inscription. |
| Toast `USER_IMPACT_SCORE_CREDITED` (`hooks/useNotificationHandlers.ts:172-179`, exploré) | Inchangé. Option : afficher "(premier inscrit)" si `rank = 1` une fois `rank` dans le payload. |
| Prime du créateur | Même toast, texte "Prime d'organisation : +N points". Nécessite `role` dans le payload. |
| Textes inexacts | `EventInfoGrid` promet "attribués après validation de la présence" : sera enfin vrai. |

## 4. Rangs d'impact

`shared/lib/impact-ranks.ts` est calibré sur 100 points par événement (commentaire de calibrage, exploré). Avec la formule les gains typiques sont de 100 à 800 points par événement (voir [04](04-exemples-et-simulations.md)).

Seuils actuels : 100, 300, 700, 1 500, 3 000, 5 500, 9 000, 15 000, 25 000.

| Option | Effet |
| :--- | :--- |
| Ne rien changer | Un utilisateur franchit un rang par événement : l'échelle perd son sens. |
| Multiplier les seuils par un facteur (point de départ proposé : x3, car le gain moyen d'un événement courant est de 200 à 500) | L'échelle garde environ le même nombre d'événements par rang qu'avant. |

Le facteur définitif se choisit avec une simulation "X événements par mois pendant Y mois donne le rang Z" une fois l'exposant tranché. Les utilisateurs existants gardent leur total (aucun backfill) et peuvent donc redescendre d'un rang après le recalibrage. À assumer ou à compenser par un seuil de transition.

## 5. Tests

Mettre à jour les tests listés dans l'exploration : `impact-ranks.test.ts`, `event.schema.test.ts`, `useNotificationHandlers.test.ts`, `components/impact/__tests__/*`. Mocks dans des `*.mock.ts`, données dans des `*.factory.ts` (règles de [AGENTS.md](../../AGENTS.md), section 3).
