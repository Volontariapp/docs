# Classement personnalisé des événements et des posts (`ms-ranking`)

Ce dossier décrit, de bout en bout, un nouveau microservice qui calcule en arrière-plan **à quel point chaque événement correspond à chaque utilisateur** et expose un endpoint renvoyant les événements qui correspondent le mieux au profil de l'utilisateur connecté.

> [!NOTE]
> **Statut : proposition de conception, rien n'est implémenté.** Les faits sur le code existant sont vérifiés et référencés. Ce qui est à créer est signalé comme tel, et ce qui reste à confirmer est listé dans [09](09-plan-de-livraison.md). **Le nom `ms-ranking` est décidé** (2026-10-18, ADR-1) : `ms-affinity` n'était qu'un nom de travail, et `ms-rank` a été écarté parce que `nativapp` utilise déjà « rank » pour les niveaux d'impact (`nativapp/src/shared/lib/impact-ranks.ts`). Décisions de la V1 : [13](13-decisions-v1.md).

## Par où commencer

1. [13](13-decisions-v1.md) : ce qui est décidé (prime sur 01 à 12 en cas de divergence).
2. [14](14-plan-d-implementation.md) : ce qu'il faut faire, dans quel ordre.
3. 02 à 12 : le détail technique d'une étape (modèle de données, flux, scoring, lecture, création, tests, risques).

## Principe en cinq lignes

1. **Toute écriture est asynchrone.** Un événement de la plateforme (inscription, souhait, nouvel événement, événement terminé) déclenche un **job** de calcul.
2. Le job lit le graphe social (`ms-social`), le texte des événements (`ms-event`), demande un jugement sémantique à **Jev** (TypeSafe AI), puis écrit une liste ordonnée `(eventId, score)` dans la **base PostgreSQL de `ms-ranking`**.
3. **La lecture est synchrone** : une requête indexée dans cette table (`GET /ranking/events`), puis la gateway charge le contenu des événements depuis `ms-event`.
4. **Cas extrême** (aucune liste calculée pour l'utilisateur) : `ms-ranking` écrit un job de calcul à la demande et répond **206 `FALLBACK_ACTIVATED`** sans données. L'application affiche la recherche d'événements classique, puis bascule sur les recommandations dès qu'elle reçoit la notification WebSocket.
5. **`ms-ranking` ne possède aucun contenu d'événement ni de post** : seulement des verdicts dérivés et recalculables. La source de vérité du contenu reste `ms-event` (et `ms-post` pour le feed).

**Feed de posts (inclus en V1, décision du 2026-10-18).** Le même service classe aussi les posts selon ce que l'utilisateur aime, commente et suit (`GET /ranking/feed`). Il réutilise la mécanique ci-dessus ; voir les fichiers 10 à 12.

> [!WARNING]
> **Exception au principe « verdicts dérivés uniquement ».** Le feed impose un **journal de likes daté** (`ranking_like_log`), car le graphe n'a aucune date. C'est une donnée comportementale primaire, non entièrement recalculable. Elle est soumise à une rétention de 90 jours, à la suppression avec le compte (traitée en V1 par `user:deleted:ranking`, [03](03-modele-de-donnees.md) section 5) et à la question du chiffrement au repos ([11](11-feed-conception.md) section 2, [12](12-feed-plan-et-risques.md)).

## Navigation

| Fichier | Contenu |
| :--- | :--- |
| [01 - État des lieux](01-etat-des-lieux.md) | Ce qui existe, avec preuves (chemins, outils) |
| [02 - Architecture cible](02-architecture-cible.md) | Déployables, dépendances, propriété des données, schémas |
| [03 - Modèle de données](03-modele-de-donnees.md) | Tables PostgreSQL, requêtes, migrations, verrous, rétention |
| [04 - Flux asynchrone](04-flux-asynchrone.md) | Déclencheurs, contrats de jobs, handlers, fan-out, idempotence |
| [05 - Scoring et Jev](05-scoring-et-jev.md) | Formule, appel Jev, port/adaptateur, confidentialité |
| [06 - Lecture et 206](06-lecture-et-206.md) | RPC, route gateway, sémantique du 206, comportement du client |
| [07 - Création du microservice](07-creation-du-microservice.md) | Liste exhaustive des dépôts et fichiers à créer ou modifier |
| [08 - Tests, observabilité, sécurité](08-tests-observabilite-securite.md) | Stratégie de test, métriques, menaces |
| [09 - Plan de livraison](09-plan-de-livraison.md) | Ordre (règle du STOP), tranches, risques, questions ouvertes, démo |
| [10 - Feed de posts : état des lieux](10-feed-etat-des-lieux.md) | Extension : ce que la plateforme sait déjà des posts, likes, commentaires, follows |
| [11 - Feed de posts : conception](11-feed-conception.md) | Signaux, registre daté, candidats, score, déclencheurs, lecture |
| [12 - Feed de posts : plan et risques](12-feed-plan-et-risques.md) | Dépôts concernés, tranches, tests, risques, questions ouvertes |
| [13 - Décisions de la V1](13-decisions-v1.md) | **À lire en premier.** Décisions validées le 2026-10-18, géographie, swipe, popularité, codes d'explication, suppression de compte |
| [14 - Plan d'implémentation](14-plan-d-implementation.md) | **Source des tickets** : ordre, dépôts, skills, critères d'acceptation (RK-01 à RK-23) |
| [15 - Application](15-nativapp.md) | Périmètre front, faits relevés, changements N1 à N9, parcours à vérifier |
| [16 - Jev ou embeddings](16-jev-ou-embeddings.md) | Arbitrage du scorer sémantique et critère de mesure |

## Décisions d'architecture (ADR synthétiques)

| # | Décision | Alternatives écartées | Raison principale |
| :--- | :--- | :--- | :--- |
| ADR-1 | Nouveau microservice `ms-ranking` (nom décidé le 2026-10-18) | Tout dans `ms-social` + `worker-social` | `ms-social` possède le graphe, pas un modèle de lecture dérivé ni une clé d'API tierce. Isolation de la sortie Internet (Jev) et des secrets. |
| ADR-2 | Stockage des listes en **PostgreSQL** | Redis comme stockage ; relation Neo4j `MATCHES` | Donnée petite et recalculable, lue par index. Aucune infrastructure nouvelle (tout microservice a déjà son Postgres). Pas de cache à désynchroniser, rien de perdu au redémarrage. Exception : le journal de likes du feed (donnée primaire), voir l'avertissement ci-dessus. |
| ADR-3 | Calcul = **job** ; déclencheurs et fin = **événements** | Calcul dans le post-processor ; calcul synchrone | Un appel externe lent bloquerait le lot du flux. Le job apporte réessais BullMQ, audit `job_audit` et garde d'idempotence. |
| ADR-4 | Jev : **une requête, N questions `noul`** par utilisateur | Une requête par candidat ; types `choice` ou `score` | Le profil n'est envoyé qu'une fois. `noul` donne directement une probabilité exploitable. |
| ADR-5 | Lecture à froid = **206 + job à la demande + WebSocket** | Repli synchrone qui renvoie une liste dégradée ; 200 `{ status: 'PENDING' }` | Réutilise `FALLBACK_ACTIVATED` et le circuit `ws:jobs-outbox-success`. **Réserve de la revue** : le 206 est défini comme « échec non client + job de repli », pas comme « état froid », et la notification demande un mapping messaging à ajouter ([06](06-lecture-et-206.md) section 5, [04](04-flux-asynchrone.md) section 9). |
| ADR-6 | Score **hybride** (structurel + sémantique) avec repli structurel | Jev seul ; graphe seul | Le graphe voit le réseau, Jev voit le texte. Jev en panne ne casse pas la liste. |
| ADR-7 | Appels sortants via des RPC `Admin*` avec token interne signé par le service | Réutiliser les RPC utilisateur | Patron déjà utilisé par `post-processor-user` (`signInternal`, rôle `ADMIN`, cache de 4 minutes). Il faut ajouter `AdminGetRecommendedEventIds`. |
| ADR-8 | Rafraîchissement opportuniste (stale-while-revalidate) | TTL avec suppression | Une liste ancienne est servie (200) et un recalcul est demandé en arrière-plan. L'utilisateur n'est jamais devant une liste vide à cause de l'âge. |

## Glossaire

| Terme | Sens |
| :--- | :--- |
| Score structurel | Score issu du graphe et de l'historique (amis, type d'événement, fraîcheur). Local et déterministe. |
| Score sémantique | Probabilité renvoyée par Jev que l'événement corresponde aux goûts déduits de l'historique. |
| Liste de classement | Lignes `ranking_score` d'un utilisateur, ordonnées par `rank`. |
| Run | Ligne `ranking_run` : métadonnées du dernier calcul d'un utilisateur. |
| Calcul à la demande | Job émis par une lecture qui ne trouve aucune liste (lié au 206). |
| Fan-out | Un événement de plateforme qui concerne beaucoup d'utilisateurs engendre un job de calcul par utilisateur. |
