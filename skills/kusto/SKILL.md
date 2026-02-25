---
name: kusto-query
description: >
  Azure infrastructure investigation via Kusto (KQL) queries across internal clusters
  (AzureCM, Disks RP, VMInsight, AzCore, AzureDCM, Sparkle, Hawkeye, ICM, Watson, AzPE).
  Use when the user mentions: Kusto, KQL, VM restart/reboot investigation, disk lifecycle,
  node fault, service healing, live migration, hardware failure, host update, or any query
  against Azure internal telemetry clusters. Also use when the user asks to investigate
  a VM availability issue, generate an RCA report, or run infrastructure diagnostics.
---

# Kusto Query Skill — Azure Infrastructure Investigation

## Workflow

When the user requests a Kusto-based investigation:

1. **Identify scenario** — determine which investigation type applies:
   - **VM restart/availability** → See `references/azurecm-queries.md` + `references/vmainsight-queries.md`
   - **Disk lifecycle** → See `references/disks-queries.md`
   - **Node hardware failure** → See `references/hardware-queries.md`
   - **Live Migration** → See `references/azurecm-queries.md` (Live Migration section)
   - **RDOS / HyperV / host-level** → See `references/azcore-queries.md`
   - **Maintenance / notifications** → See `references/operations-queries.md`
   - **Host bugcheck / Watson** → See `references/operations-queries.md`
   - **Ad-hoc single query** → Use `scripts/kusto_runner.py` directly

2. **List all KQL queries** — show the user every query that will be executed, so they can review or modify before running

3. **Execute** — run the appropriate script or `kusto_runner.py`:
   ```bash
   # VM investigation (9-step automated)
   python .claude/skills/kusto/scripts/kusto_vm_investigate.py \
       --subscription-id <id> --vm-name <name> --start-date YYYY-MM-DD --end-date YYYY-MM-DD

   # Disk investigation (4-step automated)
   python .claude/skills/kusto/scripts/kusto_disk_investigate.py \
       --subscription-id <id> --disk-name <name>

   # Single ad-hoc query
   python .claude/skills/kusto/scripts/kusto_runner.py \
       --cluster <host> --database <db> --query "<KQL>" --format table|json|csv|kv
   ```

4. **Summarize as RCA report** — present findings using the RCA template below

## RCA Report Template

```
## VM Availability

The Azure monitoring and diagnostics systems identified that the VM **{VMName}**
was impacted at **{StartTime}**. During this time, RDP/SSH connections or other
requests to the VM could have failed.

## Root Cause

{One-paragraph root cause based on query findings. Reference specific evidence:
fault codes, node state transitions, recovery actions, hardware errors, etc.}

## Resolution

{How service was restored — e.g., node reboot, service healing, live migration,
hardware replacement, etc. Include timestamps where available.}

## Timeline

| Time (UTC) | Event |
|------------|-------|
| {timestamp} | {event description} |
| ... | ... |

## Additional Information

{Any relevant context: whether the node was marked for repair, whether other VMs
on the same node were affected, platform improvement efforts, etc.}

## Recommended Documents

- [Auto-recovery of Virtual Machines](https://aka.ms/yourlink)
- [Configure availability of virtual machines](https://aka.ms/yourlink)
- [Maintenance and updates for virtual machines in Azure](https://aka.ms/yourlink)
```

Adapt sections as needed — omit Timeline if no events found, expand Root Cause with technical detail for internal use.

## Clusters Quick Reference

| Alias | URI | Database(s) | Purpose |
|-------|-----|-------------|---------|
| AzureCM | `azurecm.kusto.windows.net` | AzureCM | Container/node lifecycle, faults, recovery, SH, LM |
| Azcsupfollower | `Azcsupfollower.kusto.windows.net` | AzureCM | Follower cluster (same data) |
| Disks | `disks.kusto.windows.net` | Disks | Managed disk lifecycle, DiskManagerApiQoS |
| VMInsight | `vmainsight.kusto.windows.net` | vmadb, Air | VMA RCA, host CPU, Windows events, Air events |
| AzCore | `azcore.centralus.kusto.windows.net` | Fa | RDOS: HyperV, VM health, node service, OS logs |
| AzureDCM | `Azuredcm` | AzureDCMDb | Hardware inventory, repair history |
| Sparkle | `sparkle.eastus` | defaultdb | WHEA/SEL hardware errors |
| Hawkeye | `hawkeyedataexplorer.westus2.kusto.windows.net` | HawkeyeLogs | Automated unhealthy node RCA |
| ICM | `icmcluster` | ACM.Publisher, ACM.Backend | Customer notifications |
| Watson | `Azurewatsoncustomer` | AzureWatsonCustomer | Host bugcheck analysis |
| AzPE | `azpe.kusto.windows.net` | azpe | Host update workflow orchestration |
| APlat | `aplat.westcentralus.kusto.windows.net` | APlat | Anvil/Tardigrade service healing |
| Gandalf | `Gandalf` | gandalf | Unallocatable node detection |

All clusters require **Microsoft Corp tenant** (`72f988bf-86f1-41af-91ab-2d7cd011db47`).

## Variable Convention

All query templates use these standardized placeholders:
- `{NodeId}`, `{ContainerId}`, `{VMName}`, `{VMId}`, `{TenantName}`, `{Cluster}`
- `{SubscriptionId}`, `{ResourceGroupName}`, `{StorageAccountName}`
- `{BeginTime}` / `{EndTime}` or `{StartTime}` / `{EndTime}` — format: `2017-11-01 23:00:00Z`
- `{LMSessionId}` — for Live Migration queries

Extract Resource ID components:
```kusto
let MyResourceID = "{Resource_id}";
let SubID = split(MyResourceID, "/")[2];
let ResourceGrp = split(MyResourceID, "/")[4];
let VMName = split(MyResourceID, "/")[-1];
```

## Investigation Flow: VM Restart RCA

1. `LogContainerSnapshot` → get containerId, nodeId, tenantName
2. `LogContainerHealthSnapshot` → VM health state changes
3. `TMMgmtNodeStateChangedEtwTable` → node reboot confirmation
4. `TMMgmtNodeEventsEtwTable` → dirty shutdown, bugcheck, operations
5. `TMMgmtRoleInstanceDowntimeEventEtwTable` → downtime events
6. `TMMgmtTenantEventsEtwTable` → fabric-triggered operations, OOM, LM
7. `TMMgmtNodeFaultEtwTable` → node-level faults
8. `FaultHandlingContainerFaultEventEtwTable` → container faults
9. `FaultHandlingRecoveryEventEtwTable` → recovery actions (PowerCycle, etc.)
10. `ServiceHealingTriggerEtwTable` → service healing triggers
11. `KronoxVmOperationEvent` → platform VM operations
12. `DCMLMResourceUnexpectedRebootEtwTable` → unexpected reboots
13. `VMA` (vmadb) → RCA category and support article link
14. `VMALENS` (vmadb) → 30-day availability impact history

For deeper investigation, continue with:
- Hardware: `references/hardware-queries.md` (AzureDCM, Sparkle WHEA/SEL)
- HyperV/RDOS: `references/azcore-queries.md`
- Hawkeye automated RCA: `references/operations-queries.md`
- Host updates: `references/vmainsight-queries.md`
- Watson bugchecks: `references/operations-queries.md`
