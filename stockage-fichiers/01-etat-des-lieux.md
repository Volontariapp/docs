# 01 - État des lieux

Photographie du code au 2026-10-05, avant implémentation de l'architecture cible. Chaque affirmation a été vérifiée dans le code (chemin indiqué).

## 1. Ce qui existe

### Contrats gRPC (`proto-registry`)

`proto/volontariapp/storage/` définit le service et les messages :

```protobuf
service StorageService {
  rpc GenerateUploadUrl (GenerateUploadUrlCommand) returns (GenerateUploadUrlResponse) {}
  rpc ConfirmFileAttachment (ConfirmFileAttachmentCommand) returns (ConfirmFileAttachmentResponse) {}
  rpc DeleteFile (DeleteFileCommand) returns (DeleteFileResponse) {}
  rpc GetFileMetadata (GetFileMetadataQuery) returns (FileMetadataResponse) {}
  rpc VerifyFilesExist (VerifyFilesExistQuery) returns (VerifyFilesExistResponse) {}
}
```

- `FileStatus` : `PENDING`, `ATTACHED`, `ORPHANED`, `DELETED`.
- `EntityType` : `POST`, `USER_AVATAR`, `BADGE_ICON`, `EVENT_COVER`.
- `FileMetadata` : `id`, `owner_id`, `object_key`, `mime_type`, `status`, `entity_type`, `entity_id`, `is_public`, horodatages (champs 1 à 11).
- Types TypeScript générés dans `@volontariapp/contracts` et `@volontariapp/contracts-nest`. `GRPC_MICROSERVICES.STORAGE` existe déjà (`contracts-nest/src/grpc.helpers.ts`).

### Champs image déjà présents dans les autres domaines

- `users.logo_path` : colonne (`domain-user/src/models/user.model.ts:27`), champ `logo_path` dans `SignUpCommand` et `UpdateUserCommand` (`user/user.command.proto`), dans `User` et `UserPublic` (`user/user.proto`), et `IUserPayload.logoPath` dans `messaging`.
- `Badge.icon_path` (`user/user.proto`).
- Ces champs stockent un chemin libre, sans lien avec `ms-storage`.

### Domaine partagé (`@volontariapp/domain-storage@0.3.0`)

- Enums `FileStatus`, `EntityType`.
- Value objects `FileId`, `MimeType`.
- `ALLOWED_MIME_TYPES_BY_ENTITY` : jpeg / png / webp pour tous, plus `image/svg+xml` pour `BADGE_ICON`.
- Exceptions `FileNotFoundException`, `InvalidFileExtensionException`.
- Interfaces d'options S3 (`GeneratePresignedUploadUrlOptions`, etc.).
- Aucun modèle TypeORM ni repository, contrairement aux autres `domain-*`.

### Microservice `ms-storage`

- `S3Service` (`src/providers/s3/s3.service.ts`) : URL signée PUT, URL signée GET, `HeadObject`, `DeleteObject`. Opère uniquement sur `publicBucket`.
- Configuration S3 validée (`src/config/s3-config.ts`), endpoint `http://localhost:9000`, TTL des URL signées : 900 s.
- Tables communes présentes (`src/migrations/common/`) : `jobs_outbox`, `event_queue`, `job_audit` et leurs triggers.
- Tests unitaires et d'intégration du `S3Service`.

### Runners storage

- `outbox-runners/outbox-storage`, `workers-runners/worker-storage`, `post-processors-runner/post-processor-storage` existent. `worker-storage` et `post-processor-storage` pointent déjà sur la base `ms_storage` (`config/default.config.json`).
- Aucun handler métier dans `worker-storage` ni dans `post-processor-storage`.

### Infrastructure locale (`ci-tools`)

- MinIO + conteneur `minio-init` (`scripts/init-buckets.sh`) qui crée `volontariapp-public` (`mc anonymous set download`) et `volontariapp-private`.
- Base `postgres-storage` (`ms_storage`), `MS_STORAGE_URL: ms-storage:5006`.

### Consommateurs

- `ms-post` : `createPost` appelle `StorageClientService.verifyFilesExist(data.fileIds)`.
- `ms-user` : `updateUser` appelle `verifyFilesExist([data.avatarFileId])`.
- `nativapp` : `expo-image-picker` dans `src/components/profile/ProfileEditModal.tsx`. Après sélection, une alerte "Coming soon" est affichée. Aucun upload.

### Événements existants réutilisables

Vérifiés avec `analyze_impact` (mesh-mcp) :

| Événement | Émetteur | Remarque |
| :--- | :--- | :--- |
| `post.created` | `domain-post`, `postgres-post.repository.ts` (`createWithPostCreated`) | Écrit dans la même transaction que l'insertion. |
| `post.deleted` | `domain-post` | Même transaction que la suppression. |
| `event.created` | `domain-event`, `postgres-event.repository.ts` (`createWithEventCreated`) | Même transaction que l'insertion. |
| `event.deleted` | `domain-event` | Même transaction que la suppression. |
| `post.creation_failed`, `event.creation_failed` | `ws-service`, agrégation Scatter-Gather (`base-gather.post-processor.ts`) | Publiés sur `ws:post-created-feedback` / `ws:event-created-feedback`. Seul `pp-event` passe l'entité en `CANCEL` ; un post en échec reste `PENDING`. |
| `user.deleted` | **Aucun émetteur** | Type et payload déclarés dans `messaging`, consommé par `post-processor-social` et `ws-service`. |

## 2. Ce qui manque ou est cassé

| # | Problème | Conséquence |
| :--- | :--- | :--- |
| 1 | Aucun handler `@GrpcMethod` pour `StorageService` (`analyze_grpc` : 0 serveur) | Tout appel à `ms-storage` échoue. |
| 2 | `ms-storage/src/main.ts` démarre en HTTP seul (`app.listen(3006)`), sans `connectMicroservice` | `ms-post` / `ms-user` ciblent `ms-storage:5006` en gRPC. |
| 3 | `S3Module` non importé dans `AppModule` | `S3Service` jamais instancié. |
| 4 | Aucune table `files` (seule migration de domaine : extension `uuid-ossp`) | Pas de métadonnées, pas de statut. |
| 5 | `S3Service` n'utilise que le bucket public | Fichiers non scannés lisibles anonymement. |
| 6 | URL signée avec l'endpoint `localhost:9000` | URL inutilisable depuis un téléphone (l'hôte fait partie de la signature). |
| 7 | Le service `ms-storage` du `docker-compose` ne reçoit aucune variable `S3_*` | Configuration S3 par défaut en conteneur. |
| 8 | `verifyFilesExist` ne vérifie que l'existence | Un utilisateur peut attacher le fichier d'un autre. |
| 9 | `fileIds` (`CreatePostCommandDTO`) et `avatarFileId` (`UpdateUserCommandDTO`) absents des `.proto` post et user | Ces champs ne peuvent jamais arriver par gRPC : la vérification actuelle est du code mort. |
| 10 | Ids d'entité générés par la base (`@PrimaryGeneratedColumn('uuid')` dans `domain-post/src/models/post.model.ts` et `domain-event/src/models/event.model.ts`) | Impossible de réserver un fichier pour une entité avant son insertion. |
| 11 | Les fallbacks rejouent la création sans id (`worker-event/.../fallback-create-event.handler.ts`) | Le rejeu crée une entité avec un autre id. |
| 12 | `ms-event` n'a aucun champ image (ni code, ni proto) | Photo d'événement à concevoir entièrement. |
| 13 | `messaging` n'a pas de domaine `storage`, l'enum `Streams` (`@volontariapp/shared`) n'a pas de streams storage | Pas de scan asynchrone possible. |
| 14 | `user.deleted` n'est émis par personne, `UserService.delete` n'écrit aucun événement | Impossible de libérer les fichiers d'un compte supprimé. |
| 15 | `deleteByAuthorId` (`postgres-post.repository.ts`) supprime des posts sans émettre `post.deleted` | Fuite latente de fichiers si un appelant apparaît. |
| 16 | Un échec de saga d'événement passe l'entité en `saga_status = CANCEL` sans la supprimer, un échec de saga de post la laisse en `PENDING` (`post-processor-event/.../event-creation-failed.post-processor.ts`) | Aucun `*.deleted` émis : fichiers jamais libérés si rien n'est prévu. |
| 17 | Aucune requête de lecture de `domain-post` ne filtre sur un statut (`listPaginated`, `search`) | Aucun mécanisme existant pour masquer un post. |
| 18 | `mc anonymous set download` applique la politique "readonly" de MinIO, qui accorde aussi le listing du bucket (à confirmer avec `mc anonymous get-json`) | Les images publiques sont énumérables. |
| 19 | Pas de scanner antimalware dans `docker-compose` | Pas de scan possible en local. |
| 20 | `StorageClientService` dupliqué à l'identique dans `ms-post` et `ms-user`, avec un cast `err as {...}` | Violation DRY et du typage strict. |
| 21 | `sync-migrations.sh` ne connaît pas `storage` (`SERVICES=("user" "social" "post" "event")`) | Migrations communes non synchronisées pour `ms-storage`. |
| 22 | Aucun rate limiting dans `api-gateway` | Génération d'URL signées non bornée. |

## 3. Incohérences de configuration

- `ms-storage/config/default.config.json` : `secretKey: "minioadmin"`, alors que `docker-compose` définit `MINIO_ROOT_PASSWORD: minioadminpassword`.
- `GenerateUploadUrlCommand.is_public` laisse le client choisir la visibilité.

## 4. Documentation et bug connexes

La table d'événements s'appelle **`event_queue`** et la fonction de trigger **`notify_job_audit_status_change`** (statuts `COMPLETED` / `FAILED`, événements `<domaine>:job:outbox:success|failure`). `docs/C3-Async-Patterns-And-Flows.md` et les skills `implement-async-job-flow`, `implement-async-event-flow`, `trace-async-flow` ont été corrigés en ce sens.

**Bug connu, hors périmètre storage** : `JobOutboxFailedPostProcessor` (`npm-packages/packages/post-processors/src/common/job-outbox-failed.post-processor.ts`) n'accepte que les types `job.outbox.failed` ou `*:job:outbox:failed`, alors que le trigger émet `*:job:outbox:failure`. Les échecs de jobs ne sont jamais traités et aucun feedback d'échec n'est émis. Même filtre corrigé, son `UPDATE ... WHERE status = PENDING` ne toucherait rien : la ligne `jobs_outbox` est déjà `COMPLETED` depuis le push BullMQ (`outbox.consumer.ts`). Voir [11-scenarios-de-panne.md](11-scenarios-de-panne.md), problème P4.
