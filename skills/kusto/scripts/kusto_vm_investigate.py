#!/usr/bin/env python3
"""
VM Investigation Script - Automated Kusto query sequence for Azure VM troubleshooting.

Executes the full VM investigation workflow:
  1. LogContainerSnapshot           - Find VM identity (containerId, nodeId, tenantName)
  2. LogContainerHealthSnapshot     - Check VM health state changes
  3. TMMgmtRoleInstanceDowntimeEventEtwTable - Downtime events
  4. TMMgmtNodeFaultEtwTable        - Node-level faults
  5. FaultHandlingContainerFaultEventEtwTable - Container-level faults
  6. FaultHandlingRecoveryEventEtwTable       - Recovery actions
  7. KronoxVmOperationEvent         - Platform VM operations (reboot/restart/redeploy)
  8. DCMLMResourceUnexpectedRebootEtwTable    - Unexpected reboots
  9. ServiceHealingTriggerEtwTable   - Service healing triggers

Usage:
    python kusto_vm_investigate.py \\
        --subscription-id 483ab1e0-a746-4f34-8276-53e640d6ab09 \\
        --vm-name centralindia-1743575807630-WzXR0tLF-1 \\
        --start-date 2026-02-20 --end-date 2026-02-24
"""
import sys
import io
import argparse
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
from azure.identity import AzureCliCredential

MICROSOFT_TENANT_ID = "72f988bf-86f1-41af-91ab-2d7cd011db47"
AZURECM_CLUSTER = "https://azurecm.kusto.windows.net"
AZURECM_DB = "AzureCM"


def create_client(cluster_uri: str, tenant_id: str) -> KustoClient:
    cred = AzureCliCredential(tenant_id=tenant_id)
    kcsb = KustoConnectionStringBuilder.with_azure_token_credential(cluster_uri, credential=cred)
    return KustoClient(kcsb)


def execute_and_print(client: KustoClient, database: str, query: str, step_name: str, max_rows: int = 50):
    """Execute a query, print the KQL first, then print results. Returns list of row dicts."""
    print(f"\n{'=' * 100}")
    print(f"STEP: {step_name}")
    print(f"{'=' * 100}")
    print("KQL:")
    for line in query.strip().split("\n"):
        print(f"  {line}")
    print("-" * 100)

    try:
        query_stripped = query.strip()
        if query_stripped.startswith("."):
            response = client.execute_mgmt(database, query_stripped)
        else:
            response = client.execute(database, query_stripped)

        columns = [c.column_name for c in response.primary_results[0].columns]
        rows = []
        count = 0
        for row in response.primary_results[0]:
            count += 1
            row_dict = {}
            for col in columns:
                row_dict[col] = row[col]
                val = row[col]
                if val is not None and str(val).strip() and str(val) not in ("0", "False", ""):
                    print(f"  {col}: {val}")
            print("---")
            rows.append(row_dict)
            if count >= max_rows:
                print(f"  (truncated at {max_rows} rows)")
                break

        print(f"Total rows returned: {count}")
        return rows

    except Exception as e:
        print(f"ERROR: {e}")
        return []


def main():
    parser = argparse.ArgumentParser(description="Automated VM investigation via Kusto queries.")
    parser.add_argument("--subscription-id", required=True, help="Azure subscription ID")
    parser.add_argument("--vm-name", required=True, help="VM name (or partial name for has-match)")
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--tenant", default=MICROSOFT_TENANT_ID, help="Azure AD tenant ID")
    parser.add_argument("--max-rows", type=int, default=50, help="Max rows per query (default: 50)")
    args = parser.parse_args()

    # Validate dates
    try:
        datetime.strptime(args.start_date, "%Y-%m-%d")
        datetime.strptime(args.end_date, "%Y-%m-%d")
    except ValueError:
        print("ERROR: Dates must be in YYYY-MM-DD format", file=sys.stderr)
        sys.exit(1)

    sub_id = args.subscription_id
    vm_name = args.vm_name
    start = args.start_date
    end = args.end_date

    print(f"VM Investigation Started")
    print(f"  Subscription: {sub_id}")
    print(f"  VM Name:      {vm_name}")
    print(f"  Time Range:   {start} to {end}")
    print(f"  Cluster:      {AZURECM_CLUSTER}")
    print(f"  Database:     {AZURECM_DB}")

    client = create_client(AZURECM_CLUSTER, args.tenant)

    # ====================================================================
    # Step 1: LogContainerSnapshot - Find VM identity
    # ====================================================================
    q1 = f"""LogContainerSnapshot
| where TIMESTAMP between(datetime({start}) .. datetime({end}))
| where subscriptionId == "{sub_id}"
    or roleInstanceName has "{vm_name}"
| project PreciseTimeStamp, containerId, containerType, nodeId, tenantName,
          subscriptionId, roleInstanceName, virtualMachineUniqueId,
          CloudName, Region, DataCenterName, AvailabilityZone, SourceNodeId, creationTime
| order by PreciseTimeStamp desc
| limit 10"""

    rows1 = execute_and_print(client, AZURECM_DB, q1, "1. LogContainerSnapshot (VM Identity)", args.max_rows)

    # Extract identity info from first result for subsequent queries
    container_id = None
    node_id = None
    tenant_name = None
    vm_unique_id = None

    if rows1:
        first = rows1[0]
        container_id = first.get("containerId")
        node_id = first.get("nodeId")
        tenant_name = first.get("tenantName")
        vm_unique_id = first.get("virtualMachineUniqueId")
        print(f"\n  >> Extracted identifiers for subsequent queries:")
        print(f"     containerId: {container_id}")
        print(f"     nodeId:      {node_id}")
        print(f"     tenantName:  {tenant_name}")
        print(f"     vmUniqueId:  {vm_unique_id}")
    else:
        print("\n  >> WARNING: No results from LogContainerSnapshot. Subsequent queries may return empty results.")
        print("     Will use subscription ID and VM name as fallback filters.")

    # Build filter clause for subsequent queries
    def build_filter_by_tenant_or_vm():
        parts = []
        if tenant_name:
            parts.append(f'tenantName == "{tenant_name}"')
        parts.append(f'roleInstanceName has "{vm_name}"')
        return " or ".join(parts)

    def build_filter_by_container_or_node():
        parts = []
        if container_id:
            parts.append(f'ContainerId == "{container_id}"')
        if node_id:
            parts.append(f'NodeId has "{node_id}"')
        parts.append(f'RoleInstanceName has "{vm_name}"')
        return " or ".join(parts)

    def build_filter_node():
        if node_id:
            return f'NodeId has "{node_id}" or BladeID has "{node_id}"'
        return f'RoleInstanceName has "{vm_name}"'

    # ====================================================================
    # Step 2: LogContainerHealthSnapshot
    # ====================================================================
    filter_tenant = build_filter_by_tenant_or_vm()
    q2 = f"""LogContainerHealthSnapshot
| where TIMESTAMP between(datetime({start}) .. datetime({end}))
| where {filter_tenant}
| project PreciseTimeStamp, containerState, actualOperationalState,
          containerLifecycleState, containerOsState, vmExpectedHealthState,
          containerId, nodeId, tenantName, roleInstanceName,
          faultInfo, containerIsolationState, isContainerConnected, hibernateStatus
| order by PreciseTimeStamp desc
| limit 20"""

    execute_and_print(client, AZURECM_DB, q2, "2. LogContainerHealthSnapshot (VM Health)", args.max_rows)

    # ====================================================================
    # Step 3: TMMgmtRoleInstanceDowntimeEventEtwTable
    # ====================================================================
    filter_container = build_filter_by_container_or_node()
    q3 = f"""TMMgmtRoleInstanceDowntimeEventEtwTable
| where TIMESTAMP between(datetime({start}) .. datetime({end}))
| where {filter_container}
| project PreciseTimeStamp, ResourceType, ResourceId, TenantName, RoleInstanceName,
          ContainerId, NodeId, ActivityType, ActivityDetail, VMContext, LastEvents
| order by PreciseTimeStamp asc"""

    execute_and_print(client, AZURECM_DB, q3, "3. Downtime Events", args.max_rows)

    # ====================================================================
    # Step 4: TMMgmtNodeFaultEtwTable
    # ====================================================================
    filter_node = build_filter_node()
    q4 = f"""TMMgmtNodeFaultEtwTable
| where TIMESTAMP between(datetime({start}) .. datetime({end}))
| where {filter_node}
| project PreciseTimeStamp, FaultCode, Reason, Time, Details,
          FaultInfoJsonString, CorrelationGuid, BladeID, NodeId
| order by PreciseTimeStamp asc"""

    execute_and_print(client, AZURECM_DB, q4, "4. Node Fault Events", args.max_rows)

    # ====================================================================
    # Step 5: FaultHandlingContainerFaultEventEtwTable
    # ====================================================================
    filter_cf = []
    if container_id:
        filter_cf.append(f'ContainerId == "{container_id}"')
    if node_id:
        filter_cf.append(f'NodeId has "{node_id}"')
    if not filter_cf:
        filter_cf.append(f'RoleInstanceName has "{vm_name}"')
    filter_cf_str = " or ".join(filter_cf)

    q5 = f"""FaultHandlingContainerFaultEventEtwTable
| where TIMESTAMP between(datetime({start}) .. datetime({end}))
| where {filter_cf_str}
| project PreciseTimeStamp, NodeId, ContainerId, FaultTime, FaultCode,
          FaultType, FabricOperation, NodeState, FaultScope, Reason, Details
| order by PreciseTimeStamp asc"""

    execute_and_print(client, AZURECM_DB, q5, "5. Container Fault Events", args.max_rows)

    # ====================================================================
    # Step 6: FaultHandlingRecoveryEventEtwTable + ContainerRecovery
    # ====================================================================
    if node_id:
        q6a = f"""FaultHandlingRecoveryEventEtwTable
| where TIMESTAMP between(datetime({start}) .. datetime({end}))
| where NodeId has "{node_id}"
| project PreciseTimeStamp, NodeId, FaultDetectionTime, FaultRecoveryDurationInMinutes,
          RecoveryResult, FaultSignature, RecoveryAction, ImpactedTenants
| order by PreciseTimeStamp asc"""

        execute_and_print(client, AZURECM_DB, q6a, "6a. Node Recovery Events", args.max_rows)

    filter_cr = []
    if container_id:
        filter_cr.append(f'ContainerId == "{container_id}"')
    if node_id:
        filter_cr.append(f'NodeId has "{node_id}"')
    if not filter_cr:
        filter_cr.append(f'RoleInstanceName has "{vm_name}"')
    filter_cr_str = " or ".join(filter_cr)

    q6b = f"""FaultHandlingContainerRecoveryEventEtwTable
| where TIMESTAMP between(datetime({start}) .. datetime({end}))
| where {filter_cr_str}
| project PreciseTimeStamp, NodeId, ContainerId, AttemptResult, FaultDetails,
          RecoveryAction, FaultTime, RecoveryTime, ImpactedContainers
| order by PreciseTimeStamp asc"""

    execute_and_print(client, AZURECM_DB, q6b, "6b. Container Recovery Events", args.max_rows)

    # ====================================================================
    # Step 7: KronoxVmOperationEvent
    # ====================================================================
    filter_kronox = f'SubscriptionId =~ "{sub_id}"'
    if vm_unique_id:
        filter_kronox += f' or VmId == "{vm_unique_id}"'

    q7 = f"""KronoxVmOperationEvent
| where TIMESTAMP between(datetime({start}) .. datetime({end}))
| where {filter_kronox}
| project PreciseTimeStamp, OperationType, OperationId, CurrentOperationStatus,
          NewOperationStatus, VmId, SubscriptionId, ActivationTime, CompletionTime,
          DeadlineUtc, ErrorCode, ErrorDetails, JobId
| order by PreciseTimeStamp asc"""

    execute_and_print(client, AZURECM_DB, q7, "7. VM Operations (Kronox)", args.max_rows)

    # ====================================================================
    # Step 8: DCMLMResourceUnexpectedRebootEtwTable
    # ====================================================================
    if node_id:
        q8 = f"""DCMLMResourceUnexpectedRebootEtwTable
| where TIMESTAMP between(datetime({start}) .. datetime({end}))
| where ResourceId has "{node_id}" or SourceNodeId has "{node_id}"
| project PreciseTimeStamp, ResourceId, PowerCycleTime, PxeRequestTime,
          TimeBetweenPowerAndPxe, CloudName, Region, DataCenterName
| order by PreciseTimeStamp asc"""

        execute_and_print(client, AZURECM_DB, q8, "8. Unexpected Reboots", args.max_rows)
    else:
        print(f"\n{'=' * 100}")
        print("STEP: 8. Unexpected Reboots")
        print("SKIPPED: No nodeId available (requires LogContainerSnapshot result)")
        print("=" * 100)

    # ====================================================================
    # Step 9: ServiceHealingTriggerEtwTable
    # ====================================================================
    filter_sh = []
    if node_id:
        filter_sh.append(f'NodeId has "{node_id}"')
    if tenant_name:
        filter_sh.append(f'TenantName has "{tenant_name}"')
    filter_sh.append(f'RoleInstanceName has "{vm_name}"')
    filter_sh_str = " or ".join(filter_sh)

    q9 = f"""ServiceHealingTriggerEtwTable
| where TIMESTAMP between(datetime({start}) .. datetime({end}))
| where {filter_sh_str}
| project PreciseTimeStamp, TriggerId, TriggerType, TriggerObjectId,
          FaultCode, FaultReason, FaultInfoFabricOperation, TenantName,
          RoleInstanceName, AffectedUpdateDomain, NodeId
| order by PreciseTimeStamp asc"""

    execute_and_print(client, AZURECM_DB, q9, "9. Service Healing Triggers", args.max_rows)

    # ====================================================================
    # Summary
    # ====================================================================
    print(f"\n{'=' * 100}")
    print("INVESTIGATION COMPLETE")
    print(f"{'=' * 100}")
    print(f"  Subscription: {sub_id}")
    print(f"  VM Name:      {vm_name}")
    print(f"  Time Range:   {start} to {end}")
    if container_id:
        print(f"  Container ID: {container_id}")
    if node_id:
        print(f"  Node ID:      {node_id}")
    if tenant_name:
        print(f"  Tenant Name:  {tenant_name}")
    print()


if __name__ == "__main__":
    main()
