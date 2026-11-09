# Analyses de CPU par service

Analyses détaillées, service par service, de ce qui coûte du CPU à chaque requête et de la façon de le réduire. Rédigées le 2026-11-09 par des agents Claude Code en analyse seule (aucun code modifié, aucune base de production interrogée), à partir du code sur `origin/main` et, quand ils existent, des profils CPU pris à 225 req/s ([chapitre 04](../04-resultats.md), section 4.5). Chaque affirmation est marquée FAIT, INFERENCE ou NON VERIFIE.

| Service | Profil CPU | Rapport | Statut |
| :--- | :--- | :--- | :--- |
| `ms-user` | aucun, estimations par lecture de code | [ms-user.md](ms-user.md) | rédigé |
| `ms-social` | oui, 225 req/s | à venir | analyse en cours |
| `ms-event` | oui, 225 req/s | à venir | analyse en cours |
| `ms-post` | aucun, estimations par lecture de code et banc local | [ms-post.md](ms-post.md) | rédigé |
| `api-gateway` | oui, 225 req/s | à venir | analyse en cours |

## À retenir pour `ms-user`

- Seule la route `me` l'appelle dans le mélange de charge (un `GetUser` par requête).
- Chaque lecture fait deux requêtes SQL au lieu d'une (TypeORM, `findOne` avec relations).
- ms-user pèse environ 3 % du CPU du nœud : ses optimisations rapportent 1 à 2 % du nœud au plus.
- **Constat de sécurité, non corrigé à ce jour** : `ListUsers` n'a pas de `GrpcInternalGuard` (`ms-user/src/modules/user/controllers/queries/user.query.controller.ts:75-91`) et renvoie l'email déchiffré. À traiter séparément de la performance (décision de Victor, 2026-11-09 : faire le point plus tard).

## À retenir pour `ms-post`

- Le `COUNT` du total est la requête la plus chère de `ms-post-db` : un parcours complet de `posts` (5,6 ms au banc, 50 fois la page), à cause du terme `"authorId" = :lecteur`. Le cache actuel du total est indexé par lecteur : environ 65 % de réussite dans la rampe, proche de 0 en trafic réel.
- Chaque page fait deux requêtes SQL (mode « deux requêtes » de TypeORM avec `skip`/`take` et jointure) et un appel `ms-social` (`GetEventsRelatedToPosts`).
- Le plus gros levier de plateforme : mettre en cache les liens post vers événement dans `ms-post`, ce qui soulage aussi `ms-social`, le processus le plus chargé.
- Écart inexpliqué : environ 9 ms de CPU par `listPosts` mesurés en prod contre moins de 1 ms expliqué par la base : un profil est la première action.
- Les scripts du banc local (schéma, données, `EXPLAIN`) sont restés dans le répertoire de session de l'agent et ne sont pas versionnés.
