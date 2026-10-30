# 04 - Exemples et simulations

Tous les chiffres de ce document sont produits par un script Python qui applique la formule de [03](03-formule.md) (`P_i = P x i^-0,3 / S`, arrondi simple). Aucun n'est recopié à la main. Le script doit être versionné avec la doc lors de l'implémentation.

## 1. Cas calculés

| Cas | Durée | `N` | `beta` | `alpha` | `P` | Moyenne | Créateur | Points au rang 1 / 3 / 10 / 50 / 100 / dernier (quand présents) | Écart du 1er à la moyenne | Écart du dernier |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | :--- | ---: | ---: |
| Atelier | 2 h | 5 | 5 | 1,0 | 1 000 | 200 | 300 | 263 / 189 / 162 (dernier) | +31 % | -19 % |
| Ramassage | 4 h | 20 | 20 | 1,5 | 6 000 | 300 | 450 | 549 / 395 / 275 / 223 (dernier) | +83 % | -26 % |
| Nettoyage | 24 h | 50 | 50 | 2,5 | 25 000 | 500 | 750 | 1 172 / 843 / 587 / 362 (dernier) | +134 % | -28 % |
| Remplissage partiel | 4 h | 10 | 40 | 1,5 | 1 875 | 188 | 281 | 288 / 207 / 144 (dernier) | +54 % | -23 % |
| Festival | week-end | 200 | 200 | 4,0 | 160 000 | 800 | 1 200 | 2 783 / 2 002 / 1 395 / 861 / 699 / 568 (dernier) | +248 % | -29 % |

Le tableau lit les rangs 1, 3, 10, 50, 100 et dernier, quand ils existent.

Dérive d'arrondi (somme des `P_i` moins `P`) : 0 pour les trois premiers cas, -2 pour le remplissage partiel, -4 pour le festival. La méthode du plus grand reste la ramène à 0.

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

Dans le cas 5 les proportions entre rangs sont justes, mais les valeurs de la capture additionnent environ 94 000 points, pas les 160 000 du pool annoncé. Les captures semblent donc venir d'un autre pool ou d'un autre calcul. **La formule fait foi, pas les captures.** Les exemples de [06](06-flux-asynchrone.md) et des tests devront utiliser les valeurs ci-dessus.

## 3. Le bonus du premier grossit avec `N`

Avec `e = 0,3`, le premier touche +31 % de la moyenne à `N = 5` mais +248 % à `N = 200`. C'est contraire à l'objectif d'anti-dispersion de [02](02-probleme-et-principes.md) pour les grands événements. Écart du premier à la moyenne selon l'exposant (même script) :

| Exposant `e` | `N`=5 | `N`=10 | `N`=20 | `N`=50 | `N`=200 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0,30 | +31 % | +54 % | +83 % | +134 % | +248 % |
| 0,20 | +20 % | +34 % | +51 % | +78 % | +132 % |
| 0,15 | +15 % | +25 % | +36 % | +55 % | +89 % |
| 0,10 | +10 % | +16 % | +23 % | +34 % | +53 % |

Options à trancher :

1. **Réduire l'exposant** (par exemple 0,15) : simple, mais le bonus du premier à `N` petit devient faible (+15 % à `N`=5).
2. **Plafonner le bonus du premier** à un pourcentage de la moyenne (par exemple +100 %) et redistribuer l'excédent : garde l'attrait à petit `N`, borne le grand `N`.
3. **Exposant dépendant de `N`** : plus complexe à expliquer.

Recommandation : option 2, car elle respecte l'intention ("un pourcentage plus important, pas un fossé") sur toutes les tailles. À valider par Victor avant l'implémentation.

## 4. Cas particuliers chiffrés

| Cas | Résultat |
| :--- | :--- |
| `N = 1`, 1 h, `beta` = 5 | Participant 120 points, créateur 180 points. |
| `N = 2`, 1 h, `beta` = 50 | `P` = 208 : 115 et 93 points, créateur 156. |
