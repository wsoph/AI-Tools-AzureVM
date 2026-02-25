# Operations Queries — Hawkeye, Maintenance, Watson Bugchecks, Azure Policy Engine

---

## Hawkeye — Automated Unhealthy Node Analyzer

Cluster: `hawkeyedataexplorer.westus2.kusto.windows.net`
Database: `HawkeyeLogs`

Web UI: `aka.ms/WhyUnhealthy?startTime={StartTime}Z&endTime={EndTime}Z&nodeId={NodeId}`

### GetLatestHawkeyeRCAEvents — Automated RCA

```kusto
cluster('hawkeyedataexplorer.westus2.kusto.windows.net').database('HawkeyeLogs').GetLatestHawkeyeRCAEvents
| where RCATimestamp >= datetime({StartTime}) and RCATimestamp < datetime({EndTime})
| where NodeId == "{NodeId}"
| distinct RCATimestamp, NodeId, RCALevel1, RCALevel2, EscalateToOrg, EscalateToTeam
```

---

## Maintenance & Customer Notifications

Cluster: `icmcluster`
Databases: `ACM.Publisher`, `ACM.Backend`

### GetCommunicationsForSupport — Planned maintenance notifications

```kusto
let ParamSubscriptionId = '{SubscriptionId}';
cluster('icmcluster').database('ACM.Publisher').GetCommunicationsForSupport(Cloud="Public", Subid=ParamSubscriptionId, StartTime=ago(60d), EndTime=now())
| extend JSON = parse_json(list_json) | project-away list_json
| mv-expand JSON
| where JSON.Type contains "Maintenance"
| project Status = tostring(JSON.Status), Type = tostring(JSON.Type), TrackingId = tostring(JSON.TrackingId), ICMNumber = tostring(JSON.LSIID),
MaintenanceStartDate = todatetime(JSON.StartTime), MaintenanceEndDate = todatetime(JSON.EndTime), NotificationCreationDate = todatetime(JSON.CreateDate),
NotificationContent = tostring(JSON.CurrentDescription)
| where NotificationContent !contains "Azure SQL"
| order by MaintenanceStartDate desc
```

### AlbnTargets + PublishRequest — Outage/maintenance notifications

```kusto
cluster('Icmcluster').database('ACM.Publisher').AlbnTargets
| where Subscriptions contains "{SubscriptionId}"
| project CommunicationId
| join cluster('Icmcluster').database("ACM.Backend").PublishRequest on CommunicationId
| where CommunicationDateTime >= datetime({StartTime})
| order by CommunicationDateTime desc
| project CommunicationDateTime, CommunicationType, Title, IncidentId, RichTextMessage, CommunicationId
```

### PublishRequest — Specific incident details

```kusto
cluster('Icmcluster').database("ACM.Backend").PublishRequest
| where IncidentId == "{IncidentId}"
```

---

## Watson — Host Node Bugchecks

Cluster: `Azurewatsoncustomer`
Database: `AzureWatsonCustomer`

### CustomerCrashOccurredV2 — Bugcheck events

```kusto
cluster('Azurewatsoncustomer').database('AzureWatsonCustomer').CustomerCrashOccurredV2
| where PreciseTimeStamp >= datetime({StartTime}) and PreciseTimeStamp <= datetime({EndTime})
| where nodeIdentity == "{NodeId}" and crashMode == "km"
| project PreciseTimeStamp, nodeIdentity, EventMessage, crashMode
```

### CustomerCrashOccurredV2 + CustomerDumpAnalysisResultV2 — Bugcheck with faulting module

```kusto
cluster('Azurewatsoncustomer').database('AzureWatsonCustomer').CustomerCrashOccurredV2
| where PreciseTimeStamp >= datetime({StartTime}) and PreciseTimeStamp <= datetime({EndTime})
| where nodeIdentity == "{NodeId}" and crashMode == "km"
| join kind = leftouter
(cluster('Azurewatsoncustomer').database('AzureWatsonCustomer').CustomerDumpAnalysisResultV2
) on $left.dumpUid == $right.dumpUid
| project PreciseTimeStamp, nodeIdentity, EventMessage, crashMode, faultingModule1, bucketString, dumpType, bugId, bugLink
```

---

## Azure Policy Engine — Host Update Workflow

Cluster: `azpe.kusto.windows.net`
Database: `azpe`

AzPE is used by Orchestrate Manager (OM) to send host update notifications to nodes and tenant approval requests.

### AzPEWorkflowEvent — Host update workflow

```kusto
let starttime = datetime({StartTime});
let endtime = datetime({EndTime});
let nodeid = "{NodeId}";
cluster('azpe.kusto.windows.net').database('azpe').AzPEWorkflowEvent
| where PreciseTimeStamp between (starttime .. endtime)
| where WorkflowId contains nodeid
| where WorkflowType == "OM"
| where EntityId contains "AzPEHostUpdateMonitor"
| project PreciseTimeStamp, WorkflowInstanceGuid, WorkflowId, WorkflowType, WorkflowEventData
| order by PreciseTimeStamp asc
```
