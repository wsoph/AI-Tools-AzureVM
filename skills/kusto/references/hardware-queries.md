# Hardware Investigation Queries — AzureDCM, Sparkle WHEA/SEL

---

## AzureDCM — Hardware Inventory & Repair History

Cluster: `Azuredcm`
Database: `AzureDCMDb`

### ResourceSnapshotV1 — Identify hostname & IP from NodeId

```kusto
cluster("Azuredcm").database("AzureDCMDb").ResourceSnapshotV1
| where ResourceId == "{NodeId}"
| project ResourceId, IPAddress, HostName, Tenant, Sku, Model, Manufacturer, AvailabilityZone, CloudName, Region
```

### ResourceSnapshotV1 + dcmInventoryComponentDIMM — Memory inventory

```kusto
cluster("Azuredcm").database("AzureDCMDb").ResourceSnapshotV1
| where ResourceId == "{NodeId}"
| project ResourceId, IPAddress, HostName, Tenant, Sku, Model, Manufacturer
| join kind=leftouter (cluster("Azuredcm").database("AzureDCMDb").dcmInventoryComponentDIMM
| where NodeId == "{NodeId}"
| project NodeId, DimmSizeInMB, NumberOfPopulatedDimms) on $left.ResourceId == $right.NodeId
| distinct NodeId, IPAddress, HostName, Tenant, Sku, Model, Manufacturer, DimmSizeInMB, NumberOfPopulatedDimms
```

### ResourceSnapshotV1 + dcmInventoryComponentCPUV2 — CPU inventory

```kusto
cluster("Azuredcm").database("AzureDCMDb").ResourceSnapshotV1
| where ResourceId == "{NodeId}"
| project ResourceId, Tenant, Sku, Model, Manufacturer
| join kind=leftouter (cluster("Azuredcm").database("AzureDCMDb").dcmInventoryComponentCPUV2
| where NodeId == "{NodeId}"
| project NodeId, Name, CurrentClockSpeed, NumberOfCores) on $left.ResourceId == $right.NodeId
| distinct NodeId, Tenant, Sku, Model, Manufacturer, Name, CurrentClockSpeed, NumberOfCores
```

### ResourceSnapshotV1 + dcmInventoryComponentNIC — NIC (Mellanox) versions

```kusto
cluster("Azuredcm").database("AzureDCMDb").ResourceSnapshotV1
| where ResourceId == "{NodeId}"
| project ResourceId, IPAddress, HostName, Tenant, Sku, Model, Manufacturer
| join kind=leftouter (cluster("Azuredcm").database("AzureDCMDb").dcmInventoryComponentNIC
| project NodeId, MellanoxNic_FirmwareVersion, Mlx4BusDriverVersion, Mlx4EthDriverVersion, Mlx5BusDriverVersion, Description) on $left.ResourceId == $right.NodeId
```

### ResourceSnapshotV1 + dcmInventoryAPComponentDisk — Disk inventory

```kusto
cluster("Azuredcm").database("AzureDCMDb").ResourceSnapshotV1
| where ResourceId == "{NodeId}"
| project ResourceId, Tenant, Sku, Model, Manufacturer, HostName
| join kind=leftouter (cluster("Azuredcm").database("AzureDCMDb").dcmInventoryAPComponentDisk
| project MachineName, MediaType, Size) on $left.HostName == $right.MachineName
| distinct ResourceId, Tenant, Sku, Model, Manufacturer, HostName, MachineName, MediaType, Size
```

### ResourceSnapshotHistoryV2 — Node unexpected restart history

```kusto
cluster("Azuredcm").database("AzureDCMDb").ResourceSnapshotHistoryV2
| where ResourceId == "{NodeId}"
| where PowerCycleTime >= datetime({StartTime})
| project PowerCycleTime, UnexpectedRebootTime, RepairCode, RepairResolutionDetails, RepairRequireHardwareDiscovery, PreciseTimeStamp, Tenant
| distinct PowerCycleTime, RepairResolutionDetails, Tenant
```

### ResourceSnapshotHistoryV1 — Node lifecycle & fault codes

```kusto
cluster("Azuredcm").database("AzureDCMDb").ResourceSnapshotHistoryV1
| where ResourceId == "{NodeId}"
| where PreciseTimeStamp >= datetime({StartTime})
| project PreciseTimeStamp, LifecycleState, NeedFlags, FaultCode, FaultDescription, Tenant, ResourceId
```

### RmaDetailsV1 — RMA repair actions

```kusto
cluster("Azuredcm").database("AzureDCMDb").RmaDetailsV1
| where ResourceId == "{NodeId}"
| project TIMESTAMP, RmaDescription
```

### RepairDetailsV1 — Repair history

```kusto
cluster("Azuredcm").database("AzureDCMDb").RepairDetailsV1
| where ResourceId == "{NodeId}"
```

### FaultCodeTeamMapping — Fault code lookup

```kusto
cluster("Azuredcm").database("AzureDCMDb").FaultCodeTeamMapping
| where FaultCode == "20028"
| project FaultCode, FaultReason
```

---

## Sparkle — WHEA & SEL Hardware Errors

Cluster: `sparkle.eastus`
Database: `defaultdb`

WHEA = Windows Hardware Error Architecture events on Windows
SEL = System Event Log on BIOS/Motherboard

### WheaXPFMCAFull — WHEA errors

```kusto
cluster("sparkle.eastus").database("defaultdb").WheaXPFMCAFull
| where NodeId == "{NodeId}"
| where PreciseTimeStamp > ago(7d)
| project TIMESTAMP, ProviderName, ErrorRecordSeverity, PhysicalAddress, Status, RetryReadData
```

### SparkleSELByNodeId — System Event Log

```kusto
cluster("sparkle.eastus").database("defaultdb").SparkleSELByNodeId(nodeId="{NodeId}", startTime=ago(2d), endTime=ago(1h))
```

### SparkleSELByNodeIds — SEL filtered for known hardware failures

```kusto
let nodeId = pack_array("{NodeId}");
let startTime = ago(2d);
let endTime = now();
cluster("sparkle.eastus").database("defaultdb").SparkleSELByNodeIds(nodeId, startTime, endTime)
| where (EventDetail contains "atal") or (EventDetail contains "PCIe") or (EventDetail contains "limit") or (EventDetail contains "nterconnect") or (EventDetail contains "iERR") or (EventDetail contains "orrect")
| summarize arg_max(BMCSelTimestamp, *) by EventDetail, EventDataDetails1, EventDataDetails2, EventDataDetails3
| project BMCSelTimestamp, RecordId, EventDetail, EventDataDetails1, EventDataDetails2, EventDataDetails3, BMCSelItemMessage, SelSource
| sort by BMCSelTimestamp desc
```
