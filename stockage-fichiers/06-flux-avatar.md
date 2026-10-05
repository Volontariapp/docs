# 06 - Flux Avatar et Badge (mode SYNC)

Les petites images sont validées **pendant** `ConfirmUpload`. Au moment où le service métier les rattache, elles sont forcément `CLEAN` : aucun statut intermédiaire n'est nécessaire côté métier.

**Pas de mode asynchrone** pour ces deux types ([02-architecture-cible.md](02-architecture-cible.md), section 3) : la taille maximale (1 Mo) est égale au seuil SYNC, et `ms-user` n'a pas de statut média qui permettrait d'attendre une validation. En conséquence :

- erreur technique pendant le traitement synchrone : le fichier repasse en attente d'upload (échéance repoussée) et `ms-storage` répond 503 ;
- `ms-storage` indisponible au moment de `ConfirmFileAttachment` (`UNAVAILABLE`, `DEADLINE_EXCEEDED`) : `ms-user` répond 503, le profil n'est pas modifié, le client réessaie.

## 1. Photo de profil

**Champ** : `users.avatar_file_id` remplace `users.logo_path`. `logo_path` est déprécié dans `SignUpCommand`, `UpdateUserCommand`, `User`, `UserPublic` et `IUserPayload` ([08-contrats-et-evolutions.md](08-contrats-et-evolutions.md)). L'avatar ne se définit pas à l'inscription : il se définit ensuite par mise à jour du profil.

```mermaid
sequenceDiagram
    autonumber
    participant F as nativapp
    participant GW as api-gateway
    participant ST as ms-storage
    participant S3Q as S3 quarantaine
    participant S3P as S3 public
    participant U as ms-user
    participant RS as Redis Streams
    participant PS as pp-storage

    Note over F,S3Q: Phase 1 - Upload
    Note left of F: Redimensionne (1024 px) et ré-encode en JPEG
    F->>GW: POST /storage/upload-url (mime, size, USER_AVATAR)
    GW->>ST: gRPC GenerateUploadUrl
    Note right of ST: Politique SYNC : 1 Mo max, sinon 400
    ST-->>F: fileId + URL et champs du POST signé
    F->>S3Q: POST multipart vers quarantine/fileId

    Note over F,S3P: Phase 2 - Confirmation, mode SYNC
    F->>GW: POST /storage/files/{fileId}/confirm
    GW->>ST: gRPC ConfirmUpload
    Note right of ST: UPDATE conditionnel vers SCANNING (verrou)
    ST->>S3Q: HeadObject + GetObject
    Note right of ST: Pipeline inline : magic bytes, clamd,<br/>ré-encodage webp 512x512, suppression EXIF
    alt Scanner ou S3 indisponible
        ST-->>F: 503 UNAVAILABLE, réessai côté front
    else Rejeté
        ST->>S3Q: DeleteObject
        Note right of ST: scan_status = REJECTED
        ST-->>F: 422 avec RejectionReason
    else Sain
        ST->>S3P: PutObject user-avatar/fileId.webp
        ST->>S3Q: DeleteObject
        Note right of ST: scan_status = CLEAN
        ST-->>F: 200 FileMetadata (CLEAN, public_url)
    end

    Note over F,U: Phase 3 - Mise à jour du profil
    F->>GW: PATCH /users/me (avatarFileId)
    GW->>U: gRPC UpdateUser
    U->>ST: gRPC ConfirmFileAttachment([avatarFileId], USER_AVATAR, userId)
    Note right of U: Appel AVANT withFallback
    alt Réservation refusée
        ST-->>U: NOT_FOUND ou FAILED_PRECONDITION
        U-->>F: 404 ou 422
    else ms-storage indisponible
        U-->>F: 503, aucun rattachement asynchrone pour l'avatar
    else Réservation OK, scan_status = CLEAN garanti
        Note right of U: Transaction domain-user :<br/>SELECT avatar_file_id FOR UPDATE (oldFileId)<br/>UPDATE avatar_file_id<br/>+ event_queue user.avatar_replaced(userId, newFileId, oldFileId)
        U-->>F: 200 profil à jour
        U--)RS: user.avatar_replaced
        RS--)PS: consomme
        Note right of PS: newFileId : RESERVED vers ATTACHED<br/>oldFileId : RESERVED ou ATTACHED vers ORPHANED
    end
```

### Règles

- **Même avatar renvoyé** : si `avatar_file_id` ne change pas, `domain-user` n'écrit ni mise à jour ni `user.avatar_replaced`.
- **Affichage immédiat** : le front peut afficher l'avatar dès l'étape 2 grâce à `public_url`.
- **Fallback existant** : `updateUser` passe par `withFallback(UserJobType.FALLBACK_UPDATE_USER, ...)`. `ConfirmFileAttachment` reste **avant** ce bloc pour renvoyer le 422 en synchrone. Le payload de fallback transporte `avatarFileId`, et le rejeu écrit `user.avatar_replaced` dans sa transaction.
- **Outbox à ajouter dans `domain-user`** : la méthode `update` de `postgres-user.repository.ts` n'écrit aujourd'hui aucun événement. L'écriture de `user.avatar_replaced` dans la même transaction est un changement de `domain-user`, soumis à la règle du STOP.
- **Avatar confirmé mais jamais utilisé** : le fichier reste `PENDING` + `CLEAN`, purgé 24 h après sa confirmation.
- **Suppression de l'avatar** : `PATCH /users/me` avec `avatarFileId = null`, `user.avatar_replaced` émis avec `newFileId` absent.
- **Timeout** : le deadline gRPC de `ConfirmUpload` en mode SYNC doit couvrir le traitement d'un fichier de 1 Mo. Valeur à mesurer, proposition initiale 10 s côté gateway.
- **Format iOS** : le redimensionnement et le ré-encodage JPEG côté client évitent d'envoyer du HEIC.

## 2. Icône de badge (administration)

Les badges sont gérés par les administrateurs via `CreateBadgeCommand`, `UpdateBadgeCommand`, `DeleteBadgeCommand` (`user/user.command.proto`).

**Champ** : `badges.icon_file_id` remplace `icon_path`, déprécié dans `Badge`, `CreateBadgeCommand` et `UpdateBadgeCommand`. **SVG refusé** : les administrateurs fournissent un PNG ou un WebP.

```mermaid
sequenceDiagram
    autonumber
    participant A as Admin
    participant GW as api-gateway
    participant ST as ms-storage
    participant U as ms-user
    participant RS as Redis Streams
    participant PS as pp-storage

    A->>ST: GenerateUploadUrl (BADGE_ICON), POST signé, ConfirmUpload SYNC
    ST-->>A: FileMetadata (CLEAN, public_url)
    alt Création
        A->>GW: POST /badges (..., iconFileId, idempotencyKey)
        GW->>U: gRPC CreateBadge
        Note right of U: badgeId = UUID v5(adminId, idempotencyKey)
        U->>ST: ConfirmFileAttachment([iconFileId], BADGE_ICON, badgeId)
        Note right of U: Appel AVANT withFallback, badgeId dans le payload de fallback<br/>Transaction : INSERT badge + event_queue user.badge_created
        U--)RS: user.badge_created
    else Remplacement
        A->>GW: PATCH /badges/{id} (iconFileId)
        GW->>U: gRPC UpdateBadge
        U->>ST: ConfirmFileAttachment([iconFileId], BADGE_ICON, badgeId)
        Note right of U: Transaction : SELECT icon_file_id FOR UPDATE<br/>UPDATE + event_queue user.badge_icon_replaced
        U--)RS: user.badge_icon_replaced
    else Suppression
        A->>GW: DELETE /badges/{id}
        GW->>U: gRPC DeleteBadge
        Note right of U: Transaction : DELETE + event_queue user.badge_deleted
        U--)RS: user.badge_deleted
    end
    RS--)PS: consomme
    Note right of PS: Rattachement ou libération selon l'événement
```

### Règles

- **Propriété** : le propriétaire du fichier est l'administrateur qui l'a uploadé. Les icônes de badge sont des ressources de la plateforme : elles ne sont **pas** libérées quand le compte de cet administrateur est supprimé ([07-nettoyage-et-orphelins.md](07-nettoyage-et-orphelins.md)).
- **Fallback** : la création de badge passe par `withFallback` (`badge.command.controller.ts`). `ConfirmFileAttachment` est appelé avant, et le `badgeId` calculé est transporté dans le payload de fallback.
- **Même icône renvoyée** : aucune écriture si `icon_file_id` ne change pas.
- **Trois événements à créer** : `user.badge_created`, `user.badge_icon_replaced`, `user.badge_deleted`. `BadgeService` n'en émet aucun aujourd'hui.
