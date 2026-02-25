# VMInsight Queries — VMA RCA, Host Updates, CPU, Windows Events, Air Events

Cluster: `vmainsight.kusto.windows.net`
Databases: `vmadb`, `Air`

---

## Host Node Updates

### RootHENodeGoalVersionChange — Updates running on node

```kusto
cluster("vmainsight").database("vmadb").RootHENodeGoalVersionChange
| where PreciseTimeStamp >= datetime({StartTime}) and PreciseTimeStamp < datetime({EndTime})
| where NodeId == "{NodeId}"
```

### Combined update query (ServiceManager + RootHE + Gandalf + NMAgent)

```kusto
let ServiceManger = (cluster("AzureCM").database("AzureCM").ServiceManagerInstrumentation);
let RootHE = (cluster("Vmainsight").database("vmadb").RootHENodeGoalVersionChange
| extend RootHE_OldValue=OldValue, RootHE_NewValue=NewValue);
let RootHEGaldaf = (cluster('Azcsupfollower').database('AzureCM').RootHEGandalfInformationalEventEtwTable
| extend RootHEGandalf_OldValue=OldVersion, RootHE_NewValueGandalf=NewVersion);
let NMAgent = (cluster('vmainsight.kusto.windows.net').database('Air').AirMaintenanceEvents
| extend PreciseTimeStamp = EventTime
| extend Diagnostics=tostring(Diagnostics));
union ServiceManger, RootHE, RootHEGaldaf, NMAgent
| where PreciseTimeStamp >= datetime({StartTime}) and PreciseTimeStamp < datetime({EndTime})
| where NodeId == "{NodeId}"
| summarize NodeUpdatedAtApprox=min(PreciseTimeStamp) by ServiceVersion, ServiceName, RootHE_OldValue, RootHE_NewValue, RootHEGandalf_OldValue, RootHE_NewValueGandalf, EventCategoryLevel2, EventCategoryLevel3, Component, OutageType, Diagnostics, NodeId
| project-reorder NodeUpdatedAtApprox, NodeId
| order by NodeUpdatedAtApprox asc
```

### ServiceManagerInstrumentation — NMAgent updates

```kusto
cluster("AzureCM").database("AzureCM").ServiceManagerInstrumentation
| where NodeId == "{NodeId}" and ServiceName == "NmAgent" and PreciseTimeStamp > datetime({StartTime})
| summarize min(PreciseTimeStamp) by ServiceVersion, ServiceName
```

---

## Air Events

### AirHostNetworkingUpdateEvents — NMAgent updates & details

```kusto
cluster('vmainsight.kusto.windows.net').database('Air').AirHostNetworkingUpdateEvents
| where EventTime > datetime({StartTime}) and EventTime < datetime({EndTime})
| where NodeId =~ "{NodeId}"
| distinct EventTime, EventCategoryLevel3, EventSource, RCALevel1, OutageType, NodeId
```

### AirManagedEventsBrownouts — HostNetworking update pauses & duration

```kusto
let startTime = datetime({StartTime});
let endTime = datetime({EndTime});
let nodeId = "{NodeId}";
cluster('vmainsight.kusto.windows.net').database('Air').AirManagedEventsBrownouts
| where EventTime between (startTime .. endTime) and NodeId == nodeId
| project EventTime, NodeId, EventType, EventSource, ObjectType, ObjectId, Duration, EventCategoryLevel1, EventCategoryLevel2, EventCategoryLevel3, RCALevel1, RCALevel2, RCALevel3
```

### AirManagedEvents — Host node update investigation

```kusto
let startTime = datetime({StartTime});
let endTime = datetime({EndTime});
let nodeId = "{NodeId}";
cluster('vmainsight.kusto.windows.net').database('Air').AirManagedEvents
| where EventTime between (startTime .. endTime) and NodeId == nodeId
| project EventTime, EventType, EventSource, ObjectType, ObjectId, Duration, EventCategoryLevel1, EventCategoryLevel2, EventCategoryLevel3, RCALevel1
```

### AirDiskIOBlipEvents — Disk IO blip events

```kusto
let startTime = datetime({StartTime});
let endTime = datetime({EndTime});
let nodeId = "{NodeId}";
cluster('vmainsight.kusto.windows.net').database('Air').AirDiskIOBlipEvents
| where EventTime between (startTime .. endTime) and NodeId == nodeId
```

### GetVMPhuEventsBySubId — VMPHU events at subscription level

```kusto
cluster('vmainsight.kusto.windows.net').database('Air').GetVMPhuEventsBySubId('{SubscriptionId}', datetime({StartTime}), datetime({EndTime}))
```

### GetArticleIdByFailureSignature — RCA article lookup

```kusto
cluster('vmainsight').database('Air').GetArticleIdByFailureSignature("HardwareFault.DCM FaultCode 60017")
```

### GetCssWikiLinkByArticleId — Wiki/GitHub link for RCA article

```kusto
cluster('vmainsight').database('Air').GetCssWikiLinkByArticleId("VMA_RCA_Hardware_NodeReboot_Memory_Failure")
```

---

## Host CPU & Windows Events

### HighCpuCounterNodeTable — High CPU on node

```kusto
cluster("vmainsight").database("vmadb").HighCpuCounterNodeTable
| where NodeId == "{NodeId}"
| where PreciseTimeStamp >= datetime({StartTime}) and PreciseTimeStamp <= datetime({EndTime})
```

### WindowsEventTable (vmadb) — Windows events on host node

```kusto
cluster("vmainsight").database("vmadb").WindowsEventTable
| where NodeId == "{NodeId}"
| where PreciseTimeStamp >= datetime({StartTime}) and PreciseTimeStamp <= datetime({EndTime})
| where EventId != "0" and EventId != "505" and EventId != "504" and EventId != "3095"
| project TimeCreated, Cluster, EventId, ProviderName, Description
| order by TimeCreated asc nulls last
```

EventId filter tips:
- `18500, 18502, 18504, 18508, 18510, 18512, 18514, 18516, 18596, 18590, 19060, 18190, 18560` — HyperV container events
- `2004, 3050, 3122, 12030` — low memory condition
- `ProviderName contains "UpdateNotification"` — VM-PHU update details

---

## VMA RCA Tables

### VMA — Fault info, RCA category, support article link

```kusto
let myTable = cluster("Vmainsight").database("vmadb").VMA
| where PreciseTimeStamp >= datetime({StartTime}) and PreciseTimeStamp <= datetime({EndTime})
| where NodeId == "{NodeId}" and RoleInstanceName has "{VMName}"
| distinct PreciseTimeStamp, NodeId, RoleInstanceName, RCAEngineCategory, RCALevel1, RCALevel2, RCA_CSS, Cluster, ContainerId;
myTable
| extend StartTime = now(), EndTime = now(), RCAEngineCategory = ""
| invoke cluster("Vmainsight").database('Air').AddVmRestartSupportArticle()
| project-away StartTime, EndTime, RCAEngineCategory, InternalArticleId
```

### VMA — Filter by subscription, excluding customer-initiated & network

```kusto
cluster("vmainsight").database("vmadb").VMA
| where PreciseTimeStamp >= ago(65d)
| where Subscription == "{SubscriptionId}"
| where Usage_ResourceGroupName == "{ResourceGroupName}"
| where RCALevel1 != "NetworkAvailability"
| summarize count() by bin(StartTime, 15min), RoleInstanceName, RCA, EG_Url
| where count_ > 0
```

### VMALENS — 30-day VM availability impact

```kusto
cluster("vmainsight").database("vmadb").VMALENS()
| where StartTime >= ago(30d)
| where Subscription == "{SubscriptionId}"
| project StartTime, RoleInstanceName, PreciseTimeStamp, LastKnownSubscriptionId, Cluster, NodeId, RCA, RCALevel1, RCALevel2, RCALevel3, SEL_RCA, EscalateToBucket, RCAEngineCategory, LastEvents, EG_Followup, EG_Url
| order by StartTime asc nulls last
```
