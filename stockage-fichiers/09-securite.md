# 09 - Sécurité

## 1. Menaces et parades

| Menace | Parade | Où |
| :--- | :--- | :--- |
| Fichier malveillant servi publiquement avant traitement | Upload en quarantaine privée, publication uniquement après traitement | `ms-storage`, `worker-storage` |
| Fichier polyglotte (image valide + charge utile) | Ré-encodage systématique : seul le résultat du décodeur est publié | Package d'infrastructure storage |
| MIME déclaré mensonger | Vérification des magic bytes avant décodage | Package d'infrastructure storage |
| SVG contenant du JavaScript, ou références externes (`xlink:href`, risque SSRF / lecture de fichiers locaux) | **SVG refusé** pour tous les `EntityType` | `domain-storage` |
| Fichier trop gros | Policy `content-length-range` du POST signé, puis `HeadObject` à la confirmation | `ms-storage` |
| Bombe de décompression (petit fichier, dimensions énormes) | Limite de pixels lue dans l'en-tête avant le décodage complet | Package d'infrastructure storage |
| Upload vers une clé arbitraire | La policy du POST signé fixe la clé `quarantine/{fileId}` et le `Content-Type` | `ms-storage` |
| Utilisation du fichier d'un autre utilisateur | Réservation filtrée sur `owner_id` | `ms-storage` |
| Réutilisation d'un fichier pour un autre type d'entité | `entity_type` fixé à `GenerateUploadUrl`, vérifié à la réservation | `ms-storage` |
| `file_id` frauduleux envoyé pendant un rattachement asynchrone | Validation par `pp-storage` avec la même règle que `ConfirmFileAttachment`, rien n'est affiché avant `READY` | `pp-storage`, `domain-storage` |
| Double rattachement d'un même fichier | Réservation uniquement depuis `PENDING`, sauf réessai pour la même entité | `ms-storage` |
| Fuite de position GPS (PII) | Suppression des métadonnées EXIF / XMP au ré-encodage | Package d'infrastructure storage |
| Énumération des fichiers publics | Politique anonyme limitée à `s3:GetObject` (pas de `s3:ListBucket`), `file_id` en UUID v4 | `ci-tools`, configuration production |
| Images de posts encore invisibles accessibles | Elles ne sont publiées qu'une fois `CLEAN`, et leur clé contient un UUID v4 non devinable | Bucket public |
| Collision d'id d'entité entre utilisateurs | Id dérivé de `ownerId` + clé d'idempotence (UUID v5) | `ms-post`, `ms-event`, `ms-user` |
| Abus de génération d'URL signées | Rate limiting sur `/storage/*` | `api-gateway` (chantier préalable, inexistant aujourd'hui) |

## 2. Identité de l'appelant

- `owner_id` n'est **jamais** lu dans le payload. Il provient du `CurrentUser` extrait de l'`INTERNAL_TOKEN`.
- Pour `ConfirmFileAttachment`, l'appelant est un microservice (`ms-post`, `ms-event`, `ms-user`) qui agit **pour le compte** d'un utilisateur. Il doit propager l'`INTERNAL_TOKEN` reçu de la gateway dans les métadonnées gRPC, sous la clé `x-internal-token`.
- Le mécanisme existe déjà dans `ms-post/src/modules/post/clients/social-event-post.query-client.ts`. Les `StorageClientService` actuels ne l'utilisent pas.
- Le client storage partagé reprend ce mécanisme **sans** reprendre les casts de ce fichier (`as QueryServiceWithMetadata`, `err as Error`) : typage de l'interface de service et type guard sur les erreurs.

## 3. Mapping des erreurs

| Situation | Code gRPC | Code HTTP (gateway) |
| :--- | :--- | :--- |
| MIME non autorisé, taille déclarée trop grande, trop de fichiers pour l'entité | `INVALID_ARGUMENT` | 400 |
| Fichier inconnu ou appartenant à un autre utilisateur | `NOT_FOUND` (ne pas révéler l'existence) | 404 |
| Mauvais `EntityType`, upload non confirmé, fichier rejeté, déjà réservé pour une autre entité, libéré | `FAILED_PRECONDITION` | 422 |
| Upload expiré ou objet absent de la quarantaine à la confirmation | `FAILED_PRECONDITION` | 422 |
| Fichier rejeté en mode SYNC | `FAILED_PRECONDITION` + `RejectionReason` dans les détails | 422 |
| Scanner ou S3 indisponible pendant un traitement SYNC | Post, event : bascule ASYNC, réponse `SCANNING`. Avatar, badge : `UNAVAILABLE` | 200 / 503 |
| `ms-storage` indisponible pour `ConfirmFileAttachment` | Post, event : rattachement asynchrone, aucune erreur. Avatar, badge : `UNAVAILABLE` | 201 / 503 |
| Erreur inattendue | `INTERNAL` | 500 |

- La réservation distingue `NOT_FOUND` de `FAILED_PRECONDITION` grâce au `SELECT ... FOR UPDATE` préalable ([03-cycle-de-vie-fichier.md](03-cycle-de-vie-fichier.md), section 3). Les ids sont dédoublonnés avant traitement.
- `ms-post`, `ms-event` et `ms-user` propagent l'erreur de `ms-storage` avec le même code. Le mapping est centralisé dans le client storage partagé.

## 4. Traçabilité

- Chaque transition de `status` et de `scan_status` est loggée via `@volontariapp/logger` avec `fileId`, `ownerId`, `entityType`, `entityId`, l'ancienne et la nouvelle valeur.
- Les rejets loggent la `RejectionReason`, jamais le contenu du fichier.
- Les lignes `files` ne sont jamais supprimées (`DELETED`), ce qui conserve l'historique.
