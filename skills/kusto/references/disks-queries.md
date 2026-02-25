# Disks RP Queries — Managed Disk Lifecycle, Existence Check, Storage Layer

Cluster: `disks.kusto.windows.net`
Database: `Disks`

---

## DiskRPResourceLifecycleEvent — Disk Lifecycle

Key columns: `subscriptionId`, `resourceGroupName`, `resourceName`, `diskType`, `diskEvent`, `stage`, `state`, `storageAccountType`, `id` (internal Disk RP ID), `crpDiskId`, `diskSizeBytes`, `blobUrl`, `storageAccountName`

### Find disk by name & subscription

```kusto
cluster("disks.kusto.windows.net").database("Disks").DiskRPResourceLifecycleEvent
| where subscriptionId == "{SubscriptionId}"
| where resourceName == "{DiskName}"
| where PreciseTimeStamp >= ago(90d)
| project PreciseTimeStamp, resourceName, subscriptionId, resourceGroupName,
          diskEvent, stage, state, storageAccountType, diskSizeBytes, id
| order by PreciseTimeStamp asc
```

### Full lifecycle (latest state per disk)

```kusto
cluster("disks.kusto.windows.net").database("Disks").DiskRPResourceLifecycleEvent
| where resourceName == "{DiskName}"
| where subscriptionId == "{SubscriptionId}"
| summarize arg_max(PreciseTimeStamp, *) by resourceName
| project PreciseTimeStamp, resourceName, subscriptionId, resourceGroupName,
          diskEvent, stage, state, storageAccountType, diskOwner, id
```

### Disk lifecycle by storage account

```kusto
cluster('Disks').database('Disks').DiskRPResourceLifecycleEvent
| where (TIMESTAMP >= datetime({StartTime}) and TIMESTAMP <= datetime({EndTime}))
| where subscriptionId == "{SubscriptionId}"
| where storageAccountName == "{StorageAccountName}"
| project TIMESTAMP, resourceName, diskEvent
```

**diskEvent values**: Create, Update, Attach, Detach, Delete, SoftDelete

**state values**: Unattached, Attached, Reserved, ActiveSAS

---

## DiskManagerApiQoSEvent — Backend Existence Check

```kusto
cluster("disks.kusto.windows.net").database("Disks").DiskManagerApiQoSEvent
| where resourceName == "{DiskName}"
| where subscriptionId == "{SubscriptionId}"
| project PreciseTimeStamp, operationName, httpStatusCode, resourceName,
          clientApplicationId, userAgent, region
| order by PreciseTimeStamp desc
| limit 10
```

Interpretation:
- `httpStatusCode == 200` + `clientApplicationId == "Azure Resource Graph"` → Disk **exists**
- `httpStatusCode == 404` → Disk has been **deleted**
- `operationName == "Disks.ResourceOperation.GET"` → ARG periodic crawl

---

## Disk Snapshot Table

Column names differ from lifecycle table: `DisksId`, `DisksName`, `ResourceGroup`, `DiskResourceType`, `OwnershipState`, `AccountType`, `BlobUrl`, `StorageAccountName`, `DiskSizeBytes`, `CrpDiskId`

```kusto
cluster("disks.kusto.windows.net").database("Disks").Disk
| where DisksName has "{DiskName}"
| order by PreciseTimeStamp desc
| limit 5
| project PreciseTimeStamp, DisksId, DisksName, DiskResourceType,
          OwnershipState, AccountType, ResourceGroup, DiskSizeBytes,
          BlobUrl, StorageAccountName, CrpDiskId
```

If not found here, the disk may have been deleted.

---

## AssociatedXStoreEntityResourceLifecycleEvent — Storage Layer

```kusto
cluster("disks.kusto.windows.net").database("Disks").AssociatedXStoreEntityResourceLifecycleEvent
| where parentDiskId == "{DiskRPInternalId}"
    or entityName has "{DiskName}"
| project PreciseTimeStamp, id, parentDiskId, entityName, entityType,
          lifecycleEventType, stage, entityUri, storageAccountName,
          storageAccountType, entitySizeBytes, isHydrated, subscriptionId
| order by PreciseTimeStamp asc
```

---

## ID Cross-Reference

| Source | Table | Key Columns |
|--------|-------|-------------|
| ARM Subscription ID → VM internal IDs | `LogContainerSnapshot` | `subscriptionId` → `containerId`, `nodeId`, `tenantName` |
| Disk Name → Subscription | `DiskRPResourceLifecycleEvent` | `resourceName` → `subscriptionId`, `resourceGroupName` |
| Disk Name → Backend Status | `DiskManagerApiQoSEvent` | `resourceName` → `httpStatusCode` |
| Disk internal ID → Storage | `AssociatedXStoreEntityResourceLifecycleEvent` | `parentDiskId` → `entityUri`, `storageAccountName` |
