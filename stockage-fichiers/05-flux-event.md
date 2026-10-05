# 05 - Flux Event, photo de l'événement

**Cas d'usage** : un organisateur ajoute ou remplace la photo d'un événement, à la création ou plus tard.

**Règle produit (proposée, à valider)** : la photo décore l'événement, elle n'en est pas le contenu. L'événement est **visible immédiatement**. Tant que la photo n'est pas validée (`cover_status != READY`), le front affiche un placeholder.

**Modes** ([02-architecture-cible.md](02-architecture-cible.md), section 3) : traitement SYNC par défaut, ASYNC si la photo est volumineuse ou si le traitement synchrone échoue techniquement. Rattachement synchrone par défaut, asynchrone si `ms-storage` est indisponible.

> [!NOTE]
> `ms-event` ne contient aujourd'hui aucun champ image, ni dans le code ni dans `event.proto`. La création passe par `withFallback`, qui peut rejouer l'insertion depuis `worker-event` plusieurs minutes plus tard. Ce fallback couvre l'échec de l'opération d'écriture, **pas** l'indisponibilité de la base : il écrit son job dans la même base (`base.command.controller.ts`). Il est indépendant du rattachement asynchrone (`ms-storage` indisponible) : les deux peuvent se combiner.

## 1. Création d'un événement avec photo

```mermaid
sequenceDiagram
    autonumber
    participant F as nativapp
    participant GW as api-gateway
    participant ST as ms-storage
    participant W as worker-storage
    participant E as ms-event
    participant WE as worker-event
    participant RS as Redis Streams
    participant PS as pp-storage
    participant PE as pp-event
    participant WS as ws-service

    Note over F,W: Phases 1 et 2 - Upload et confirmation, identiques au flux Post
    F->>ST: GenerateUploadUrl (EVENT_COVER), POST signé, ConfirmUpload
    Note right of ST: SYNC (1 Mo ou moins) : CLEAN immédiat<br/>ASYNC (volumineux ou erreur technique) : SCANNING
    ST--)W: Job storage.scan_file (ASYNC uniquement)

    Note over F,E: Phase 3 - Création
    F->>GW: POST /events (..., coverFileId, idempotencyKey)
    GW->>E: gRPC CreateEvent
    Note right of E: eventId = UUID v5(ownerId, idempotencyKey)
    E->>ST: gRPC ConfirmFileAttachment([coverFileId], EVENT_COVER, eventId), deadline 2 s
    Note right of E: Appel AVANT withFallback
    alt Réservation refusée
        ST-->>E: NOT_FOUND ou FAILED_PRECONDITION
        E-->>F: 404 ou 422
    else Réservation OK
        ST-->>E: FileMetadata (scan_status)
        Note right of E: cover_status = READY si CLEAN, sinon PENDING
    else ms-storage indisponible (UNAVAILABLE, DEADLINE_EXCEEDED)
        Note right of E: Rattachement asynchrone : cover_status = PENDING<br/>pp-storage validera le fichier
    end
    opt Réservation OK ou ms-storage indisponible
        alt Base ms-event disponible
            Note right of E: Transaction domain-event :<br/>INSERT event ON CONFLICT (id) DO NOTHING<br/>cover_file_id, cover_status<br/>+ event_queue event.created (userId, coverFileId)
            E-->>F: 201 (event visible, placeholder si PENDING)
            E--)RS: event.created
        else Échec de l'écriture : withFallback
            E--)WE: Job fallback avec eventId et cover_status dans le payload
            E-->>F: FALLBACK_ACTIVATED
            Note right of WE: Rejoue plus tard la même transaction<br/>avec le même eventId
            WE--)RS: event.created (au rejeu)
        end
        RS--)PS: consomme
        Note right of PS: Algorithme unique (doc 03 section 4) :<br/>RESERVED ou PENDING validé vers ATTACHED<br/>+ résultat du scan si déjà traité<br/>fichier invalide : storage.attachment_rejected
    end

    Note over W,WS: Phase 4 - Résultat, émis par W, ST ou PS selon l'ordre
    par Mise à jour métier
        RS--)PE: storage.file_scanned / file_rejected / attachment_rejected (EVENT_COVER)
        Note right of PE: Ignore si fileId != events.cover_file_id<br/>Event supprimé entre temps : acquitter (warn)
        PE->>E: UPDATE events.cover_status = READY ou REJECTED
    and Notification
        RS--)WS: consomme
        WS--)F: push "photo validée" ou "photo refusée"
    end
```

## 2. Remplacement ou suppression de la photo

`UpdateEventCommand` fonctionne avec `Event event` + `update_mask`. Le champ `cover_file_id` est ajouté **uniquement dans `Event`** et adressé par le masque, pour ne pas créer un second chemin de mise à jour.

```mermaid
sequenceDiagram
    autonumber
    participant F as nativapp
    participant GW as api-gateway
    participant ST as ms-storage
    participant E as ms-event
    participant RS as Redis Streams
    participant PS as pp-storage

    F->>GW: PATCH /events/{id} (coverFileId ou null)
    GW->>E: gRPC UpdateEvent(event.cover_file_id, update_mask = [cover_file_id])
    opt Nouvelle photo
        E->>ST: gRPC ConfirmFileAttachment([newFileId], EVENT_COVER, eventId), deadline 2 s
        alt Réservation OK
            ST-->>E: FileMetadata (scan_status)
        else Refus
            ST-->>E: NOT_FOUND ou FAILED_PRECONDITION
            E-->>F: 404 ou 422, rien n'est écrit
        else ms-storage indisponible
            Note right of E: Rattachement asynchrone, cover_status = PENDING
        end
    end
    Note right of E: Transaction domain-event :<br/>SELECT cover_file_id FOR UPDATE (oldFileId)<br/>UPDATE cover_file_id, cover_status<br/>+ event_queue event.cover_replaced(eventId, userId, newFileId, oldFileId)
    E-->>F: 200
    E--)RS: event.cover_replaced
    RS--)PS: consomme
    Note right of PS: newFileId : RESERVED ou PENDING validé vers ATTACHED (+ résultat si traité)<br/>oldFileId : PENDING, RESERVED ou ATTACHED vers ORPHANED
```

## 3. Règles

- **Lecture de l'ancienne photo sous verrou** : `oldFileId` est lu avec `SELECT ... FOR UPDATE` dans la transaction qui écrit `event.cover_replaced`. Deux remplacements simultanés produisent ainsi deux événements chaînés (A vers B, puis B vers C), et aucun fichier intermédiaire n'échappe à la libération.
- **Même photo renvoyée** : si `cover_file_id` ne change pas, `domain-event` n'écrit ni mise à jour ni `event.cover_replaced`.
- **Photo invalide en rattachement asynchrone** : `storage.attachment_rejected` conduit `pp-event` à passer `cover_status = REJECTED` (si le `fileId` est toujours le `cover_file_id` courant). La photo n'a jamais été affichée.
- **Photo rejetée** : `cover_status = REJECTED`, l'événement reste visible avec le placeholder. L'organisateur est notifié et peut envoyer une autre photo.
- **Remplacement pendant le scan** : `pp-event` ignore les résultats de scan dont le `fileId` n'est plus le `cover_file_id` courant.
- **Suppression de la photo** : `cover_file_id = null` via le masque, `cover_status = NONE`, `event.cover_replaced` émis avec `newFileId` absent.
- **Suppression de l'événement** : `event.deleted` (existant) est consommé par `pp-storage`, qui libère la photo et écrit une pierre tombale.

Les scénarios de panne détaillés sont dans [11-scenarios-de-panne.md](11-scenarios-de-panne.md).
- **Échec de la saga de création** : `event.creation_failed` est émis par `ws-service` (agrégation Scatter-Gather) sur le stream `ws:event-created-feedback`, partagé avec d'autres types. `pp-storage` filtre sur le type, comme le fait déjà `pp-event` (`event-creation-failed-options.ts`), et libère la photo. `pp-event` passe l'événement en `saga_status = CANCEL`.
- **Saga** : `cover_status` est une colonne distincte de `saga_status`. Elles ne doivent pas être confondues.
