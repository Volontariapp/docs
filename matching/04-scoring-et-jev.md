# 04 - Scoring et Jev

## Pourquoi deux scores

Le graphe sait **qui** a fait **quoi**, pas **de quoi parle** un événement. Jev comprend le texte, pas le réseau. Le score final combine les deux.

| Score | Source | Ce qu'il capte | Ce qu'il rate |
| :--- | :--- | :--- | :--- |
| Structurel | Neo4j + historique | amis présents, affinité de type (écologie/social), proximité temporelle | « nettoyage de rivière » proche de « ramassage de plage » si personne ne les relie |
| Sémantique | Jev | proximité de sens entre le goût déduit et l'événement | la dimension sociale (qui y va) |

## Score structurel (0 à 1)

Calculé localement, sans appel externe, sur chaque candidat :

| Composante | Définition | Poids initial |
| :--- | :--- | :--- |
| `friends` | proportion d'amis (suivi mutuel) liés à l'événement, bornée à 1 (ex. 3 amis ou plus = 1) | 0,40 |
| `typeAffinity` | part des événements de l'historique ayant le même `type` que le candidat (`SOCIAL` ou `ECOLOGY`) | 0,35 |
| `freshness` | décroissance linéaire selon la distance entre `startAt` et maintenant (un événement dans 2 jours vaut plus qu'un dans 3 mois) | 0,25 |

Les poids sont des constantes de configuration versionnées par `version` (champ de `matching:meta`) : changer la formule invalide les anciennes listes.

Pour un utilisateur **sans historique** (cas d'un compte neuf), `typeAffinity` vaut 0,5 pour tous (neutre) et le score sémantique est ignoré faute de profil : la liste est classée par `friends` puis `freshness`, et `source = STRUCTURAL_ONLY`.

## Score sémantique par Jev (0 à 1)

### Principe

Jev renvoie une décision structurée avec une probabilité. On lui pose une question fermée par candidat : « cet événement correspond-il au profil ci-dessous ? », et on exploite la probabilité de la réponse affirmative comme score.

### Ce qui est envoyé, et ce qui ne l'est jamais

Envoyé, par appel :

- Un **résumé de goût** construit à partir des 20 événements de l'historique : pour chacun `name`, `type`, `tags` et un extrait court de `description`.
- Le candidat : `name`, `type`, `tags`, extrait de `description`.

**Jamais envoyé** : `userId`, `pseudo`, `email`, `rna`, `passwordHash`, identifiants d'amis, `bio`. La `bio` est du texte libre rédigé par l'utilisateur et peut contenir des données personnelles : elle est exclue par défaut (voir questions ouvertes pour une option explicite). Cette règle découle de la section 6 de `AGENTS.md` (protection des données).

### Port et adaptateur

Le domaine ne connaît pas Jev. Il définit un port, l'adaptateur le branche.

```typescript
// domain-social (ou package dédié) : le port
export interface MatchingCandidate {
  eventId: string;
  name: string;
  type: 'SOCIAL' | 'ECOLOGY';
  tags: string[];
  summary: string;
}

export interface MatchingScorer {
  score(tasteSummary: string, candidates: MatchingCandidate[]): Promise<Map<string, number>>;
}
```

- `JevMatchingScorer` : implémentation qui appelle l'API TypeSafe AI.
- `NoopMatchingScorer` : renvoie une map vide, ce qui équivaut au mode structurel seul. Sert aux tests et aux environnements sans clé.

> [!WARNING]
> **Ce dossier ne spécifie volontairement pas l'API HTTP de Jev** (URL, format de requête, schéma de sortie, authentification). Elle n'a pas été vérifiée dans la documentation du fournisseur ; la décrire ici serait deviner. L'accès est en accès anticipé. À renseigner dans `JevMatchingScorer` une fois la documentation et la clé en main. Le reste de l'architecture n'en dépend pas, grâce au port.

### Garde-fous d'appel

| Garde-fou | Valeur initiale | Raison |
| :--- | :--- | :--- |
| Nombre de candidats envoyés | 30 meilleurs au score structurel | borne le coût et la durée du job |
| Concurrence | 5 appels simultanés | respecte un éventuel plafond de débit |
| Timeout par appel | 2 s | les latences annoncées par le fournisseur sont de 70 à 500 ms (chiffres du vendeur) |
| Tentatives | 1 retry | puis repli structurel |
| Clé API | variable d'environnement via la config, **SealedSecret** en déploiement | règle « zéro secret en clair dans Git » |

## Score final

```text
si score sémantique disponible pour le candidat :
    final = 0,5 * structurel + 0,5 * sémantique
sinon :
    final = structurel
```

Les candidats au-delà des 30 premiers (non envoyés à Jev) gardent leur score structurel. Pour que les deux populations restent comparables, seuls les 30 premiers voient leur score recombiné ; les autres sont conservés mais classés après (score plafonné sous le minimum des 30 premiers). Ce détail évite qu'un événement non évalué par Jev passe devant un événement évalué.

## Validation avant de faire confiance

Avant d'exposer le score en production de démonstration, constituer un petit jeu étiqueté (par exemple 20 couples profil/événement jugés à la main : pertinent, neutre, hors sujet) et mesurer si le classement obtenu les respecte. C'est la recommandation de la presse spécialisée pour tout modèle de décision, dont les performances annoncées par le fournisseur sont des chiffres du vendeur.
