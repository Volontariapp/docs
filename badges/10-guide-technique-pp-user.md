# 10 - Guide Technique pour `pp-user`

Ce document consigne les faits vérifiés dans le code pour implémenter le moteur de badges, afin qu'un agent n'ait pas à refaire les recherches. Chaque fait indique son fichier source. Les éléments **proposés** (à écrire) sont marqués comme tels.

## 1. Structure actuelle de `post-processors-runner/post-processor-user`

| Fichier | Rôle |
| :--- | :--- |
| `src/app.module.ts` | `AppModule.register(config: CustomConfig)` : `ConfigModule`, `InfrastructureModule.forRoot(config)`, `TerminusModule`, `HealthModule` (postgres, redis), `PostProcessorsModule`. |
| `src/config/custom-config.ts` | `CustomConfig extends BaseConfig` avec `db: PostgresConfig`, `redis: RedisConfig`, `postProcessor: PostProcessorConfig`. |
| `src/post-processors/post-processors.module.ts` | Une factory par post-processor : `await dbProvider.connect(); await redisProvider.connect(); new XPostProcessor(dbProvider.getDriver(), redisProvider.getDriver(), options); void postProcessor.start();`. Injecte `NestPostgresProvider`, `NestRedisProvider` et le token d'options. |
| `src/post-processors/options/*-options.ts` | Un provider d'options par post-processor (voir ci-dessous). |
| `src/post-processors/options/constants.ts` | Les tokens d'injection d'options (chaînes). |

Aujourd'hui seuls `JobOutboxSuccessPostProcessor` et `JobOutboxFailedPostProcessor` (importés de `@volontariapp/post-processors`) y sont enregistrés.

### Pattern d'options (copier)

```ts
export const xOptionsProvider = {
  provide: X_POST_PROCESSOR_OPTIONS,
  useFactory: (customConfig: CustomConfig) => ({
    groupName: customConfig.postProcessor.groupName,
    streamName: Streams.<CLE>,
    batchSize: customConfig.postProcessor.batchSize,
    blockTimeout: customConfig.postProcessor.blockTimeout,
    idempotencyTtlSeconds: customConfig.postProcessor.idempotencyTtlSeconds,
    maxRetries: customConfig.postProcessor.maxRetries,
    retryDelayMs: customConfig.postProcessor.retryDelayMs,
  }),
  inject: [CustomConfig],
};
```

Un consumer group Redis est propre à un stream : réutiliser `groupName` sur des streams différents est correct. Pour que `pp-user` lise un stream déjà lu par un autre service (ex. `EVENT_SUCCESSFULLY_CREATED` lu par `pp-event`), il suffit d'un `groupName` différent de celui de l'autre service, à confirmer au moment de l'implémentation (`config` de `pp-user` : `postProcessor.groupName`).

## 2. Squelette d'un post-processor (référence réelle)

Référence : `post-processor-event/src/post-processors/event-creation-successfull.post-processor.ts` et `ws-service/src/post-processors/posts/interactions/post-liked.post-processor.ts`.

```ts
export class XBadgePostProcessor extends BatchPostProcessor<SomeEventType> {
  constructor(private readonly db: DataSource, redisDriver: Redis, options: PostProcessorOptions, /* deps */) {
    super(redisDriver, options);
  }

  protected override shouldProcess(eventType: string): boolean {
    return eventType === SomeEventType.toString();
  }

  protected async processEvents(events: BatchEventItem<SomeEventType>[]): Promise<void> {
    for (const { event, messageId } of events) {
      const payload = event.payload.after;   // charge utile typée
      // event.emitterId, event.correlationId, event.traceId disponibles
    }
  }
}
```

Une erreur levée dans `processEvents` fait rejouer le lot (`maxRetries`, `retryDelayMs`). Un `continue` après un `logger.error` ignore l'élément (pas de rejeu).

## 3. Forger un token interne (décision : `pp-user` s'en forge un)

### Mécanique (vérifiée)

| Élément | Valeur | Source |
| :--- | :--- | :--- |
| Format | JWT RS256, claims = l'objet `AuthUser` (`id: string`, `role: string`, plus champs libres), `jti` aléatoire, `iat`, `exp` | `auth/src/services/jwt.service.ts` (`signInternal`, `sign`) |
| Clé de signature | PKCS8 lue depuis `AuthConfig.internalPrivateKeyPath` | idem |
| Expiration | `AuthConfig.internalExpiresIn` obligatoire (sinon `CONFIG_ERROR`) | idem (`validateExpiration`) |
| Clé de métadonnée gRPC | `x-internal-token` (`INTERNAL_TOKEN_METADATA_KEY`) | `auth/src/constants/index.ts` |
| Vérification côté `ms-*` | `GrpcInternalGuard` (APP_GUARD global) : lit `x-internal-token`, `verifyInternal` avec `internalPublicKeyPath`, exige `id` et `role` en chaîne | `auth/src/guards/grpc-internal.guard.ts`, `ms-social/src/app.module.ts:45` |
| Création de métadonnée | `GrpcMetadataHelper.createInternalMetadata(user: AuthUser): Promise<Metadata>` | `auth/src/services/grpc-metadata.helper.ts` |
| Précédent de forge hors gateway | `api-gateway/.../system-seed.service.ts:62-68` signe `{ id: userId, role: UserRoles.VOLUNTEER }` et ajoute `x-internal-token` | vérifié |

### Ce que `ms-social` contrôle réellement

`GrpcInternalGuard` ne vérifie **que la signature**. Les RPC `Admin*` de `ms-social` (ex. `adminGetUserLikes` dans `interaction.query.controller.ts`) n'ont **aucun contrôle de rôle** : le rôle `ADMIN` est imposé par la gateway (`@Roles(UserRoles.ADMIN)`). Un token valide quelconque suffit donc techniquement.

Les RPC non `Admin` (ex. `getUserLikes`) lisent l'utilisateur dans le token (`@CurrentUser()`), pas dans le payload. Pour `pp-user`, **utiliser les variantes `Admin*`** qui prennent `userId` dans le payload.

### Ce qu'il faut ajouter à `pp-user` (proposé)

1. Dans `CustomConfig` : un bloc `auth` (`internalPrivateKeyPath`, `internalExpiresIn`) et `microServices.msSocialUrl`, sur le modèle de la gateway (`api-gateway/src/config/app-config.service.ts`, champ `config.microServices.msSocialUrl`).
2. Dans `AppModule` : `AuthModule.registerGateway({ internalPrivateKeyPath, internalExpiresIn })`. Cette variante fournit `JwtService` et `GrpcMetadataHelper` sans le guard (`auth.module.ts`, `registerGateway`).
3. Identité du token : `{ id: 'pp-user', role: UserRoles.ADMIN }` (identité de service fixe, rôle `ADMIN` par cohérence avec les RPC `Admin*`). `UserRoles` : `ORGANIZATION`, `VOLUNTEER`, `ADMIN` (`shared/src/enums/user-roles-enum.ts`). Durée courte (quelques minutes) et signature à chaque lot, pas à chaque appel.
4. Montage de la clé privée dans le pod : secret scellé dans le dépôt `deploy` (skill `volontariapp-deploy-gitops`), et règle réseau autorisant `pp-user` vers `ms-social` et `ms-user`.

### Conséquence de sécurité à valider par le Lead Dev

`AGENTS.md`, section 6, fait de la gateway l'unique générateur de `INTERNAL_TOKEN`. Donner la clé privée à `pp-user` en fait un second émetteur capable d'usurper n'importe quel utilisateur auprès de n'importe quel `ms-*`. Décision actée : acceptée pour ce flux. Mitigations : secret scellé, durée courte, identité de service fixe et journalisée (`@volontariapp/logger`), et `pp-user` n'appelle que `ms-social` en lecture.

## 4. Client gRPC vers `ms-social` (proposé, sur le modèle de la gateway)

Références : `api-gateway/src/grpc/grpc-client.options.ts`, `grpc-client.module.ts`, `modules/social/controllers/base-grpc.controller.ts`.

| Élément | Valeur |
| :--- | :--- |
| Enregistrement | `ClientsModule.registerAsync([{ name: SOCIAL_PACKAGE, inject: [...], useFactory: (cfg) => getGrpcOptions(GRPC_MICROSERVICES.SOCIAL, cfg.microServices.msSocialUrl) }])` |
| Imports | `GRPC_MICROSERVICES`, `GRPC_SERVICES`, `getGrpcOptions` depuis `@volontariapp/contracts-nest` |
| Services utiles | `GRPC_SERVICES.INTERACTION_QUERY_SERVICE`, et le service de participation (`ParticipationQueryService` dans `social.services.proto`) |
| Passage du token | métadonnée en second argument de l'appel : `client.adminGetUserLikes(request, metadata)` (le gateway utilise le type `WithMetadata<...>` de `api-gateway/src/common/types/grpc.types.ts`) |

Port gRPC : 3000 (`AGENTS.md`, section 4).

## 5. Compter likes et wishlist : `PaginationResponse` expose un total (vérifié)

`proto-registry/proto/volontariapp/common/pagination.proto` :

```
PaginationRequest  { int32 page = 1; int32 limit = 2; }
PaginationResponse { int32 total = 1; int32 page = 2; int32 limit = 3; int32 total_pages = 4; }
```

Le total est renseigné par `ms-social` (`PaginationMapper.toPaginationResponseDTO` : `page`, `limit`, `total`, `totalPages`). Les réponses de liste portent `ids[]` et `pagination` (`PaginatedIdsMapper`).

Pour obtenir un compte sans transférer de données : demander `page = 1`, `limit = 1` et lire `pagination.total`. Si `pagination` est absent de la requête, `ms-social` applique `PaginationVO(1, 10)`. Valeur minimale acceptée pour `limit` : non vérifiée (utiliser 1, sinon 10).

RPC à appeler :

| Besoin | RPC | Entrée |
| :--- | :--- | :--- |
| Total de posts likés | `AdminGetUserLikes` | `{ userId, pagination }` |
| Total d'événements en wishlist | `AdminGetUserWishEvent` | `{ userId, pagination }` |
| Participants d'un événement | `GetEventParticipants` | `{ eventId, pagination }` (pas de variante admin, pas d'utilisateur dans le token) |

## 6. Écrire les badges (décision : `pp-user` utilise `domain-user`)

### API existante (vérifiée)

| Élément | Détail | Source |
| :--- | :--- | :--- |
| `UserService.addBadgeToUser(userId: UserId, badgeId: BadgeId)` | Charge l'utilisateur, vérifie le badge, **lève `USER_ALREADY_HAS_BADGE`** si déjà possédé, puis appelle le repository. Ne gère ni transaction ni outbox. | `domain-user/src/services/user.service.ts:145` |
| `PostgresUserRepository.addBadgeToUser(userId, badgeId)` | `getRepository('UserBadgeModel').save({ user: {id}, badge: {id} })` | `domain-user/src/repositories/postgres-user.repository.ts:63` |
| `UserBadgeModel` | Table `user_badges`, clé primaire composite `(user_id, badge_id)`, colonne `awarded_at` (`CreateDateColumn`) | `domain-user/src/models/user-badge.model.ts` |
| `BadgeService.findById(BadgeId)` | Utilisé par `UserService` | `domain-user` |

### Pourquoi ne pas appeler `addBadgeToUser` tel quel

1. Il n'écrit pas dans l'outbox : le badge serait attribué sans `user.badge_awarded`.
2. Il lève une erreur sur doublon : le flux doit traiter un doublon comme un succès.
3. Il fait N lectures pour N badges.

### Écriture à implémenter (proposé)

Dans un **seul** `dataSource.transaction(async (manager) => { ... })` :

1. `INSERT INTO user_badges (user_id, badge_id) VALUES ... ON CONFLICT DO NOTHING RETURNING badge_id` pour tous les badges gagnés. Les lignes retournées sont les badges **réellement** nouveaux.
2. S'il y en a au moins un : une ligne d'outbox `user.badge_awarded` avec la liste de ces seuls badges.
3. Les compteurs de participation (voir [07](07-evenement-event-finished.md)) sont mis à jour dans la **même** transaction.

Pour résoudre un slug en `badge_id`, charger les 13 badges une fois (table de 13 lignes) et les garder en mémoire par slug. Le nom exact de la méthode de lecture par slug dans `domain-user` n'est pas relevé : le RPC `GetBadgeBySlug` existe (`badge.query.controller.ts`), donc la capacité existe côté domaine.

## 7. Écrire dans l'outbox

Pattern de référence (`domain-social/src/services/interaction.service.ts:55-66`) :

```ts
const entity = EventQueueEntity.createEvent<UserEventMessagingType.USER_BADGE_AWARDED>({
  type: UserEventMessagingType.USER_BADGE_AWARDED,
  emitter: 'pp-user',
  emitterId: userId,
  payload,                       // { userId, badges: IBadgePayload[] }
  targetServices: [Streams.USER_BADGE_AWARDED],
});
const repo = new EventQueueRepository<UserEventMessagingType.USER_BADGE_AWARDED>(eventQueueTypeormRepository);
await repo.create(entity);
```

Imports : `EventQueueEntity`, `EventQueueModel` depuis `@volontariapp/database` ; `EventQueueRepository` depuis `@volontariapp/outbox`. Pour qu'elle soit dans la transaction, construire le repository TypeORM à partir de `manager.getRepository(EventQueueModel)` (comme le fait `base-gather.post-processor.ts` avec `entityManager.getRepository(EventQueueModel)`). Ne pas reproduire le `try/catch` qui avale l'erreur de `interaction.service.ts` : ici l'échec doit annuler la transaction.

Le `type` et le payload doivent être déclarés dans `messaging` (`EventRegistry`) avant usage : voir [09](09-contrats-et-plan.md).

## 8. Messages publiés avec des particularités à connaître

| Fait | Conséquence | Source |
| :--- | :--- | :--- |
| Dans `post.liked`, `payload.authorId` contient l'id de **celui qui like** (`authorId: userId.value`), pas l'auteur du post. `emitterId` est aussi le liker. | Utiliser `emitterId` (ou `payload.authorId`, identiques). On ne peut pas déduire l'auteur du post depuis ce message : l'exclusion des auto-likes demande un appel supplémentaire. | `interaction.service.ts:51-58` |
| L'écriture outbox de `post.liked` est en best effort : l'erreur est journalisée (`warn`) puis ignorée, et la relation Neo4j est déjà créée. | Un like peut exister sans événement. | `interaction.service.ts:67-71` |
| Succès de saga : `userId = metadata.emitterId ?? userId` | Pour un événement créé par un admin, c'est l'admin (edge case accepté). | `base-gather.post-processor.ts`, `handleCompletion` |

Le compte de likes et de wishlist étant **basé sur l'état** (total courant dans Neo4j), la perte d'un événement est auto-réparée : le prochain like déclenche une nouvelle évaluation qui relit le total. La latence est donc acceptée, sans mécanisme de réconciliation.
