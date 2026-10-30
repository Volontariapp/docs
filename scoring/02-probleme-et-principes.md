# 02 - Problème et principes

## 1. Le problème

Volontariapp vit de la création et de la participation aux événements. Aujourd'hui les points ne motivent ni l'un ni l'autre :

- Le créateur fixe lui-même les points, donc ils ne mesurent rien et peuvent être gonflés.
- Tous les inscrits touchent la même chose, quelle que soit la durée, l'effort ou la taille de l'événement.
- Le créateur ne reçoit aucun point, alors que sans lui l'événement n'existe pas.
- Rien ne récompense l'engagement précoce, qui est pourtant ce qui remplit un événement.

## 2. Objectifs

1. Des points qui augmentent avec l'effort réel : durée, nombre de présents, taux de remplissage.
2. Récompenser les premiers inscrits sans créer un fossé : un premier à 40 000 points et les autres à 200 serait décourageant. Le bonus du premier doit être un pourcentage borné de la moyenne.
3. Récompenser le créateur sur la même logique d'effort, avec une prime comparable à un bon participant, pas écrasante.
4. Rester simple à expliquer en une phrase à un utilisateur.
5. Rester calculable de façon asynchrone, idempotente et rejouable (voir [06](06-flux-asynchrone.md)).

## 3. Principes de conception

| Principe | Application |
| :--- | :--- |
| Le total d'un événement est connu avant de se répartir | Le prize pool `P` ne dépend pas du rang. Les rangs ne font que le répartir : un bonus pour le premier se paie par un retrait aux suivants. |
| La présence fait foi | Seuls les présents comptent (anti-farming de l'inscription). |
| Bonus décroissant lent et borné | Poids `w_i = i^-0,3` : décroissance douce, avec chaque part plafonnée à +100 % de la moyenne pour éviter que l'écart du premier grossisse avec `N` (voir [04](04-exemples-et-simulations.md)). |
| Le créateur ne s'auto-récompense pas | Il ne saisit plus de points et sa prime vient de la formule, versée à partir de 3 présents. |
| Reproductibilité | Une version de formule (`formula_version`) est stockée avec chaque crédit : changer la formule ne réécrit pas l'historique. |
| Pas de rétroactivité | Les événements déjà terminés gardent leurs points actuels. |

## 4. Pourquoi une formule plutôt qu'une table fixe

Une table fixe (par exemple 100, 200, 500 points) ne tient pas compte de la taille réelle. La formule ajoute deux effets :

- **Remplissage** : le facteur `(1 + N/beta)` double le pool d'un événement plein par rapport à un événement presque vide.
- **Effort** : `alpha` rémunère la durée. Un week-end vaut 4 fois une heure.

## 5. Ce qui n'est pas dans le périmètre

- Récompenses matérielles ou financières.
- Réécriture de l'historique de points.
- Détection de fraude avancée (voir risques dans [10](10-plan-de-livraison-et-risques.md)).
