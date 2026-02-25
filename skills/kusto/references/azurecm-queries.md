# AzureCM Queries — Container, Node, Fault, Recovery, Service Healing, Live Migration

Cluster: `azurecm.kusto.windows.net` (or `Azcsupfollower.kusto.windows.net`)
Database: `AzureCM`

---

## Container State & Operation

### LogContainerSnapshot — VM host placement history

```kusto
let sid="{SubscriptionId}";
let vmname="{VMName}";
cluster("AzureCM").database("AzureCM").LogContainerSnapshot
| where subscriptionId == sid and roleInstanceName has vmname
| summarize min(PreciseTimeStamp), max(PreciseTimeStamp) by roleInstanceName, creationTime, virtualMachineUniqueId, Tenant, containerId, nodeId, tenantName, containerType, updateDomain, availabilitySetName, subscriptionId
| project VMName=roleInstanceName, VirtualMachineUniqueId=virtualMachineUniqueId, Cluster=Tenant, NodeId=nodeId, ContainerId=containerId,
    ContainerCreationTime=todatetime(creationTime), StartTimeStamp=min_PreciseTimeStamp, EndTimeStamp=max_PreciseTimeStamp, tenantName, containerType, updateDomain, availabilitySetName, subscriptionId
| order by ContainerCreationTime asc
```

### LogContainerSnapshot — VMs on a specific node (last 3 days)

```kusto
cluster("AzureCM").database("AzureCM").LogContainerSnapshot
| where nodeId == "{NodeId}"
| where PreciseTimeStamp > ago(3d)
| distinct creationTime, roleInstanceName, subscriptionId, containerType, virtualMachineUniqueId, nodeId, containerId
```

### LogContainerHealthSnapshot — Container health & OS state

```kusto
cluster('Azcsupfollower.kusto.windows.net').database('AzureCM').LogContainerHealthSnapshot
| where PreciseTimeStamp between (datetime({BeginTime}) .. datetime({EndTime}))
| where roleInstanceName contains "{VMName}"
| project PreciseTimeStamp, Tenant, roleInstanceName, tenantName, containerId, nodeId,
  containerState, actualOperationalState, containerLifecycleState, containerOsState, faultInfo, vmExpectedHealthState, virtualMachineUniqueId,
  containerIsolationState, AvailabilityZone, Region
```

Filter tips:
- `containerOsState == "ContainerOsStateUnresponsive"` — guest OS unresponsive
- `containerOsState == "GuestOsStateProvisioningRecovery"` — provisioning recovery
- `faultInfo <> ""` — CreateContainer failures

### LogContainerSnapshot + Gandalf — Unallocatable node check

```kusto
let dateTime_StartTime = datetime_add('day', -8, {BeginTime});
let dateTime_EndTime = datetime_add('hour', +1, {BeginTime});
let subscriptionId = '{SubscriptionId}';
let vmName = '{VMName}';
cluster('Azcsupfollower').database('AzureCM').LogContainerSnapshot
| where PreciseTimeStamp between(dateTime_StartTime..dateTime_EndTime)
| where subscriptionId =~ subscriptionId and roleInstanceName has vmName
| project-rename ContainerId = containerId
| distinct nodeId, ContainerId
| join kind = inner
(cluster('Gandalf').database('gandalf').GandalfUnallocableNodesHistorical
| project-rename FoundTimestamp = PreciseTimeStamp
| where State == "Unallocatable") on $left.nodeId == $right.NodeId
| join kind = inner
(cluster('Azcsupfollower').database('AzureCM').LogContainerHealthSnapshot
| where PreciseTimeStamp >= {BeginTime} and containerState has "ContainerStateDestroyed"
| project-rename IssueTimestamp = PreciseTimeStamp
) on $left.nodeId == $right.nodeId
| where containerId == ContainerId
| where (IssueTimestamp - datetime_add('day', +7, FoundTimestamp)) between (0min .. 10min)
| distinct FoundTimestamp, State, nodeId, IssueTimestamp, ContainerId, containerState
```

---

## Node Events on Cluster Manager

### TMMgmtNodeStateChangedEtwTable — Node state changes / reboots

```kusto
cluster("AzureCM").database("AzureCM").TMMgmtNodeStateChangedEtwTable
| where BladeID == "{NodeId}"
| where PreciseTimeStamp >= datetime({BeginTime}) and PreciseTimeStamp <= datetime({EndTime})
| project PreciseTimeStamp, BladeID, OldState, NewState
```

### TMMgmtNodeStateChangedEtwTable — Multiple node reboots on same cluster

```kusto
cluster("AzureCM").database("AzureCM").TMMgmtNodeStateChangedEtwTable
| where PreciseTimeStamp >= datetime({BeginTime}) and PreciseTimeStamp <= datetime({EndTime})
| where Tenant == "{Cluster}"
| where NewState == "Booting"
| project PreciseTimeStamp, BladeID, OldState, NewState
```

### LogNodeSnapshot — Unallocatable, OFR, node state

```kusto
cluster('Azcsupfollower.kusto.windows.net').database('AzureCM').LogNodeSnapshot
| where nodeId =~ "{NodeId}" and PreciseTimeStamp >= datetime({BeginTime}) and PreciseTimeStamp <= datetime({EndTime})
| project PreciseTimeStamp, nodeState, nodeAvailabilityState, containerCount, diskConfiguration, faultInfo, rootUpdateAllocationType, RoleInstance
```

Filter tips:
- `nodeState == "PoweringOn"` — node restart
- `nodeAvailabilityState == "Unallocatable"` — node marked unallocatable
- `diskConfiguration == "AllDisksInStripe"` — disk config change

### LogNodeSnapshot — Check if node is OFR

```kusto
cluster("AzureCM").database("AzureCM").LogNodeSnapshot
| where PreciseTimeStamp >= ago(2h) and nodeId == "{NodeId}" and Tenant == "{Cluster}" and nodeState == "OutForRepair"
```

### TMMgmtNodeEventsEtwTable — Detailed node operations

```kusto
cluster("AzureCM").database("AzureCM").TMMgmtNodeEventsEtwTable
| where NodeId == "{NodeId}"
| where PreciseTimeStamp >= datetime({BeginTime}) and PreciseTimeStamp <= datetime({EndTime})
| project PreciseTimeStamp = tostring(PreciseTimeStamp), Message
| sort by PreciseTimeStamp asc
```

Message filter tips:
- `"Node reboot event: EventType:"` — reboot events
- `"->"` — state transitions (e.g., Ready -> HumanInvestigate)
- `"Marking container"` — VM stopped by fabric
- `"Fault Code: 10005"` — start container failures
- `"Not enough memory"` — OOM conditions
- `"PrepareMode"` — disk config changes requiring reboot

### TMMgmtNodeEventsEtwTable — Dirty shutdown confirmation

```kusto
let timeSpan = 7d;
let NodeIdentifier = "{NodeId}";
cluster("AzureCM").database("AzureCM").TMMgmtNodeEventsEtwTable
| where NodeId == NodeIdentifier and PreciseTimeStamp >= ago(timeSpan) and Message contains "Node reboot event: EventType: "
| parse Message with "Node reboot event: EventType: " eventType "," * "EventTimeStamp: " eventTimeStamp:datetime "," *
| project PreciseTimeStamp, eventTimeStamp, RoleInstance, Tenant, NodeId, eventType, Message
| where eventType in ("DirtyShutdown", "BugCheck", "PXEEvent")
| union(
cluster("AzureCM").database("AzureCM").TMMgmtNodeEventsEtwTable
| where NodeId == NodeIdentifier and PreciseTimeStamp >= ago(timeSpan) and Message contains "EventType: FabricInitiatedPowerCycleFaultHandler"
| project PreciseTimeStamp, eventTimeStamp = PreciseTimeStamp, RoleInstance, Tenant, NodeId, eventType = "UnhealthyNodePowerCycle", Message
)
| where eventType == "DirtyShutdown"
```

### TMMgmtContainerTraceEtwTable — Detailed container events

```kusto
cluster("AzureCM").database("AzureCM").TMMgmtContainerTraceEtwTable
| where PreciseTimeStamp >= datetime({BeginTime}) and PreciseTimeStamp < datetime({EndTime})
| where ContainerID == "{ContainerId}"
| project PreciseTimeStamp, ContainerID, Message
```

### TMMgmtTenantEventsEtwTable — Fabric-triggered operations

```kusto
cluster("AzureCM").database("AzureCM").TMMgmtTenantEventsEtwTable
| where TenantName == "{TenantName}"
| where PreciseTimeStamp > datetime({BeginTime}) and PreciseTimeStamp < datetime({EndTime})
| project PreciseTimeStamp, TaskName, TenantName, Message
```

Message filter tips:
- `"unhealthy"` — unhealthy node trigger of SH
- `"LiveMigration"` — live migration events
- `"Not enough memory in the system to start"` — host node OOM

### TMMgmtTenantEventsEtwTable — OOM at cluster level

```kusto
let err = "Not enough memory in the system to start";
cluster("AzureCM").database("AzureCM").TMMgmtTenantEventsEtwTable
| where Message contains err
| where PreciseTimeStamp >= datetime({BeginTime})
| parse Message with * ' NodeId: ' NodeId '. StatusCode:' SC
| project PreciseTimeStamp, Tenant, NodeId, TenantName
| summarize count() by NodeId, Tenant
```

### TMMgmtSlaMeasurementEventEtwTable — Container & tenant state details

```kusto
cluster("AzureCM").database("AzureCM").TMMgmtSlaMeasurementEventEtwTable
| where PreciseTimeStamp >= datetime({BeginTime}) and PreciseTimeStamp < datetime({EndTime})
| where ContainerID == "{ContainerId}"
| project PreciseTimeStamp, Context, EntityState, Detail0, Tenant, TenantName, RoleInstanceName, NodeID, ContainerID, Region
```

Filter: `EntityState == "GuestOsStateHardPowerOff"` — hard power off

---

## Node Fault & Recovery (Anvil/Tardigrade)

### AnvilRepairServiceForgeEvents — Anvil recovery actions

```kusto
cluster('aplat.westcentralus.kusto.windows.net').database('APlat').AnvilRepairServiceForgeEvents
| where PreciseTimeStamp >= datetime({BeginTime}) and PreciseTimeStamp <= datetime({EndTime})
| where ResourceDependencies has_any ("{NodeId}")
| where TreeNodeKey !in ('Root', 'Node')
| summarize arg_max(PreciseTimeStamp, *) by RequestIdentifier, TreeNodeKey
| order by RequestIdentifier, PreciseTimeStamp asc
| project PreciseTimeStamp, AnvilOperation=TreeNodeKey, NodeId=tostring(parse_json(ResourceDependencies).NodeId), AnvilRequestIdentifier=RequestIdentifier, ResourceId, ResourceType
| sort by PreciseTimeStamp asc
```

### FaultHandlingRecoveryEventEtwTable — Fabric recovery actions

```kusto
cluster("AzureCM").database("AzureCM").FaultHandlingRecoveryEventEtwTable
| where NodeId == "{NodeId}"
| where PreciseTimeStamp >= datetime({BeginTime}) and PreciseTimeStamp <= datetime({EndTime})
| project PreciseTimeStamp, NodeId, Reason, RecoveryAction, RecoveryResult
```

RecoveryAction values: `PowerCycle`, `RestartNodeService`, `HumanInvestigate`, `ResetNodeHealth`, `RebootNode`, `MarkNodeAsUnallocatable`

### DCMLMResourceResultEtwTable — BMC-SEL hardware faults at node restart

```kusto
cluster("AzureCM").database("AzureCM").DCMLMResourceResultEtwTable
| where PreciseTimeStamp >= datetime({BeginTime}) and PreciseTimeStamp <= datetime({EndTime})
| where ResourceId == "{NodeId}"
| project PreciseTimeStamp, ResourceId, ResultType, ActivityName, FaultCode, FaultReason, DeviceType
```

---

## Service Healing

### ServiceHealingTriggerEtwTable — SH confirmation & details

```kusto
cluster("AzureCM").database("AzureCM").ServiceHealingTriggerEtwTable
| where NodeId == "{NodeId}"
| where TenantName == "{TenantName}"
| where PreciseTimeStamp >= datetime({BeginTime}) and PreciseTimeStamp < datetime({EndTime})
```

### AzSMTenantEvents — Alternate tenant event view

```kusto
cluster("AzureCM").database("AzureCM").AzSMTenantEvents
| where PreciseTimeStamp > datetime({BeginTime}) and PreciseTimeStamp < datetime({EndTime})
| where tenantName =~ "{TenantName}"
| project PreciseTimeStamp, Tenant, message
```

---

## Live Migration

### LiveMigrationContainerDetailsEventLog — Identify LM session ID

```kusto
cluster("AzureCM").database("AzureCM").LiveMigrationContainerDetailsEventLog
| where destinationContainerId == "{ContainerId}" or sourceContainerId == "{ContainerId}"
| where PreciseTimeStamp > datetime({BeginTime}) and PreciseTimeStamp < datetime({EndTime})
| project triggerType, migrationConstraint, sessionId
```

### LiveMigrationSessionCreatedLog — LM session creation

```kusto
cluster("AzureCM").database("AzureCM").LiveMigrationSessionCreatedLog
| where sourceContainerId == "{ContainerId}"
| where sessionId == "{LMSessionId}"
| project TIMESTAMP, message, sourceContainerId, containerState
```

### LiveMigrationSessionCompleteLog — LM completion

```kusto
cluster("AzureCM").database("AzureCM").LiveMigrationSessionCompleteLog
| where destinationContainerId == "{ContainerId}" or sourceContainerId == "{ContainerId}"
| where sessionId == "{LMSessionId}"
```

### LiveMigrationSessionStatusEventLog — LM status (errors)

```kusto
cluster("AzureCM").database("AzureCM").LiveMigrationSessionStatusEventLog
| where sessionId == "{LMSessionId}"
| where ['type'] == "Error"
| project ['state'], message
```

### LiveMigrationStateMachineTracesLog — Detailed LM tracing

```kusto
cluster("AzureCM").database("AzureCM").LiveMigrationStateMachineTracesLog
| where sessionId == "{LMSessionId}"
```

### LiveMigrationSessionCriticalLog — Critical LM errors

```kusto
cluster("AzureCM").database("AzureCM").LiveMigrationSessionCriticalLog
| where sessionId == "{LMSessionId}"
| project exceptionType, exception, lmContext
```
