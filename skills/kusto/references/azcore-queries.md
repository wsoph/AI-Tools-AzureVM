# AzCore/RDOS Queries — HyperV, VM Health, Node Service, OS Logs, Performance

Cluster: `azcore.centralus.kusto.windows.net` (also `Rdosmc` for Mooncake, `Rdosff` for FairFax)
Database: `Fa`

---

## Windows Events

### WindowsEventTable — Host node Windows events

```kusto
cluster('azcore.centralus.kusto.windows.net').database('Fa').WindowsEventTable
| where PreciseTimeStamp between(datetime({StartTime})..datetime({EndTime}))
| where NodeId == '{NodeId}'
| where not (ProviderName == "NETLOGON" and EventId == 3095)
| where not (ProviderName == 'IPMIDRV' and EventId == 1004)
| where not (ProviderName == "VhdDiskPrt" and EventId == 47)
| where ProviderName <> "CMClientLib"
| where EventId <> 7000 and EventId <> 1023
| where EventId !in (505, 504, 146, 145, 142)
| project todatetime(TimeCreated), Cluster, Level, ProviderName, EventId, Channel, Description, NodeId
| order by TimeCreated asc
```

EventId filter tips:
- `18500, 18502, ...18560` — HyperV container events
- `2004, 3050, 3122, 12030` — low memory condition
- `ProviderName contains "UpdateNotification"` — VM-PHU update details

---

## VM Performance

### VmCounterFiveMinuteRoleInstanceCentralBondTable — Container performance

```kusto
cluster('azcore.centralus.kusto.windows.net').database('Fa').VmCounterFiveMinuteRoleInstanceCentralBondTable
| where PreciseTimeStamp between (datetime({StartTime}) .. datetime({EndTime}))
| where VmId == '{ContainerId}'
| project PreciseTimeStamp, Cluster, TenantId, NodeId, VmId, RoleInstanceId, CounterName, SampleCount, AverageCounterValue, MinCounterValue, MaxCounterValue
```

### VmShoeboxCounterTable — Shoebox source data

```kusto
cluster('azcore.centralus.kusto.windows.net').database('Fa').VmShoeboxCounterTable
| where PreciseTimeStamp between (datetime({StartTime}) .. datetime({EndTime}))
| where VmId == "{ContainerId}"
| project PreciseTimeStamp, Cluster, RoleInstanceId, VmResourceType, MDMCounterName, MDMAccountName, DurationInMinutes, AverageValue
```

---

## HyperV Investigation

### HyperVHypervisorTable — Hypervisor version

```kusto
cluster('azcore.centralus.kusto.windows.net').database('Fa').HyperVHypervisorTable
| where PreciseTimeStamp between (datetime({StartTime}) .. datetime({EndTime}))
| where NodeId == "{NodeId}"
| where TaskName in ('Hyp version', 'Hal config', 'Hypervisor hotpatch state') or TaskName contains 'config'
| project PreciseTimeStamp, Cluster, TaskName, Message
```

### HyperVAnalyticEvents — HyperV errors & warnings

```kusto
cluster("azcore.centralus.kusto.windows.net").database("Fa").HyperVAnalyticEvents
| where PreciseTimeStamp >= datetime({StartTime}) and PreciseTimeStamp <= datetime({EndTime})
| where NodeId == '{NodeId}' and Level < 4
| extend leveldescription = case(Level <= 2, "error", Level == 3, "warning", "info")
| project PreciseTimeStamp, NodeId, Level, leveldescription, ProviderName, TaskName, EventMessage, Message
```

### HyperVWorkerTable — HyperV worker events

```kusto
cluster("azcore.centralus.kusto.windows.net").database("Fa").HyperVWorkerTable
| where NodeId == "{NodeId}"
| where PreciseTimeStamp between(datetime({StartTime})..2h)
| where Message contains "{ContainerId}" or Message contains "{VMId}"
| where Level <= 4
| project PreciseTimeStamp, EventId, Level, ProviderName, TaskName, Message
```

### HyperVWorkerTable — Memory allocation delays (>120s)

```kusto
cluster("azcore.centralus.kusto.windows.net").database("Fa").HyperVWorkerTable
| where PreciseTimeStamp between(datetime({StartTime})..datetime({EndTime}))
| where NodeId == "{NodeId}"
| where TaskName == "TimeSpentInMemoryOperation" and Message has "ReservingRam" and Message has "CreateRamMemoryBlocks"
| extend length = strlen(Message), secstring = indexof(Message, "Seconds")
| extend strSeconds = substring(Message, secstring+9, length-secstring)
| extend Seconds = trim_end("}", strSeconds)
| where todouble(Seconds) > 120
| project PreciseTimeStamp, Message, Seconds
```

### HyperVVmmsTable — VMMS events

```kusto
cluster("azcore.centralus.kusto.windows.net").database("Fa").HyperVVmmsTable
| where NodeId == "{NodeId}"
| where PreciseTimeStamp >= datetime({StartTime}) and PreciseTimeStamp <= datetime({EndTime})
| project PreciseTimeStamp, Message, Cluster, EventMessage
```

### HyperVStorageStackTable — Storage stack events

```kusto
cluster("azcore.centralus.kusto.windows.net").database("Fa").HyperVStorageStackTable
| where NodeId == "{NodeId}" and PreciseTimeStamp between(datetime({StartTime})..2h)
| where Message contains "{ContainerId}" or Message contains "{VMId}"
| extend leveldescription = case(Level <= 2, "error", Level == 3, "warning", "info")
| project PreciseTimeStamp, Level, leveldescription, ProviderName, TaskName, Message
```

### HyperVVidTable — VID (memory) errors

```kusto
cluster("azcore.centralus.kusto.windows.net").database("Fa").HyperVVidTable
| where NodeId == "{NodeId}"
| where PreciseTimeStamp >= datetime({StartTime}) and PreciseTimeStamp <= datetime({EndTime})
| project PreciseTimeStamp, Cluster, Level, ProviderName, OpcodeName, KeywordName, TaskName, Task, EventMessage, Message
```

Note: VID = Virtual Infrastructure Driver. Memory errors: EventId 5043, 5039, 5038.

---

## VM Health (RDOS perspective)

### VmHealthRawStateEtwTable — VM availability (logged every 15s)

```kusto
cluster("azcore.centralus.kusto.windows.net").database("Fa").VmHealthRawStateEtwTable
| where ContainerId == "{ContainerId}"
| where PreciseTimeStamp >= datetime({StartTime}) and PreciseTimeStamp <= datetime({EndTime})
```

Note: Column `IsVscStateOperational` is always `0` on `AllDisksInStripe` nodes. Use NetVMA/VFPPortMetrics for correct VSC state.

### VmHealthTransitionStateEtwTable — VM state changes only

```kusto
cluster("azcore.centralus.kusto.windows.net").database("Fa").VmHealthTransitionStateEtwTable
| where ContainerId == "{ContainerId}"
| where PreciseTimeStamp >= datetime({StartTime}) and PreciseTimeStamp <= datetime({EndTime})
```

---

## Node Service

### NodeServiceOperationEtwTable — StartContainer timing

```kusto
cluster("azcore.centralus.kusto.windows.net").database("Fa").NodeServiceOperationEtwTable
| where PreciseTimeStamp between (({StartTime}) .. ({EndTime}))
| where NodeId =~ '{NodeId}'
| where Identifier contains "{ContainerId}"
| project PreciseTimeStamp, OperationName, Identifier, Result, ResultCode, RequestTime, CompleteTime
```

If StartContainer > 5 minutes, it indicates performance issues on the node.

### NodeServiceEventEtwTable — RD Agent / node service events

```kusto
cluster("azcore.centralus.kusto.windows.net").database("Fa").NodeServiceEventEtwTable
| where PreciseTimeStamp >= datetime({StartTime}) and PreciseTimeStamp <= datetime({EndTime})
| where NodeId == "{NodeId}"
| where Message contains "{ContainerId}"
```

---

## OS Logs & File Versions

### OsLoggerTable — OS error logs

```kusto
cluster("azcore.centralus.kusto.windows.net").database("Fa").OsLoggerTable
| where NodeId == "{NodeId}"
| where PreciseTimeStamp >= datetime({StartTime}) and PreciseTimeStamp <= datetime({EndTime})
| where ComponentName != "XDiskSvc" and LogErrorLevel == "Error"
| project PreciseTimeStamp, Cluster, NodeId, ActivityId, ComponentName, FunctionName, LogErrorLevel, ResultCode, ErrorDetails
```

### OsFileVersionTable — File version changes on node

```kusto
cluster("azcore.centralus.kusto.windows.net").database("Fa").OsFileVersionTable
| where PreciseTimeStamp >= datetime({StartTime}) and PreciseTimeStamp <= datetime({EndTime})
| where NodeId == "{NodeId}"
| where FileName contains "storahci"
| project PreciseTimeStamp, Cluster, NodeId, FileName, FileVersion
```
