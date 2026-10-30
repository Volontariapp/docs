# 03 - Formule

## 1. Paramètres

| Symbole | Sens | Source |
| :--- | :--- | :--- |
| `N` | Nombre de participants **présents** validés | `checked_in_at` non nul, voir [05](05-modele-de-donnees-et-checkin.md) |
| `beta` | Capacité maximale (`maxParticipants`, doit être `>= 1`) | `events.maxParticipants` |
| `alpha` | Coefficient de durée | table de paliers ci-dessous |
| `i` | Rang d'inscription parmi les présents (1 à `N`), trié par `registered_at` croissant | `registered_at` |
| `e` | Exposant de décroissance, fixé à 0,3 | constante versionnée (voir [04](04-exemples-et-simulations.md), section 3) |
| `MIN_ATTENDEES_FOR_ORGANIZER_POINTS` | Seuil de présents pour verser la prime du créateur, fixé à 3 (anti-Sybil) | constante de `@volontariapp/shared` |

## 2. Paliers de `alpha` (à valider)

La durée est `endAt - startAt`. Les durées libres du formulaire (0,5 à 720 h) sont toujours couvertes.

| Durée | `alpha` | Cas typique |
| :--- | :--- | :--- |
| `<= 2 h` | 1,0 | Atelier |
| `<= 4 h` | 1,5 | Demi-journée |
| `<= 24 h` | 2,5 | Journée |
| `> 24 h` | 4,0 | Week-end |

> [!WARNING]
> Une journée de 8 h et un événement de 24 h donnent le même `alpha`, et un événement de 30 jours aussi que le week-end. Si cela pose problème, plafonner la durée admise ou ajouter un palier.

## 3. Gain du créateur

```text
P_createur = arrondi( 150 x alpha x (1 + N / beta) )   si N >= 3
P_createur = 0                                         si N < 3
```

Le seuil de 3 présents (`MIN_ATTENDEES_FOR_ORGANIZER_POINTS`) empêche un créateur d'encaisser la prime avec un ou deux comptes complices (voir [10](10-plan-de-livraison-et-risques.md)).

## 4. Prize pool et points des participants

```text
P   = N x 100 x alpha x (1 + N / beta)
w_i = 1 / i^e
C   = 2 x P / N                      (plafond : +100 % de la moyenne)
```

Répartition par plafonnement itératif (water-filling) :

1. Toutes les parts sont d'abord `P x w_i / S` avec `S` la somme des `w_k`.
2. Toute part au-dessus de `C` est ramenée à `C`.
3. L'excédent est redistribué aux rangs non plafonnés, proportionnellement à leurs poids `w_i`.
4. On répète les étapes 2 et 3 jusqu'à ce qu'aucune part ne dépasse `C`.
5. Les parts réelles sont arrondies au plus grand reste (section 5).

Le résultat est monotone non croissant : le rang 1 touche au moins autant que le rang 2, etc. Plusieurs rangs peuvent être à égalité au plafond (au Festival, les rangs 1 à 6 touchent 1 600). Le plafond s'applique à **chaque** rang, pas seulement au premier ([04](04-exemples-et-simulations.md), section 3).

Le pool moyen par participant est `100 x alpha x (1 + N/beta)`, soit de 100 (très peu rempli, 1 h) à 800 (plein, week-end).

## 5. Arrondi

L'arrondi simple fait dériver la somme des `P_i` par rapport à `P` (jusqu'à 4 points à N=200). Règle retenue : méthode du plus grand reste, appliquée aux parts déjà plafonnées (parties entières, puis les points manquants aux plus grandes parties fractionnaires, à égalité le rang le plus petit d'abord). La somme vaut alors exactement `P`, ce qui rend la distribution auditable.

## 6. Cas limites

| Cas | Règle proposée |
| :--- | :--- |
| `N = 0` | Aucun point, y compris pour le créateur. |
| `N = 1` | Le seul présent touche `P` entier (120 pour 1 h, `beta = 5`). Le créateur touche 0 (sous le seuil de 3 présents). |
| `N = 2` | Les deux présents se partagent `P`. Le créateur touche 0 (sous le seuil de 3 présents). |
| `N >= 3` | Le créateur touche sa prime. |
| Parts au plafond | Plusieurs rangs peuvent être ex aequo à `2 x P / N` (Festival : rangs 1 à 6). |
| `beta` absent ou 0 (anciens événements) | `N/beta` traité comme 0. |
| `N > beta` (capacité non appliquée, voir [01](01-etat-des-lieux.md)) | `N/beta` plafonné à 1, pour borner `P`. |
| Désinscription avant la clôture | Le participant n'est plus présent, les suivants remontent. |
| Événement annulé | Aucun calcul : `event.finished` n'est pas émis. |
| L'organisateur a aussi une arête `PARTICIPATE` | Il ne reçoit que la prime du créateur, pas de points de participant. |
| Présent coché puis événement non terminé | Aucun point tant que `FINISHED` n'est pas atteint. |
| Rejeu de `event.finished` | Aucun doublon : le registre est idempotent par `(event_id, user_id)`. |

## 7. Version de formule

Chaque crédit enregistre `formula_version`. La version vaut `1` : rien n'a été déployé avec une version antérieure, donc le plafond et le seuil de 3 présents font partie de la version 1. Changer `e`, le plafond, le seuil du créateur, la table de `alpha` ou l'arrondi incrémente ensuite la version. Les crédits existants ne sont jamais recalculés.
