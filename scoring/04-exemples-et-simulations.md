# 04 - Exemples et simulations

Tous les chiffres de ce document sont produits par [`scripts/simulate.py`](scripts/simulate.py) (`python3 -I docs/scoring/scripts/simulate.py`), qui applique la formule de [03](03-formule.md) : poids `i^-0,3`, plafond de chaque part à `2 x P / N`, excédent redistribué, arrondi au plus grand reste. Aucun n'est recopié à la main. Le script est versionné avec la doc : toute modification de la formule passe par lui, puis par ce document.

## 1. Cas calculés

| Cas | Durée | `N` | `beta` | `alpha` | `P` | Moyenne | Créateur | Points au rang 1 / 3 / 10 / 50 / 100 / dernier (quand présents) | Écart du 1er à la moyenne | Écart du dernier |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | :--- | ---: | ---: |
| Atelier | 2 h | 5 | 5 | 1,0 | 1 000 | 200 | 300 | 263 / 189 / 162 (dernier) | +31 % | -19 % |
| Ramassage | 4 h | 20 | 20 | 1,5 | 6 000 | 300 | 450 | 549 / 395 / 275 / 223 (dernier) | +83 % | -26 % |
| Nettoyage | 24 h | 50 | 50 | 2,5 | 25 000 | 500 | 750 | 1 000 / 849 / 591 / 365 (dernier) | +100 % | -27 % |
| Remplissage partiel | 4 h | 10 | 40 | 1,5 | 1 875 | 188 | 281 | 288 / 207 / 145 (dernier) | +54 % | -23 % |
| Festival | week-end | 200 | 200 | 4,0 | 160 000 | 800 | 1 200 | 1 600 / 1 600 / 1 420 / 876 / 711 / 578 (dernier) | +100 % | -28 % |

Le tableau lit les rangs 1, 3, 10, 50, 100 et dernier, quand ils existent. Dans le Nettoyage, le rang 50 est le dernier : 365.

Effet du plafond : le Nettoyage passe de 1 172 à 1 000 au rang 1, et le Festival de 2 783 à 1 600. Au Festival, les rangs 1 à 6 touchent tous 1 600 (ex aequo au plafond, voir [03](03-formule.md), section 6). L'Atelier, le Ramassage et le Remplissage partiel restent sous le plafond et gardent les valeurs de la formule pure.

Somme des `P_i` : égale à `P` dans les cinq cas (méthode du plus grand reste). Avec l'arrondi simple, la somme dérivait de -2 (remplissage partiel) et -4 (festival).

## 2. Écart avec les maquettes

Le Cas 1 des captures correspond à la formule à un point près (arrondi) :

| Rang | Capture | Formule |
| ---: | ---: | ---: |
| 1 | 262 | 263 |
| 2 | 213 | 213 |
| 3 | 189 | 189 |
| 4 | 173 | 173 |
| 5 | 163 | 162 |

Les cas B (créateur contre participants) et 5 (festival) **ne correspondent pas** à la formule :

| Cas | Rang | Capture | Formule |
| :--- | ---: | ---: | ---: |
| B (`N`=20, `alpha`=1,5, `beta`=20) | 1 | 495 | 549 |
| B | 10 | 248 | 275 |
| B | 20 | 201 | 223 |
| 5 (`N`=200, `alpha`=4, `beta`=200) | 1 | 1 630 | 2 783 |
| 5 | 10 | 818 | 1 395 |
| 5 | 50 | 504 | 861 |
| 5 | 100 | 409 | 699 |
| 5 | 200 | 333 | 568 |

Dans le cas 5 les proportions entre rangs sont justes, mais les valeurs de la capture additionnent environ 94 000 points, pas les 160 000 du pool annoncé. Les captures semblent donc venir d'un autre pool ou d'un autre calcul. **La formule fait foi, pas les captures.** Les valeurs "Formule" de ce tableau sont celles de la formule pure, avant le plafond de la section 3 (avec le plafond, le rang 1 du cas 5 vaut 1 600). Les exemples de [06](06-flux-asynchrone.md) et des tests devront utiliser les valeurs de la section 1.

## 3. Le bonus du premier : plafond pour tous les rangs

Avec `e = 0,3` seul, le premier touche +31 % de la moyenne à `N = 5` mais +248 % à `N = 200`, contraire à l'objectif d'anti-dispersion de [02](02-probleme-et-principes.md). Écart du premier à la moyenne selon l'exposant, formule pure sans plafond (même script) :

| Exposant `e` | `N`=5 | `N`=10 | `N`=20 | `N`=50 | `N`=200 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0,30 | +31 % | +54 % | +83 % | +134 % | +248 % |
| 0,20 | +20 % | +34 % | +51 % | +78 % | +132 % |
| 0,15 | +15 % | +25 % | +36 % | +55 % | +89 % |
| 0,10 | +10 % | +16 % | +23 % | +34 % | +53 % |

**Décision (option plafond).** L'exposant reste `0,3`. Chaque part est bornée à `+100 %` de la moyenne (`2 x P / N`) pour **tous** les rangs, pas seulement le premier. L'excédent est redistribué proportionnellement aux poids des rangs non plafonnés, jusqu'à stabilité (water-filling), puis arrondi au plus grand reste. Avec le plafond, la ligne `e = 0,30` devient :

| Exposant `e` | `N`=5 | `N`=10 | `N`=20 | `N`=50 | `N`=200 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0,30 plafonné | +31 % | +54 % | +83 % | +100 % | +100 % |

Options écartées :

1. **Réduire l'exposant** (par exemple 0,15) : le bonus du premier à `N` petit devient faible (+15 % à `N`=5).
2. **Exposant dépendant de `N`** : plus complexe à expliquer.

## 4. Cas particuliers chiffrés

La prime du créateur n'est versée qu'à partir de 3 présents (`MIN_ATTENDEES_FOR_ORGANIZER_POINTS`, voir [03](03-formule.md)).

| Cas | Résultat |
| :--- | :--- |
| `N = 0` | Aucun point, y compris pour le créateur. |
| `N = 1`, 1 h, `beta` = 5 | Participant 120 points, créateur 0 (sous le seuil). |
| `N = 2`, 1 h, `beta` = 50 | `P` = 208 : 115 et 93 points, créateur 0 (sous le seuil). |
| `N = 3`, 1 h, `beta` = 50 | `P` = 318 : 126, 102 et 90 points, créateur 159. |
