# 05 - Scoring et Jev

## 1. Pourquoi deux scores

Le graphe sait **qui** a fait **quoi**, pas **de quoi parle** un événement. Jev comprend le texte, pas le réseau. Le score final combine les deux.

| Score | Source | Capte | Rate |
| :--- | :--- | :--- | :--- |
| Structurel | Neo4j + historique | amis présents, affinité de type (écologie/social), proximité temporelle | « nettoyage de rivière » proche de « ramassage de plage » si personne ne les relie |
| Sémantique | Jev | proximité de sens entre le goût déduit et l'événement | la dimension sociale (qui y va) |

## 2. Score structurel (0 à 1)

Calculé localement, sans appel externe, sur chaque candidat, par un service pur de `domain-affinity` (donc testable sans aucune infrastructure).

| Composante | Définition | Poids initial |
| :--- | :--- | :--- |
| `friends` | **booléen** : 1 si l'événement est touché (participé, souhaité ou créé) par au moins un ami (suivi mutuel), sinon 0. Un compte d'amis n'est pas calculable avec la RPC actuelle, qui renvoie des identifiants dédupliqués sans compte ([04](04-flux-asynchrone.md) étape 5) | 0,40 |
| `typeAffinity` | part des événements de l'historique ayant le même `type` que le candidat (`SOCIAL` ou `ECOLOGY`) | 0,35 |
| `freshness` | `1 - clamp(joursAvantDébut / 60, 0, 1)`, où `joursAvantDébut` est positif (seuls les événements avec `startAt > now` sont candidats) : un événement dans 2 jours vaut plus qu'un dans 2 mois | 0,25 |

```text
structurel = 0,40 * friends + 0,35 * typeAffinity + 0,25 * freshness
```

Cas limites :

| Cas | Traitement |
| :--- | :--- |
| Historique vide (compte neuf) | `typeAffinity = 0,5` pour tous (neutre) ; Jev n'est pas appelé (rien à décrire) ; `source = STRUCTURAL_ONLY` |
| Aucun ami | `friends = 0` pour tous |
| Événement déjà commencé | écarté à la lecture des candidats (`start_date_from = now`, [04](04-flux-asynchrone.md) étape 4) : critère unique `startAt > now` |
| Nombre de candidats inférieur à la taille de liste | la liste est simplement plus courte |

Les poids et seuils (3 amis, 60 jours) sont des constantes versionnées par `FORMULA_VERSION`. **Toute modification de la formule incrémente la version** ; les listes d'une autre version sont considérées périmées à la lecture ([06](06-lecture-et-206.md)).

## 3. Score sémantique par Jev (0 à 1)

### 3.1 API (source : documentation officielle https://docs.typesafe.ai/api)

```text
POST https://api.typesafe.ai/v1/systemone
Authorization: Bearer <TYPESAFE_API_KEY>
Content-Type: application/json
```

| Champ | Valeur chez nous |
| :--- | :--- |
| `model` | `"jev-latest"` (alias donné par la doc ; la page « Models » n'a pas été lue) |
| `state` | le **résumé de goût** de l'utilisateur (objet) |
| `questions` | map `eventId -> question`, une question de type `noul` par candidat |

Types de question documentés : `noul` (oui/non, renvoie une probabilité du oui entre 0 et 1), `choice` (une option parmi 255 max, avec `probabilities` et `confidence`), `score` (grille de 2 à 10 niveaux). Nous utilisons `noul`.

Requête type :

```json
{
  "model": "jev-latest",
  "state": {
    "taste": {
      "ecology_share": 0.7,
      "social_share": 0.3,
      "attended_or_wished": [
        { "name": "Nettoyage de la plage", "type": "ECOLOGY", "tags": ["plage", "dechets"], "summary": "..." }
      ]
    }
  },
  "questions": {
    "<eventId>": {
      "type": "noul",
      "instructions": {
        "candidate": { "name": "...", "type": "ECOLOGY", "tags": ["..."], "summary": "..." },
        "ask": "Cet evenement correspond-il aux gouts decrits dans state ?"
      },
      "criteria": {
        "true": "L'evenement est proche, par le theme ou l'activite, de ce que la personne a deja fait ou souhaite faire.",
        "false": "L'evenement n'a aucun rapport avec ce que la personne a deja fait ou souhaite faire."
      }
    }
  }
}
```

Réponse (champs documentés) : `model`, `answers` (map par la même clé), `usage` avec `input_tokens` et `output_tokens`. Pour `noul` : `answers.<eventId>.type = "noul"` et `answers.<eventId>.noul` (nombre de 0 à 1).

D'après la documentation, la clé de chaque question n'est pas envoyée au modèle ; l'utilisation de l'`eventId` comme clé suppose donc qu'il n'y a pas de fuite d'identifiant. C'est une **hypothèse à valider** (la documentation ne précise pas les limites de longueur ou de format d'une clé).

**Un seul appel HTTP par calcul** évalue tous les candidats. Le plafond de 30 questions par requête est une borne prudente de notre côté : la documentation ne donne aucune limite et ne parle ni de batching explicite, ni de timeout, ni de prix. **À valider par un essai** (voir [09](09-plan-de-livraison.md)).

### 3.2 Erreurs documentées et traitement

| Statut | Signification | Traitement |
| :--- | :--- | :--- |
| `401` | clé absente ou invalide | pas de réessai ; repli structurel ; journal `error` ; alerte |
| `422` | requête mal formée ; le corps nomme le champ | pas de réessai identique ; **dégradation par sous-lot** (diviser les questions en deux et réessayer) pour isoler la question fautive sans perdre les autres ; repli structurel pour les questions isolées en erreur ; journal `error`, message tronqué et masqué (il peut citer du texte d'événement) |
| `429` | limite de débit | réessai, attente exponentielle (2 tentatives) |
| `529` | surcharge temporaire | réessai après un court délai (2 tentatives) |
| autre / timeout / réseau | indisponible | repli structurel |

Les SDK officiels JavaScript et Python réessaient automatiquement `429` et `529`. On peut soit utiliser le SDK JavaScript officiel, soit un client HTTP minimal avec cette politique. Le choix (dépendance supplémentaire contre code de réessai à maintenir) est laissé à l'implémentation ; l'adaptateur reste derrière le port.

### 3.3 Résumé de goût (`state`)

Construit de façon **déterministe** à partir de l'historique (jusqu'à `AFFINITY_HISTORY_SIZE` événements participés et autant de souhaités) :

- `ecology_share` et `social_share` : parts de chaque `type` dans l'historique.
- `attended_or_wished` : pour chaque événement, `name`, `type`, `tags`, et `summary` = les 200 premiers caractères de `description`, sans retour à la ligne.

Cette liste est triée de façon stable (par `eventId`) pour que deux calculs identiques produisent des requêtes identiques.

### 3.4 Ce qui n'est jamais envoyé

`userId`, `pseudo`, `email`, `rna`, `passwordHash`, identifiants d'amis, `bio`, coordonnées précises. La `bio` est du texte libre rédigé par l'utilisateur et peut contenir des données personnelles : elle est exclue (option explicite en [09](09-plan-de-livraison.md)). Le texte envoyé est celui d'événements **publics**. Cette règle découle de la section 6 de `AGENTS.md`.

La page de référence ne dit rien sur la conservation des données par le fournisseur : tant que ce n'est pas établi, cette liste blanche est la protection.

Limite de la liste blanche de **champs** : le contenu de `name`, `description` et `tags` est rédigé par des utilisateurs et peut contenir des données personnelles. Mesures complémentaires : troncature (200 caractères), passage dans le masque de `@volontariapp/logger` avant envoi, borne de longueur et échappement des séparateurs, et détection de scores extrêmes répétés pour un même organisateur (tentative de manipulation du classement).

## 4. Port et adaptateur

Le domaine ne connaît pas Jev.

```typescript
// domain-affinity : le port
export interface AffinityCandidate {
  eventId: string;
  name: string;
  type: 'SOCIAL' | 'ECOLOGY';
  tags: string[];
  summary: string;
}

export interface TasteSummary {
  ecologyShare: number;
  socialShare: number;
  history: AffinityCandidate[];
}

export interface AffinityScorer {
  /** Renvoie la probabilite (0 a 1) par eventId. Un candidat absent n'a pas ete evalue. */
  score(taste: TasteSummary, candidates: AffinityCandidate[]): Promise<ReadonlyMap<string, number>>;
}

export class AffinityScorerUnavailableError extends Error {}
```

- `JevAffinityScorer` : implémentation HTTP (dans `worker-affinity` ou `domain-affinity/infrastructure`).
- `NoopAffinityScorer` : renvoie une map vide (équivaut à `STRUCTURAL_ONLY`). Sert aux tests, au développement local sans clé et à la tranche T1.

Le handler injecte le port ; il ne contient aucun détail HTTP.

## 5. Score final

```text
si semantic_score est disponible pour le candidat :
    final = 0,5 * structurel + 0,5 * sémantique
sinon :
    final = structurel
```

Les candidats au-delà des `AFFINITY_JEV_CANDIDATES` premiers (non envoyés à Jev) conservent leur score structurel. Pour que les deux populations restent comparables, on **plafonne** leur score final sous le minimum des candidats évalués par Jev : un événement non évalué ne passe jamais devant un événement évalué.

Les candidats envoyés à Jev sont choisis par **score structurel décroissant** (les 30 meilleurs). Conséquence assumée : Jev ne peut pas remonter un événement mal classé par le graphe au-delà du rang 30. C'est le prix d'un coût borné ; la formule peut évoluer (taille du lot, présélection) via `FORMULA_VERSION`.

## 6. Validation avant de faire confiance

Avant de présenter le score comme fiable :

1. Constituer un petit jeu étiqueté (par exemple 20 couples profil/événement jugés à la main : pertinent, neutre, hors sujet).
2. Vérifier que le classement obtenu les respecte (tests manuels documentés, pas nécessairement automatisés).
3. Mesurer la latence réelle d'une requête de 30 questions et ajuster `JEV_TIMEOUT_MS` (la valeur de 10 s est provisoire : la documentation n'en donne pas) et `AFFINITY_JEV_CANDIDATES`.
5. Prévoir un budget quotidien d'appels et un coupe-circuit (circuit breaker) dans l'adaptateur : après N échecs consécutifs, passer directement en repli structurel pendant une durée donnée.
4. Vérifier le plafond de questions par requête.

Les performances annoncées par le fournisseur (70 à 500 ms, 0,042 $ par million de tokens d'entrée) sont des chiffres du vendeur : à confirmer par la mesure.

## 7. Estimation du volume de tokens

Ordre de grandeur pour un calcul : environ 20 événements d'historique à 80 tokens et 30 candidats à 100 tokens, soit environ 5 000 tokens d'entrée. Au tarif annoncé, c'est de l'ordre du centième de centime par calcul. Le suivi réel se fait via `usage` stocké dans `affinity_run` ([03](03-modele-de-donnees.md)).
