# Analyses de CPU par service

Analyses détaillées, service par service, de ce qui coûte du CPU à chaque requête et de la façon de le réduire. Rédigées le 2026-11-09 par des agents Claude Code en analyse seule (aucun code modifié, aucune base de production interrogée), à partir du code sur `origin/main` et, quand ils existent, des profils CPU pris à 225 req/s ([chapitre 04](../04-resultats.md), section 4.5). Chaque affirmation est marquée FAIT, INFERENCE ou NON VERIFIE.

| Service | Profil CPU | Rapport | Statut |
| :--- | :--- | :--- | :--- |
| `ms-user` | aucun, estimations par lecture de code | [ms-user.md](ms-user.md) | rédigé |
| `ms-social` | résumé du profil à 225 req/s (fichier écrasé, voir plus bas) | à venir | analyse en cours |
| `ms-event` | résumé du profil à 225 req/s (fichier écrasé), micro-mesures locales | [ms-event.md](ms-event.md) | rédigé |
| `ms-post` | aucun, estimations par lecture de code et banc local | [ms-post.md](ms-post.md) | rédigé |
| `api-gateway` | résumé du profil à 225 req/s (fichier écrasé), profil détaillé du 2026-11-08 | [api-gateway.md](api-gateway.md) | rédigé |

## Note sur les profils CPU à 225 req/s

Les trois profils pris à 10:03Z (gateway, `ms-social`, `ms-event`) ont été analysés juste après la capture : 30,4 s chacun, 48 %, 70 % et 58 % d'occupation. Les chiffres de la section 4.5 du [chapitre 04](../04-resultats.md) viennent de cette lecture et restent valables (FAIT). Les fichiers ont ensuite été **écrasés à 10:06:45Z** par une seconde capture lancée pendant la suppression des pods profilés : ils ne contiennent plus que l'arrêt des processus (`_kill`, hooks d'arrêt). Les rapports `ms-event` et `api-gateway` ont été rédigés à partir de ces fichiers écrasés, d'où leur avertissement en tête : ils s'appuient sur le résumé ci-dessus, sur le profil détaillé de la gateway du 2026-11-08 et sur la lecture du code. Pour connaître le temps inclusif par handler, il faut refaire les profils, en nommant chaque fichier par son heure pour ne pas l'écraser.

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

## À retenir pour `ms-event`

- La recherche (`searchAdvanced`) passe chaque identifiant exclu comme un paramètre SQL séparé : jusqu'à 2 000 paramètres et une requête de près de 14 000 caractères, envoyée deux fois, car `getManyAndCount` ajoute un `COUNT(1)` sans `LIMIT` avec le même filtre.
- INFERENCE : ce `COUNT` sur toute la table `events`, environ 100 fois par seconde, est la cause la plus probable de la charge de `ms-event-db`, la base la plus chargée.
- Côté pod, la validation de chaque identifiant (`@IsUUID`) et la sérialisation des 2 000 valeurs pèsent environ 12 à 15 % (micro-mesures locales).
- Leviers principaux : supprimer ou mettre en cache le `COUNT`, passer chaque liste comme un seul paramètre tableau, alléger la validation des identifiants (décision de sécurité à prendre).

## À retenir pour `api-gateway`

- Le jeton interne RS256 est signé à chaque requête alors qu'il vaut 1 h : environ 0,6 ms par requête dans le pool de threads, invisible dans le profil du fil principal, et sur le chemin critique avant le premier appel gRPC.
- Les instrumentations OpenTelemetry `express` et `router` produisent environ 15 des 20 spans par requête ; une variable d'environnement de `deploy` suffit pour les couper.
- `events-list-app` enchaîne 2 à 3 appels gRPC en série (exclusions, recherche, compteurs) qu'on ne peut pas paralléliser sans casser la pagination : seul le cache des exclusions (C2) retire un aller-retour.
- Gain total estimé : 15 à 20 % du CPU de la gateway (INFERENCE). Fastify et ES256 ou EdDSA écartés pour l'instant.
