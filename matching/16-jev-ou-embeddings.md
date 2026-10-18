# 16 - Jev, embeddings ou base vectorielle ?

Décision demandée le 2026-10-18 : Jev est-il pertinent, ou une approche par embeddings (voire une base vectorielle) suffit-elle ? Contexte : projet à but éducatif, zéro client, une clé Jev disponible. Ce fichier tranche et fixe le critère de décision.

## 1. Le besoin réel

Comparer le **texte d'un événement** (nom, tags, 200 premiers caractères de la description) au **goût déduit** de l'historique d'un utilisateur, pour au plus `RANKING_CANDIDATE_LIMIT` (150) candidats par calcul, dont 30 envoyés au scorer sémantique ([05](05-scoring-et-jev.md) section 3). Ce n'est ni de la recherche sur un grand corpus, ni de la génération.

## 2. Les trois options

| Critère | A. Jev (API) | B. Embeddings + cosinus en mémoire | C. Base vectorielle (pgvector ou dédiée) |
| :--- | :--- | :--- | :--- |
| Principe | une requête, une question oui/non par candidat, probabilité renvoyée | un vecteur par texte d'événement (calculé une fois, mis en cache), vecteur de goût = moyenne des vecteurs de l'historique, score = cosinus | idem B, avec recherche des plus proches voisins dans la base |
| Infrastructure | aucune (appel HTTPS sortant) | un modèle d'embeddings (API externe **ou** inférence locale dans le worker, non évaluée) ; stockage des vecteurs dans une table | B plus une extension ou un service à installer |
| Données sortantes | texte public vers un tiers | aucune si le modèle est local ; texte public vers un tiers sinon | idem B |
| Coût | tokens facturés (estimation de [05](05-scoring-et-jev.md) section 7, chiffres du fournisseur non vérifiés) | quasi nul une fois les vecteurs en cache | quasi nul, plus l'exploitation |
| Déterminisme et tests | dépend d'un tiers (limites de débit, pannes) ; repli structurel obligatoire | reproductible, testable hors ligne | idem B |
| Effort | faible : un adaptateur HTTP déjà spécifié | moyen : choix du modèle, cache, mise à jour des vecteurs | élevé : infra supplémentaire |
| Valeur pédagogique | approche récente, peu standard | approche standard de l'industrie | approche standard à grande échelle |

## 3. Verdict

1. **Écarter la base vectorielle (C).** Une recherche de plus proches voisins n'a d'intérêt que sur de grands corpus ; ici on compare 150 vecteurs à un seul. Un cosinus en mémoire suffit. Le déploiement de test utilise `postgres:16-alpine` (`ci-tools/docker-compose.yml:171`) ; la disponibilité d'une extension vectorielle en production n'a pas été vérifiée.
2. **Garder le port `RankingScorer`** ([05](05-scoring-et-jev.md) section 4) : c'est lui qui rend le choix réversible. T1 livre un classement **sans** scorer sémantique (`NoopRankingScorer`).
3. **Ordre proposé** : RK-21 Jev d'abord (zéro infrastructure, déjà spécifié, clé disponible), puis RK-22 embeddings comme **expérience comparée** sur le même jeu d'essai. L'approche par embeddings est celle qu'un relecteur attend par défaut ; Jev apporte la comparaison et reste un choix défendable parce qu'il est mesuré.
4. **Réponse à « n'est-ce pas surdimensionné ? »** : le classement structurel est livré seul et fonctionne ; le scorer sémantique est un composant interchangeable, retenu ou retiré selon la mesure ci-dessous.

## 4. Critère de décision (RK-20 puis RK-22)

Sur le jeu d'essai (20 couples profil/événement étiquetés pertinent, neutre, hors sujet), comparer structurel seul, structurel + Jev, structurel + embeddings :

| Mesure | Comment |
| :--- | :--- |
| Qualité | accord entre l'ordre obtenu et les étiquettes (les pertinents avant les hors sujet) |
| Latence | p95 d'un calcul complet |
| Coût | tokens ou appels par calcul |
| Robustesse | taux de repli structurel (erreurs, limites de débit) |

Règle : un scorer sémantique n'est conservé que s'il améliore l'ordre étiqueté de façon visible par rapport au structurel seul. Sinon, la V1 reste structurelle et le résultat est consigné.

## 5. Conception de l'adaptateur par embeddings (RK-22, si réalisé)

- Table `ranking_event_embedding(event_id, model, vector, text_hash, computed_at)` : le vecteur n'est recalculé que si `text_hash` change ; les vecteurs d'événements terminés sont purgés.
- Goût de l'utilisateur = moyenne (éventuellement pondérée par récence) des vecteurs des événements souhaités et participés.
- Score sémantique = cosinus ramené dans [0, 1], combiné comme le score Jev (`0,5 * structurel + 0,5 * sémantique`, [05](05-scoring-et-jev.md) section 5).
- Mêmes protections que Jev : texte public uniquement, liste blanche de champs, troncature, aucun identifiant personnel.
- Le choix du modèle et de l'endroit où il s'exécute (API ou worker) reste à évaluer : un worker doit rester sous son plafond de mémoire.
