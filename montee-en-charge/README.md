# Montée en charge : de 200 à 300 requêtes par seconde

Dossier rédigé le 2026-11-09 à partir des mesures du soir du 2026-11-08 (Victor, Lead Dev, avec un agent Claude Code). Il répond à une question : **que faut-il faire pour que la plateforme tienne 300 requêtes par seconde sur la machine actuelle ?** Il explique ce qui a été mesuré, ce que cela prouve et ne prouve pas, puis le plan d'implémentation, étape par étape.

**Statut au 2026-11-10 : 400 req/s tenus sur le mélange de 4 routes, mais un Neo4j froid casse la première rafale.** Avec le plancher mémoire de la VM relevé à 14 Go et la vague 2 déployée, 300 req/s passent avec 0 erreur et un p95 de 166 ms, et 400 req/s avec un p95 de 196 ms, nœud à 52 % de CPU ([chapitre 08](08-memoire-vague2-et-400.md)). Après un redémarrage de Neo4j ou des heures sans travail, 100 req/s donnent 80 % d'erreurs : Neo4j tourne avec 1 CPU par erreur de configuration et ses lectures n'ont pas de timeout ([chapitre 09](09-demarrage-a-froid.md), correctifs en PR). Ces chiffres ne mesurent pas l'application réelle, qui lit `/ranking/feed` et `/ranking/events` : la rampe est en refonte ([chapitre 10](10-suites.md)).

Historique : le 2026-11-09 à 14:00, 300 req/s tenaient une fois, à la limite au second passage, et les rampes suivantes s'effondraient faute de mémoire ([chapitres 06](06-resultats-vague1.md) et [07](07-ms-event-db-et-memoire.md)).

## Chapitres

| Chapitre | Contenu |
| :--- | :--- |
| [01 - Mesures et méthode](01-mesures-et-methode.md) | Machine, méthode de la rampe de charge, résultats palier par palier, ce qui est déjà livré, limites des mesures |
| [02 - Analyses](02-analyses.md) | Où part le CPU, les incidents expliqués, le profil de la gateway, les journaux, OpenTelemetry, la répartition gRPC, l'hypothèse matérielle, la question Go |
| [03 - Plan d'implémentation](03-plan-d-implementation.md) | Budget de CPU, phases avec portes de décision, fichiers à modifier, critères de réussite, risques, décisions ouvertes |
| [04 - Résultats](04-resultats.md) | Ce qui a été livré (PR), rampes avant et après, répartition gRPC, profils CPU à 225 req/s, fréquence de l'hôte, ce qui limite à 275 req/s |
| [Analyses par service](analyses-services/README.md) | Ce qui coûte du CPU dans chaque service et comment le réduire (les cinq services et une synthèse) |
| [05 - Plan vers 300](05-plan-vers-300.md) | Phases A (hôte), B (mémoire de Node), C (code), D (mesure finale), portes de décision, décisions ouvertes |
| [06 - Résultats de la vague 1](06-resultats-vague1.md) | Sept changements (OpenTelemetry, journaux, HTTP, caches, validation, deadlines), rampe 225 à 300 req/s, CPU par pod, réussite des caches, prochain goulot |
| [07 - ms-event-db, puis la mémoire de la VM](07-ms-event-db-et-memoire.md) | Confirmation à 300 req/s, EXPLAIN du total de la recherche, `domain-event` 3.17.0, deux effondrements dus au manque de mémoire, prochaines étapes |
| [08 - Mémoire de la VM, vague 2, puis 400 req/s](08-memoire-vague2-et-400.md) | Ballon Proxmox, limites de Traefik, vague 2 (jetons, exclusions, pages de posts, GetUser), rampes jusqu'à 400 req/s, marge par composant, limite du mélange de 4 routes |
| [09 - Démarrage à froid](09-demarrage-a-froid.md) | Panne de la première rafale, deux tests qui départagent les hypothèses, Neo4j à 1 CPU par erreur, correctifs C1 à C5, critère d'acceptation |
| [10 - Suites](10-suites.md) | Rampe réaliste (décisions, lots L1 à L8), arrêt des post-processors (SIGTERM), optimisation des écritures, ordre de mise en œuvre, règles de travail |
| [11 - Passation](11-passation.md) | État de chaque chantier au 2026-11-10, PR ouvertes, commandes, décisions et pièges pour les prochains agents |
| [12 - Ticket : prérequis de L9 async](12-ticket-l9-prerequis-async.md) | Nettoyage de `social_edge` dans les suppressions faites par les post-processors, fin des erreurs d'outbox avalées dans `domain-social` (STOP) |

## Le résumé

1. **Aujourd'hui** : 200 req/s tiennent sans erreur mais sans marge (p95 1,3 s). 250 req/s s'effondre. Le plafond pratique est autour de 200.
2. **Pour 300 req/s sur 14 vCPU**, il faut passer de 52m de CPU par req/s à environ 36m : **moins 31 % par requête**, ou 3,2 vCPU à gagner à débit égal.
3. **Ce n'est pas un problème de langage.** Le profil CPU de la gateway montre que gRPC pèse 6 % de son temps, le ramasse-miettes 16 %, les journaux environ 15 % et OpenTelemetry environ 13 %. Une réécriture en Go n'est pas justifiée par ce profil.
4. **Les gains sont dans la configuration et dans quelques corrections de code** : niveau de journalisation (ignoré aujourd'hui), échantillonnage OpenTelemetry (à 100 % aujourd'hui), cache borné de lectures identiques pour tous, répartition des connexions gRPC entre les réplicas.
5. **La somme estimée de ces gains est de 2,0 à 3,5 vCPU pour 3,2 nécessaires** : atteindre 300 req/s est plausible mais pas acquis.
6. **Trois incertitudes à lever d'abord** : les paliers à 150 req/s rejoués ce soir se sont dégradés trois fois sans cause établie (pods froids de la gateway ? limite de puissance du processeur de l'hôte ? autre ?), la part réelle des journaux hors de la gateway, et le plafond matériel de l'hôte.
7. **Ordre proposé** : mesures (une demi-journée), configuration (un jour), code (deux à quatre jours), répartition gRPC (deux à trois jours), mesure finale. Chaque phase a une porte : on ne passe à la suivante que si le coût par requête a baissé.
8. **Si 300 n'est pas atteint après les quatre phases**, les options sont dans l'ordre : portage ciblé des quatre routes chaudes en Go, limite de puissance de l'hôte, seconde machine.

## Glossaire

| Terme | Sens dans ce dossier |
| :--- | :--- |
| **req/s** | Requêtes HTTP par seconde reçues par la gateway publique |
| **p50, p95, p99** | Durée sous laquelle répondent 50 %, 95 % et 99 % des requêtes. Le p95 est notre indicateur : il dit ce que vit 1 utilisateur sur 20 |
| **vCPU** | Un cœur virtuel de la VM. La VM en a 14 sur les 16 threads de la machine physique |
| **mCPU, "m"** | Millième de vCPU : 500m = une demi-vCPU |
| **HPA** | HorizontalPodAutoscaler : ajoute ou retire des pods de la gateway selon sa charge |
| **Pod froid** | Pod qui vient de démarrer : son code JavaScript n'est pas encore optimisé, ses connexions ne sont pas ouvertes |
| **OOMKilled** | Pod tué par Kubernetes parce qu'il dépasse sa limite de mémoire |
| **GC** | Ramasse-miettes : le travail de Node pour libérer la mémoire. Plus un programme crée d'objets (lignes de journal, spans), plus il coûte |
| **Span** | Unité de trace OpenTelemetry (une opération mesurée, envoyée à Datadog) |
| **PSI** | Pression de ressources du noyau Linux : mesure le temps où des tâches attendent le CPU ou le disque |
| **Marginal** | Coût de la requête suivante : CPU ajouté par chaque req/s supplémentaire |
| **FAIT, INFERENCE, NON VERIFIE** | Un FAIT est lu dans une sortie d'outil ou dans une ligne de code citée. Une INFERENCE est un raisonnement non mesuré. Un NON VERIFIE n'a pas été regardé |
