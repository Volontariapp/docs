# 08 - Contrats et évolutions

Ce document liste tous les changements de contrats et de packages partagés. Chaque changement dans `proto-registry` ou `npm-packages` est soumis à la **règle du STOP** (`.agents/AGENTS.md`, section 1) : aucun consommateur n'est modifié avant publication par la CI.

## 1. Protobuf : domaine `storage`

`buf.yaml` n'a pas de section `breaking` : la catégorie par défaut (`FILE`) s'applique. Tous les changements ci-dessous sont des **ajouts** (valeurs d'enum, champs, messages, RPC) ou des **dépréciations** : ils ne cassent ni la compatibilité wire ni `buf breaking`.

### `storage.proto`

```protobuf
enum FileStatus {
  FILE_STATUS_UNSPECIFIED = 0;
  FILE_STATUS_PENDING = 1;
  FILE_STATUS_ATTACHED = 2;
  FILE_STATUS_ORPHANED = 3;
  FILE_STATUS_DELETED = 4;
  FILE_STATUS_RESERVED = 5;              // nouveau
}

enum ScanStatus {                        // nouveau
  SCAN_STATUS_UNSPECIFIED = 0;
  SCAN_STATUS_AWAITING_UPLOAD = 1;
  SCAN_STATUS_SCANNING = 2;
  SCAN_STATUS_CLEAN = 3;
  SCAN_STATUS_REJECTED = 4;
}

enum ValidationMode {                    // nouveau
  VALIDATION_MODE_UNSPECIFIED = 0;
  VALIDATION_MODE_SYNC = 1;
  VALIDATION_MODE_ASYNC = 2;
}

enum RejectionReason {                   // nouveau
  REJECTION_REASON_UNSPECIFIED = 0;
  REJECTION_REASON_SIZE_MISMATCH = 1;
  REJECTION_REASON_MIME_MISMATCH = 2;
  REJECTION_REASON_MALWARE = 3;
  REJECTION_REASON_UNDECODABLE = 4;
  REJECTION_REASON_SCAN_TIMEOUT = 5;
}

message FileMetadata {
  string id = 1;
  string owner_id = 2;
  string object_key = 3;                 // sémantique précisée : clé publique si CLEAN, vide sinon
  string mime_type = 4;
  FileStatus status = 5;
  optional EntityType entity_type = 6;
  optional string entity_id = 7;
  bool is_public = 8 [deprecated = true];  // la visibilité découle de scan_status
  google.protobuf.Timestamp upload_expires_at = 9;
  google.protobuf.Timestamp created_at = 10;
  google.protobuf.Timestamp updated_at = 11;
  ScanStatus scan_status = 12;                       // nouveau
  optional RejectionReason rejection_reason = 13;    // nouveau
  optional string public_url = 14;                   // nouveau, renseigné si CLEAN
  ValidationMode validation_mode = 15;               // nouveau : SYNC ou ASYNC (après bascule éventuelle)
}
```

La clé de quarantaine n'est jamais exposée.

### `storage.command.proto`, `storage.responses.proto`

```protobuf
message GenerateUploadUrlCommand {
  string mime_type = 1;
  int64 size_bytes = 2;
  EntityType entity_type = 3;
  bool is_public = 4 [deprecated = true];  // ignoré
}

message GenerateUploadUrlResponse {
  string file_id = 1;
  string upload_url = 2;
  google.protobuf.Timestamp expires_at = 3;
  map<string, string> upload_fields = 4;   // nouveau : champs du formulaire POST signé
}

message ConfirmUploadCommand {             // nouveau
  string file_id = 1;
}

message ConfirmUploadResponse {            // nouveau
  FileMetadata file = 1;                   // SCANNING (ASYNC) ou état final (SYNC)
}

message ConfirmFileAttachmentResponse {
  bool success = 1;
  int32 updated_count = 2;
  repeated FileMetadata files = 3;         // nouveau
}
```

`ConfirmFileAttachmentCommand` est inchangé (`file_ids`, `entity_type`, `entity_id`). Sa sémantique devient la **réservation** décrite dans [03-cycle-de-vie-fichier.md](03-cycle-de-vie-fichier.md), section 3. Aucun serveur n'existe aujourd'hui : ce changement de sens ne casse rien.

### `storage.services.proto`

```protobuf
service StorageService {
  rpc GenerateUploadUrl (GenerateUploadUrlCommand) returns (GenerateUploadUrlResponse) {}
  rpc ConfirmUpload (ConfirmUploadCommand) returns (ConfirmUploadResponse) {}             // nouveau
  rpc ConfirmFileAttachment (ConfirmFileAttachmentCommand) returns (ConfirmFileAttachmentResponse) {}
  rpc DeleteFile (DeleteFileCommand) returns (DeleteFileResponse) {}
  rpc GetFileMetadata (GetFileMetadataQuery) returns (FileMetadataResponse) {}
  rpc VerifyFilesExist (VerifyFilesExistQuery) returns (VerifyFilesExistResponse) {
    option deprecated = true;
  }
}
```

`DeleteFile` ne s'applique qu'aux fichiers `PENDING` de l'appelant (abandon d'un upload). Les fichiers réservés ou rattachés sont libérés uniquement par événement.

## 2. Protobuf : domaines métier

Les nouveaux enums sont préfixés et commencent par `_UNSPECIFIED = 0` (lint `STANDARD`). Les numéros de champs sont **fixés explicitement**, au-dessus du maximum actuel de chaque message. `buf breaking` (catégorie `FILE`) ne détecte pas la réutilisation d'un numéro supprimé : `CreateEventCommand` a un trou au champ 5 (ancien `volontariapp.common.Point location = 5`, supprimé sans `reserved`), qu'il faut réserver.

| Message | Ajouts (numéro) | Dépréciations / réservations |
| :--- | :--- | :--- |
| `CreatePostCommand` (max actuel 3) | `repeated string file_ids = 4`, `string idempotency_key = 5` | |
| `PostMedia` (nouveau) | `string file_id = 1`, `int32 position = 2` | |
| `Post` (max 7) | `repeated PostMedia media = 8`, `PostMediaStatus media_status = 9` | |
| `CreateEventCommand` (max 10, trou en 5) | `optional string cover_file_id = 11`, `string idempotency_key = 12` | `reserved 5; reserved "location";` |
| `Event` (max 15) | `optional string cover_file_id = 16`, `CoverStatus cover_status = 17` | |
| `UpdateEventCommand` | Aucun : `cover_file_id` passe par `Event` + `update_mask` | |
| `UpdateUserCommand` (max 8) | `optional string avatar_file_id = 9` | `logo_path` déprécié |
| `SignUpCommand` (max 7) | | `logo_path` déprécié |
| `User` (max 9) | `optional string avatar_file_id = 10` | `logo_path` déprécié |
| `UserPublic` (max 7) | `optional string avatar_file_id = 8` | `logo_path` déprécié |
| `Badge` (max 6) | `optional string icon_file_id = 7` | `icon_path` déprécié |
| `CreateBadgeCommand` (max 4) | `optional string icon_file_id = 5`, `string idempotency_key = 6` | `icon_path` déprécié |
| `UpdateBadgeCommand` (max 5) | `optional string icon_file_id = 6` | `icon_path` déprécié |

Enums : `PostMediaStatus` (`POST_MEDIA_STATUS_UNSPECIFIED`, `_NONE`, `_PENDING`, `_READY`, `_REJECTED`) et `CoverStatus` (`COVER_STATUS_UNSPECIFIED`, `_NONE`, `_PENDING`, `_READY`, `_REJECTED`).

Les numéros sont relevés sur `main` au 2026-10-05 : les revérifier au moment du ticket.

Les URL publiques ne figurent **pas** dans les contrats gRPC métier : la gateway les calcule avec `buildPublicFileUrl`.

## 3. `@volontariapp/messaging`

### Nouveau domaine `storage`

Structure existante : `jobs/<domaine>/` et `events/<domaine>/`. Nommage aligné sur l'existant (`post.publish_post`, `post-queue`).

| Type | Nom | Payload |
| :--- | :--- | :--- |
| Job | `storage.scan_file` | `{ fileId }` |
| Job | `storage.cleanup_files` | `{}` |
| Queue | `storage-queue` | |
| Event | `storage.file_scanned` | `{ fileId, ownerId, entityType, entityId }` |
| Event | `storage.file_rejected` | `{ fileId, ownerId, entityType, entityId, reason }` |
| Event | `storage.attachment_rejected` | `{ fileId, entityType, entityId, reason }`, `reason` parmi `NOT_FOUND`, `WRONG_ENTITY_TYPE`, `NOT_CONFIRMED`, `CONTENT_REJECTED`, `ALREADY_ATTACHED` |

`entityId` est toujours présent : `storage.file_scanned` / `storage.file_rejected` ne sont émis que pour un fichier `ATTACHED`, et `storage.attachment_rejected` concerne toujours une entité nommée par l'événement de confirmation.

### Ajouts dans les domaines existants

| Domaine | Changement |
| :--- | :--- |
| `post` | `post.created` enrichi : `fileIds: string[]` et `userId` obligatoire (aujourd'hui `Partial<IUserIdPayload>`), nécessaires au rattachement asynchrone |
| `event` | `event.created` enrichi : `userId` rendu obligatoire (acteur, déjà présent en optionnel dans `IEventCreatedPayload`) et `coverFileId?` |
| `event` | Nouvel événement `event.cover_replaced` : `{ eventId, userId, newFileId?, oldFileId? }` |
| `user` | Nouveaux événements `user.avatar_replaced` : `{ userId, newFileId?, oldFileId? }`, `user.badge_created` : `{ badgeId, iconFileId? }`, `user.badge_icon_replaced` : `{ badgeId, newFileId?, oldFileId? }`, `user.badge_deleted` : `{ badgeId }` |
| `user` | `IUserPayload.logoPath` déprécié, ajout de `avatarFileId` |
| Fallbacks | Les payloads de fallback de création (event, post si concerné, badge) transportent l'id calculé de l'entité, et ceux de mise à jour transportent le `file_id` concerné |

## 4. `@volontariapp/shared`

`shared/src/enums/streams.enum.ts` regroupe un enum par domaine (`UserStream`, `EventStream`, `PostStream`, `SocialStream`, `WebsocketStream`), fusionnés dans l'objet `Streams` et dans le type union. Les conventions existantes sont mélangées (`post-created`, `event:created`, `event:successfully_created`). **Convention retenue pour les nouveaux streams : `<domaine>:<nom_en_snake_case>`**, comme `event:successfully_created`.

| Enum | Entrées |
| :--- | :--- |
| `StorageStream` (nouveau) | `STORAGE_JOB_OUTBOX_SUCCESS = 'storage:job:outbox:success'`, `STORAGE_JOB_OUTBOX_FAILURE = 'storage:job:outbox:failure'` (déjà utilisés en dur dans `post-processor-storage/src/post-processors/options/`), `STORAGE_FILE_SCANNED = 'storage:file_scanned'`, `STORAGE_FILE_REJECTED = 'storage:file_rejected'`, `STORAGE_ATTACHMENT_REJECTED = 'storage:attachment_rejected'` |
| `EventStream` | `EVENT_COVER_REPLACED = 'event:cover_replaced'` |
| `UserStream` | `USER_AVATAR_REPLACED = 'user:avatar_replaced'`, `USER_BADGE_CREATED = 'user:badge_created'`, `USER_BADGE_ICON_REPLACED = 'user:badge_icon_replaced'`, `USER_BADGE_DELETED = 'user:badge_deleted'` (`USER_DELETED = 'user:deleted'` existe déjà) |

`StorageStream` doit être ajouté à l'objet `Streams` et au type union. Les échecs de saga (`post.creation_failed`, `event.creation_failed`) ne passent pas par un stream dédié : `ws-service` les publie sur `ws:post-created-feedback` et `ws:event-created-feedback` (`WebsocketStream`), streams partagés sur lesquels `pp-storage` filtre par type.

## 5. `@volontariapp/domain-storage`

Le package suit la convention des autres `domain-*` (modèles, repositories, services) :

| Élément | Contenu |
| :--- | :--- |
| Enums | `FileStatus` (+ `RESERVED`), `ScanStatus`, `RejectionReason`, `ValidationMode` |
| Politiques | `VALIDATION_POLICY_BY_ENTITY` : taille max, seuil SYNC (`syncMaxSizeBytes`), ASYNC autorisé (`asyncAllowed`), MIME, format de sortie, nombre max de fichiers par entité. Fonction pure `resolveValidationMode(entityType, declaredSize)`. `image/svg+xml` retiré pour `BADGE_ICON`. |
| Helpers | `buildQuarantineObjectKey`, `buildPublicObjectKey`, `buildPublicFileUrl` |
| Modèle | `FileModel` (TypeORM), table `files` |
| Repository | `PostgresFileRepository` : `createPending`, `confirmUpload`, `switchToAsync`, `resetToAwaitingUpload`, `reserve` (doc 03 section 3), `attachFromConfirmationEvent` (doc 03 section 4, chemins synchrone et asynchrone, même règle de validation que `reserve`), `releaseForEntity` (avec pierre tombale `released_entities`), `releaseFile`, `releaseForOwner`, `completeScan`, `rejectScan`, requêtes de purge. Chaque méthode qui doit émettre un événement écrit dans `event_queue` dans la même transaction. |

`ms-storage`, `worker-storage` et `post-processor-storage` utilisent tous ce repository : aucune duplication de la persistance.

## 6. Packages `domain-*` métier

| Package | Changement |
| :--- | :--- |
| `domain-post` | Id fourni à la création (fin de `@PrimaryGeneratedColumn`, comportement TypeORM à valider). Table `post_media`, colonne `media_status`. `createWithPostCreated` remplace `manager.save` par `INSERT ... ON CONFLICT (id) DO NOTHING` : post, médias et `post.created` dans la même transaction, et si 0 ligne est insérée, pas d'événement, relecture et vérification de l'auteur. Le mapping `23505` de `PostService.create` distingue la clé primaire des autres contraintes. Filtre de visibilité dans `findById` (non-auteur), `listPaginated`, `search`. Mise à jour idempotente de `post_media.scan_status` et recalcul de `media_status` (pour `pp-post`). |
| `domain-event` | Id fourni à la création, insertion `ON CONFLICT (id) DO NOTHING` sans réémission de `event.created`. Colonnes `cover_file_id`, `cover_status`. Mise à jour de la photo : `SELECT ... FOR UPDATE` puis `UPDATE` + `event.cover_replaced` dans la même transaction, rien si le fichier ne change pas. Mise à jour idempotente de `cover_status` (pour `pp-event`). |
| `domain-user` | Colonne `avatar_file_id`. `update` lit l'ancien avatar sous `SELECT ... FOR UPDATE` et écrit `user.avatar_replaced` dans la même transaction, uniquement si l'avatar change (aucun outbox aujourd'hui). `delete` écrit `user.deleted`. Badges : colonne `icon_file_id`, id fourni à la création (insertion `ON CONFLICT (id) DO NOTHING`, id transporté dans le fallback de création), événements `user.badge_created`, `user.badge_icon_replaced`, `user.badge_deleted`. |

## 7. Nouveaux packages

| Package | Contenu |
| :--- | :--- |
| Infrastructure storage (nom à définir) | Client S3 (quarantaine, public, signature POST avec `publicEndpoint`), vérification des magic bytes, client clamd (INSTREAM, port 3310 par défaut), ré-encodage (orientation EXIF, resize, format de sortie, suppression des métadonnées, limite de pixels). |
| Client gRPC storage (nom à définir) | `StorageClient` : propagation de `x-internal-token` dans les `Metadata`, mapping des erreurs gRPC par type guard (aucun cast). Remplace les deux `StorageClientService` dupliqués. |

Le choix des bibliothèques (ré-encodage, client clamd, signature POST) et de leurs versions est fait au moment du ticket, après vérification.

## 8. Schéma SQL `ms_storage`

```sql
CREATE TABLE files (
  id                 uuid PRIMARY KEY,
  owner_id           uuid NOT NULL,
  entity_type        varchar NOT NULL,
  entity_id          uuid NULL,
  status             varchar NOT NULL DEFAULT 'PENDING',
  scan_status        varchar NOT NULL DEFAULT 'AWAITING_UPLOAD',
  rejection_reason   varchar NULL,
  declared_mime_type varchar NOT NULL,
  declared_size      bigint  NOT NULL,
  actual_size        bigint  NULL,
  quarantine_key     varchar NOT NULL,
  public_key         varchar NULL,
  scan_attempts      int     NOT NULL DEFAULT 0,   -- informatif
  rescan_scheduled_at timestamptz NULL,             -- relance unique par la purge
  validation_mode    varchar NOT NULL,              -- SYNC ou ASYNC, calculé à GenerateUploadUrl
  upload_expires_at  timestamptz NOT NULL,
  confirmed_at       timestamptz NULL,
  scanned_at         timestamptz NULL,
  reserved_at        timestamptz NULL,
  attached_at        timestamptz NULL,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_files_entity     ON files (entity_type, entity_id);
CREATE INDEX idx_files_owner      ON files (owner_id);
CREATE INDEX idx_files_awaiting   ON files (upload_expires_at)  WHERE scan_status = 'AWAITING_UPLOAD';
CREATE INDEX idx_files_scanning   ON files (confirmed_at)       WHERE scan_status = 'SCANNING';
CREATE INDEX idx_files_unused     ON files (confirmed_at)       WHERE status = 'PENDING';
CREATE INDEX idx_files_reserved   ON files (reserved_at)        WHERE status = 'RESERVED';
CREATE INDEX idx_files_orphaned   ON files (updated_at)         WHERE status = 'ORPHANED';

CREATE TABLE released_entities (
  entity_type  varchar     NOT NULL,
  entity_id    uuid        NOT NULL,
  released_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (entity_type, entity_id)
);
```

La migration vit dans `ms-storage/src/migrations/domain/`. Les tables communes (`jobs_outbox`, `event_queue`, `job_audit`) existent déjà.

## 9. Configuration

### `ms-storage`

| Clé | Rôle |
| :--- | :--- |
| `port` (3006) | **Conservé** pour `/health`, dont dépend le healthcheck `docker-compose`. |
| `microServices.msStorageUrl` | Nouveau : adresse d'écoute gRPC (`0.0.0.0:5006`). `main.ts` suit le modèle hybride de `ms-post` : `connectMicroservice(getGrpcOptions(GRPC_MICROSERVICES.STORAGE, msStorageUrl))` puis `app.listen(port)`. |
| `s3.endpoint` | Endpoint interne, utilisé pour les opérations des services. |
| `s3.publicEndpoint` | Nouveau : endpoint joignable par le téléphone, utilisé **uniquement** pour signer. |
| `s3.privateBucket` | Nouveau : bucket de quarantaine. |
| `s3.publicBaseUrl` | Nouveau : base des URL publiques (CDN ou endpoint public). |
| `scanner.host`, `scanner.port`, `scanner.timeoutMs` | Nouveau : démon clamd. Un dépassement de `timeoutMs` en SYNC déclenche la bascule ASYNC (post, event) ou le 503 (avatar, badge). |

### `ms-post`, `ms-event`, `ms-user`

| Clé | Rôle |
| :--- | :--- |
| `microServices.msStorageUrl` | Adresse gRPC de `ms-storage` (déjà présente dans `ms-post` et `ms-user`). |
| `storage.attachmentDeadlineMs` | Nouveau : deadline de `ConfirmFileAttachment` (2000). Au-delà, rattachement asynchrone (`ms-post`, `ms-event`) ou 503 (`ms-user`). |

### `ci-tools`

- Service `ms-storage` du `docker-compose` : variables `S3_*` (dont `S3_SECRET_KEY` aligné sur `MINIO_ROOT_PASSWORD`), `MS_STORAGE_URL`.
- Nouveau conteneur clamd.
- `init-buckets.sh` : politique anonyme JSON limitée à `s3:GetObject` sur `volontariapp-public`, règle de lifecycle `quarantine/` sur `volontariapp-private`.

### Méta-dépôt

- `sync-migrations.sh` : ajouter `storage` à `SERVICES`.
