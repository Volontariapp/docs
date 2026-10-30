# 03 - Formule

## 1. Paramètres

| Symbole | Sens | Source |
| :--- | :--- | :--- |
| `N` | Nombre de participants **présents** validés | `checked_in_at` non nul, voir [05](05-modele-de-donnees-et-checkin.md) |
| `beta` | Capacité maximale (`maxParticipants`, doit être `>= 1`) | `events.maxParticipants` |
| `alpha` | Coefficient de durée | table de paliers ci-dessous |
| `i` | Rang d'inscription parmi les présents (1 à `N`), trié par `registered_at` croissant | `registered_at` |
| `e` | Exposant de décroissance, 0,3 dans les maquettes | constante versionnée (voir [04](04-exemples-et-simulations.md) pour l'ajustement) |

## 2. Paliers de `alpha` (proposition, à valider)

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
P_createur = arrondi( 150 x alpha x (1 + N / beta) )
```

## 4. Prize pool et points des participants

```text
P   = N x 100 x alpha x (1 + N / beta)
w_i = 1 / i^e
S   = somme des w_k pour k de 1 à N
P_i = arrondi( P x w_i / S )
```

Le pool moyen par participant est `100 x alpha x (1 + N/beta)`, soit de 100 (très peu rempli, 1 h) à 800 (plein, week-end).

## 5. Arrondi

L'arrondi simple fait dériver la somme des `P_i` par rapport à `P` (jusqu'à 4 points à N=200). Proposition : méthode du plus grand reste (parties entières, puis les points manquants aux plus grandes parties fractionnaires). La somme vaut alors exactement `P`, ce qui rend la distribution auditable.

## 6. Cas limites

| Cas | Règle proposée |
| :--- | :--- |
| `N = 0` | Aucun point, y compris pour le créateur. |
| `N = 1` | Le seul présent touche `P` entier (120 pour 1 h, `beta = 5`). Le créateur touche 180, plus que lui. À surveiller (Sybil, [10](10-plan-de-livraison-et-risques.md)). |
| `beta` absent ou 0 (anciens événements) | `N/beta` traité comme 0. |
| `N > beta` (capacité non appliquée, voir [01](01-etat-des-lieux.md)) | `N/beta` plafonné à 1, pour borner `P`. |
| Désinscription avant la clôture | Le participant n'est plus présent, les suivants remontent. |
| Événement annulé | Aucun calcul : `event.finished` n'est pas émis. |
| L'organisateur a aussi une arête `PARTICIPATE` | Il ne reçoit que la prime du créateur, pas de points de participant. |
| Présent coché puis événement non terminé | Aucun point tant que `FINISHED` n'est pas atteint. |
| Rejeu de `event.finished` | Aucun doublon : le registre est idempotent par `(event_id, user_id)`. |

## 7. Version de formule

Chaque crédit enregistre `formula_version` (par exemple `1`). Changer `e`, la table de `alpha` ou l'arrondi incrémente la version. Les crédits existants ne sont jamais recalculés.
