# 02 - Décisions

## 1. Décisions validées par Victor (2026-11-07)

| # | Décision | Source |
| :--- | :--- | :--- |
| D1 | "En direct" = `isEventLive` (l'état `IN_PROGRESS`, ou `maintenant` entre `startAt` et `endAt`), **et** `endAt > maintenant`, **et** un état différent de `CANCELLED` et `FINISHED` (`isEventLive` ne regarde pas l'état dans la plage horaire). S'applique à la recherche comme à "Mon événement" | conversation ; relecture du 2026-11-07 |
| D2 | Rayon de recherche : **2 km à pied**. Pas plus loin : "sinon la personne n'arrive jamais" | conversation |
| D3 | Ne pas proposer un événement qui finit trop tôt : s'il reste moins de temps que la marche plus un temps de présence utile, il est écarté. La durée de présence utile (15 min) est une **valeur proposée par l'assistant**, à ajuster | conversation |
| D4 | Proposer **3 événements** rejoignables au plus, triés par temps de marche. Les événements **complets** sont montrés à part, **en grisé**, dans une section "Autres événements (complets)", non joignables | conversation |
| D5 | Point d'entrée : une **troisième action dans `QuickActionsModal`** (le gros bouton vert central). Le libellé change si l'utilisateur participe déjà à un événement en cours ("Mon événement en direct"). Un écran commun regroupe "Mon événement" et "Autour de moi" | conversation |
| D6 | Trajet : **OSRM public**, depuis l'app, tracé affiché dans l'app. Le front n'est pas déployé (démo pédagogique), le back l'est déjà. Hôte piéton `routing.openstreetmap.de/routed-foot` (l'hôte `router.project-osrm.org` calcule en voiture) | conversation et mesure ([01](01-etat-des-lieux.md) section 8) |
| D7 | Partage de position : **version réduite acceptée**. Désactivé par défaut, consentement par événement, position arrondie à environ 100 m, foreground uniquement, arrêt automatique (arrivée, fin, départ, app en arrière-plan), aucun historique, jamais dans les logs | conversation |
| D8 | Pas de carte publique des participants (risque de suivi) | conversation |
| D9 | Option B pour l'autorisation du partage (la gateway garde le contrôle de participation, `ws-service` lit une autorisation dans Redis), **dans la forme adaptée de D13** | conversation |
| D10 | Documentation d'abord, puis découpage en lots exécutables en parallèle par des sous-agents | conversation |
| D11 | Cycle de contrats minimal : `proto-registry` d'abord, puis **au plus 2 PR dans `npm-packages`** | conversation |
| D12 | Les rooms WebSocket par événement restent une piste pour la suite | conversation |

## 2. Décisions prises par l'assistant à la suite d'une vérification

À relire : elles modifient ce qui avait été accepté.

| # | Décision | Raison (preuve) |
| :--- | :--- | :--- |
| D13 | **Option B adaptée.** La gateway ne parle pas à Redis ; elle vérifie la participation puis appelle un endpoint interne de `ws-service`, qui écrit l'autorisation dans Redis | La `NetworkPolicy` de la gateway n'autorise pas Redis en production ([01](01-etat-des-lieux.md) section 6). La gateway peut joindre `ws-service`. Aucun changement dans `deploy` |
| D14 | **Audience V1 : l'organisateur seul**, via la room utilisateur existante. Pas de room par événement en V1 | Un seul destinataire : `notifyUser(organizerId, ...)` suffit. Les rooms par événement servent quand l'audience s'élargit |
| D15 | Les types de messages du partage vivent dans `@volontariapp/messaging` (nouveau groupe `live`), y compris la forme de l'autorisation envoyée par la gateway | Un seul endroit partagé par la gateway, `ws-service` et `nativapp` |

## 2 bis. Décisions validées par Victor après la relecture (2026-11-07)

| # | Décision | Raison (preuve) |
| :--- | :--- | :--- |
| D16 | **P3 conservé** (Q2 = A) : un champ `end_at_from`, un cycle de contrats | Choix de Victor |
| D17 | **Arrivée détectée par le client** sur sa position brute (jamais envoyée) : il appelle `DELETE` avec la raison `ARRIVED`. Repli serveur : `ws-service` arrête le partage si la position arrondie est à 150 m ou moins de l'événement | La position reçue par le serveur est arrondie (cellule d'environ 110 m sur 73 m à Paris) : un seuil de 50 m peut ne jamais se déclencher |
| D18 | **Endpoint interne de `ws-service`** : jeton interne vérifié **et** lié à l'utilisateur concerné (`token.id === userId` du corps ou du chemin), chemin sous `/internal/live`, jamais sous `/socket.io` ; `ws-service` revérifie le plafond de 8 h de `expiresAt` | Le jeton interne porte une identité utilisateur et circule dans toutes les métadonnées gRPC ([01](01-etat-des-lieux.md) section 5) ; 21 sources peuvent joindre `ws-service` ([01](01-etat-des-lieux.md) section 6) |
| D19 | **Capacité** : `maxParticipants <= 0` signifie sans limite, comme la gateway (ranking) ; complet signifie `maxParticipants > 0` et `currentParticipants >= maxParticipants` | Données anciennes possibles à 0 ([01](01-etat-des-lieux.md) section 3) |
| D20 | **"Mon événement en direct" compte aussi les événements en direct que l'utilisateur organise** (libellé du bouton central et section de l'écran) | Choix de Victor |
| D21 | **Isolation du verrou STOP** : les lots qui modifient `proto-registry` ou `npm-packages` (LE-01, LE-05) tournent chacun dans un processus `claude -p` séparé, jamais dans la session de l'orchestrateur | Un sous-agent partage le `session_id` de sa session, donc son verrou ([05](05-plan-de-pr-et-lots.md) section 1) |

## 3. Décisions ouvertes (valeur par défaut appliquée)

| # | Question | Options | Défaut appliqué | Si tu changes |
| :--- | :--- | :--- | :--- | :--- |
| Q1 | Audience du partage | **A.** organisateur seul. **B.** organisateur et amis participants (demande un RPC "amis" côté `ms-social` et des rooms par événement). **C.** tous les participants (écartée : suivi) | **A** | B ajoute un lot `ms-social` et un cycle de contrats |
| Q2 | Ajouter `endAtFrom` au proto | **A.** oui, un champ (1 PR `proto-registry`, 1 PR automatique `npm-packages`). **B.** non : on garde le filtre de fin côté client avec `limit = 100` et une fenêtre de 24 h | **A, validé (D16)** | B supprimerait LE-01, LE-06, LE-07, LE-10 et la PR automatique, et réduirait la PR B à `messaging` |
| Q3 | Contrôle de capacité côté serveur à la participation | **A.** non, le client grise (V1). **B.** oui, dans la gateway avant `participate` (409 si complet ; course possible entre deux appels) | **A** | B ajoute le lot optionnel LE-12 (règle de capacité de D19) |
| Q4 | Durée de marche maximale proposée | 20 min, **30 min**, 40 min | **30 min** | une constante |
| Q5 | Durée de présence utile après l'arrivée | 10 min, **15 min**, 30 min | **15 min** | une constante |
| Q6 | Nombre de complets affichés | 1, **2**, 3 | **2** | une constante |
| Q7 | Fréquence de partage de position | 15 s, **30 s**, 60 s (jamais 10 min : trop espacé pour 2 km à pied) | **30 s** | une constante |
| Q8 | Rappel "l'événement finit dans N minutes" | **A.** hors périmètre. **B.** job différé (aucun scheduler n'existe aujourd'hui) | **A** | B ajoute un lot `workers-runners` et des types de job |
| Q9 | Démarrer un direct depuis l'app (déclencher) | **A.** plus tard. **B.** maintenant : réutiliser le démarrage manuel existant (`EventDetailsTab.tsx:217`) | **A** | B est un petit lot `nativapp` |
