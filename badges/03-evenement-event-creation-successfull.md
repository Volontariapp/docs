# 03 - Événement `event.creation_successfull`

**Badge débloqué** : `EVENT_HOST_COUNT_1` (Bâtisseur·se, "Créer 1 événement").

**Statut** : **Implémenté et actif** (`EventCreationSuccessfullBadgePostProcessor` dans `pp-user`).

## Pourquoi cet événement et pas `event.created`

`event.created` est le **déclencheur** de la saga de création. À ce stade, `ms-event` et `ms-social` n'ont pas encore confirmé leur part. Si la saga échoue, l'événement est compensé : le badge aurait été donné pour rien.

`event.creation_successfull` est émis par `ws-service` quand le gather atteint 2/2 (voir `base-gather.post-processor.ts`, `handleCompletion`). C'est le seul signal fiable que l'événement existe vraiment.

## Scénario nominal

```mermaid
sequenceDiagram
    autonumber
    participant F as nativapp
    participant GW as api-gateway
    participant ME as ms-event
    participant MS as ms-social
    participant WS as ws-service
    participant RS as Redis Streams
    participant PE as pp-event
    participant PU as pp-user
    participant UDB as DB ms-user

    F->>GW: POST /events
    GW->>ME: gRPC CreateEvent
    Note right of ME: Transaction : INSERT event (saga PENDING)<br/>+ event_queue event.created
    ME--)RS: event.created
    RS--)MS: consomme, cree le noeud Neo4j
    MS--)RS: event_social.created
    RS--)WS: gather EVENT_CREATION : 2/2
    Note right of WS: Complete : outbox event.creation_successfull<br/>(userId = emitterId)
    WS--)RS: event.creation_successfull
    par Existant
        RS--)PE: saga_status = DONE
    and Nouveau
        RS--)PU: consomme (groupe pp-user)
        PU->>UDB: badges possedes de userId ?
        alt EVENT_HOST_COUNT_1 absent
            PU->>UDB: Transaction : INSERT badge + outbox user.badge_awarded
        else deja possede
            Note right of PU: Sortie immediate, ack
        end
    end
    PU--)RS: user.badge_awarded
    Note over RS,F: Suite : voir 08
```

## Contrat consommé

| Champ | Source | Remarque |
| :--- | :--- | :--- |
| `payload.after.eventId` | gather | Sert à la traçabilité (logs). |
| `payload.after.userId` | `metadata.emitterId` du gather | Utilisateur à récompenser. |

## Règle

```
si "EVENT_HOST_COUNT_1" non possede alors attribuer
```

Aucun compteur : un seuil de 1 ne nécessite aucune mesure.

## Scénarios d'erreur

| Cas | Comportement |
| :--- | :--- |
| Saga en échec | `event.creation_failed` est émis, `event.creation_successfull` ne l'est pas : aucun badge. |
| Livraison en double | La contrainte unique `(user_id, badge_id)` absorbe le doublon, pas de second `user.badge_awarded`. |
| `pp-user` indisponible | Le message reste dans le PEL du groupe, il est rejoué au retour. Le badge arrive en retard, jamais perdu. |
| Événement créé par un admin pour un autre utilisateur | **Edge case accepté** : `userId` vaut `metadata.emitterId` (l'admin), pas l'organisateur (`base-gather.post-processor.ts`, `handleCompletion`). Le badge irait à l'admin. Aucun traitement prévu. |

## Implémenté
 
- Post-processor `EventCreationSuccessfullBadgePostProcessor` dans `pp-user` (`post-processors-runner/post-processor-user/src/post-processors/events/`), groupe de consommation propre sur le stream `Streams.EVENT_SUCCESSFULLY_CREATED`.
- Évaluation et outbox gérées dans `BadgeEvaluator.evaluateEventHostBadge`.
