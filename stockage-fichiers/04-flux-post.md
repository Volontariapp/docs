# 04 - Flux Post

**Cas d'usage** : un utilisateur publie un post avec une à dix images.

**Règle produit** : l'image est le contenu du post. Un post dont les médias ne sont pas encore validés n'est **pas visible** des autres utilisateurs (`media_status = PENDING`). Son auteur le voit avec un indicateur "en cours de traitement".

**Modes** ([02-architecture-cible.md](02-architecture-cible.md), section 3) :

- Traitement : SYNC par défaut (image de 1 Mo ou moins après redimensionnement client), ASYNC si l'image est plus volumineuse ou si le traitement synchrone échoue techniquement.
- Rattachement : `ConfirmFileAttachment` synchrone par défaut, rattachement asynchrone par `pp-storage` si `ms-storage` est indisponible.

## 1. Diagramme de séquence

```mermaid
sequenceDiagram
    autonumber
    participant F as nativapp
    participant GW as api-gateway
    participant ST as ms-storage
    participant S3Q as S3 quarantaine
    participant S3P as S3 public
    participant W as worker-storage
    participant P as ms-post
    participant RS as Redis Streams
    participant PS as pp-storage
    participant PP as pp-post
    participant WS as ws-service

    Note over F,S3Q: Phase 1 - Upload, répété pour chaque image
    Note left of F: Redimensionne (2048 px) et ré-encode en JPEG
    F->>GW: POST /storage/upload-url (mime, size, POST)
    GW->>ST: gRPC GenerateUploadUrl
    Note right of ST: domain-storage : mime, taille, validation_mode<br/>SYNC si 1 Mo ou moins, sinon ASYNC<br/>INSERT files (PENDING, AWAITING_UPLOAD)
    ST-->>F: fileId + URL et champs du POST signé
    F->>S3Q: POST multipart vers quarantine/fileId

    Note over F,W: Phase 2 - Confirmation
    F->>GW: POST /storage/files/{fileId}/confirm
    GW->>ST: gRPC ConfirmUpload
    ST->>S3Q: HeadObject (taille réelle)
    alt validation_mode = SYNC
        Note right of ST: Pipeline inline : magic bytes, clamd,<br/>ré-encodage webp, suppression EXIF
        alt Sain
            ST->>S3P: PutObject post/fileId.webp
            ST-->>F: FileMetadata CLEAN + public_url
        else Rejeté
            ST-->>F: 422 avec RejectionReason
        else Erreur technique
            Note right of ST: Bascule ASYNC : validation_mode = ASYNC<br/>+ jobs_outbox storage.scan_file
            ST-->>F: FileMetadata SCANNING
            ST--)W: Job storage.scan_file
        end
    else validation_mode = ASYNC (image volumineuse)
        Note right of ST: Transaction : scan_status = SCANNING<br/>+ jobs_outbox storage.scan_file
        ST-->>F: FileMetadata SCANNING
        ST--)W: Job storage.scan_file
    end

    Note over F,P: Phase 3 - Création du post
    F->>GW: POST /posts (title, content, fileIds, idempotencyKey)
    GW->>P: gRPC CreatePost
    Note right of P: postId = UUID v5(ownerId, idempotencyKey)
    P->>ST: gRPC ConfirmFileAttachment(fileIds, POST, postId), deadline 2 s
    alt Réservation refusée
        ST-->>P: NOT_FOUND ou FAILED_PRECONDITION
        P-->>F: 404 ou 422
    else Réservation OK
        ST-->>P: FileMetadata[] avec scan_status
        Note right of P: Transaction domain-post :<br/>INSERT post ON CONFLICT (id) DO NOTHING + post_media<br/>media_status = READY si tous CLEAN, sinon PENDING<br/>+ event_queue post.created (userId, fileIds)
        P-->>F: 201 post créé
    else ms-storage indisponible (UNAVAILABLE, DEADLINE_EXCEEDED)
        Note right of P: Rattachement asynchrone :<br/>même transaction, media_status = PENDING
        P-->>F: 201 post créé (en cours de traitement)
    end
    P--)RS: post.created
    RS--)PS: consomme
    Note right of PS: Algorithme unique (doc 03 section 4) :<br/>RESERVED vers ATTACHED, ou PENDING validé vers ATTACHED<br/>+ résultat du scan si déjà traité<br/>fichier invalide : storage.attachment_rejected

    Note over W,WS: Phase 4 - Fin du traitement ASYNC
    W->>S3Q: GetObject
    Note right of W: Pipeline : magic bytes, clamd,<br/>ré-encodage webp, suppression EXIF
    alt Sain
        W->>S3P: PutObject post/fileId.webp
        Note right of W: Transaction : UPDATE conditionnel scan_status = CLEAN<br/>+ storage.file_scanned si status = ATTACHED
    else Rejeté
        Note right of W: Transaction : UPDATE conditionnel scan_status = REJECTED<br/>+ storage.file_rejected si status = ATTACHED
    end
    W->>S3Q: DeleteObject quarantine/fileId

    Note over RS,WS: Phase 5 - Diffusion, émise par W ou par PS selon l'ordre
    par Mise à jour métier
        RS--)PP: storage.file_scanned / file_rejected / attachment_rejected (entityType = POST)
        Note right of PP: post_media.scan_status mis à jour<br/>media_status recalculé (idempotent)<br/>post supprimé entre temps : acquitter (warn)
        PP->>P: UPDATE posts.media_status
    and Notification
        RS--)WS: consomme
        WS--)F: push "post publié" ou "image refusée"
    end
```

## 2. Règles

- **Sans image** : `fileIds` vide, `ConfirmFileAttachment` n'est pas appelé, `media_status = NONE`.
- **Cas nominal** : images de 1 Mo ou moins, `ms-storage` disponible. Les images sont `CLEAN` dès la confirmation, la réservation renvoie `CLEAN`, le post est créé directement en `READY`. Aucune attente pour l'utilisateur.
- **Ordre des images** : conservé par `post_media.position`.
- **Agrégation** : `pp-post` met à jour `post_media.scan_status` pour le fichier reçu, puis recalcule `media_status` :
  - un média `REJECTED` (contenu refusé ou `storage.attachment_rejected`) : `REJECTED` ;
  - tous les médias `CLEAN` : `READY` ;
  - sinon : `PENDING`.

  La mise à jour et le recalcul sont idempotents : recevoir deux fois le même événement ne change rien.
- **Rattachement asynchrone** : le post est écrit sans validation préalable des fichiers. `pp-storage` les valide à réception de `post.created`. Un fichier invalide produit `storage.attachment_rejected`, et le post passe `REJECTED` sans avoir jamais été visible.
- **Réessai client après une erreur 5xx** : la même `idempotencyKey` donne le même `postId`. La réservation est reconnue comme "même entité" et l'insertion (`ON CONFLICT (id) DO NOTHING`) renvoie le post existant sans réémettre `post.created`.
- **Média rejeté** : le post passe `media_status = REJECTED` et reste invisible pour les autres. L'auteur est notifié et peut supprimer le post. La modification des médias d'un post existant n'est pas prévue au MVP.
- **Suppression du post** : `post.deleted` (existant) est consommé par `pp-storage`, qui libère les fichiers du post et écrit une pierre tombale.
- **Échec de la saga de création** : `post.creation_failed` est émis par `ws-service` (agrégation Scatter-Gather, `base-gather.post-processor.ts`) sur le stream `ws:post-created-feedback`, partagé avec d'autres types. `pp-storage` s'y abonne, filtre sur le type `post.creation_failed` et libère les fichiers du post. Aucun consommateur ne passe aujourd'hui un post en `CANCEL` : le post reste en `saga_status = PENDING`.

Les scénarios de panne détaillés sont dans [11-scenarios-de-panne.md](11-scenarios-de-panne.md).

## 3. Visibilité

Le filtre `media_status IN (NONE, READY)` s'applique pour tout lecteur qui n'est pas l'auteur, dans les requêtes de lecture de `domain-post` : `findById`, `listPaginated`, `search`. Le fil d'actualité renvoie des ids depuis `ms-social` (alimenté par `post.created`), hydratés par `ms-post` : les posts non visibles sont écartés à cette étape. Voir [02-architecture-cible.md](02-architecture-cible.md), section 6.

## 4. Lecture d'un post

```mermaid
sequenceDiagram
    participant F as nativapp
    participant GW as api-gateway
    participant P as ms-post
    participant S3P as S3 public

    F->>GW: GET /posts/{id}
    GW->>P: gRPC GetPost
    P-->>GW: post + media[] (fileId, position) + media_status
    Note right of GW: buildPublicFileUrl(POST, fileId, publicBaseUrl)<br/>domain-storage, aucun appel réseau
    GW-->>F: post + media[].url
    F->>S3P: GET post/fileId.webp
```

Tant que `media_status != READY`, l'auteur reçoit les `fileId` sans URL, et le front affiche un indicateur de traitement.
