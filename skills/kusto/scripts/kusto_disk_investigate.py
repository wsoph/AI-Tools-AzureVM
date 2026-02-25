#!/usr/bin/env python3
"""
Disk Investigation Script - Automated Kusto query sequence for Azure Managed Disk troubleshooting.

Executes the full disk investigation workflow:
  1. DiskRPResourceLifecycleEvent                    - Disk lifecycle (create/attach/detach/delete)
  2. DiskManagerApiQoSEvent                          - Backend API operations & existence check
  3. Disk (snapshot table)                           - Current disk state
  4. AssociatedXStoreEntityResourceLifecycleEvent    - Storage layer (XStore) entity lifecycle

Usage:
    python kusto_disk_investigate.py \\
        --subscription-id 0e9367ff-1d01-483d-ba59-1a5d51c00128 \\
        --disk-name DATADisk-seedkrypton-dn20250520016-1-001-001
"""
import sys
import io
import argparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
from azure.identity import AzureCliCredential

MICROSOFT_TENANT_ID = "72f988bf-86f1-41af-91ab-2d7cd011db47"
DISKS_CLUSTER = "https://disks.kusto.windows.net"
DISKS_DB = "Disks"


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
    parser = argparse.ArgumentParser(description="Automated disk investigation via Kusto queries.")
    parser.add_argument("--subscription-id", required=True, help="Azure subscription ID")
    parser.add_argument("--disk-name", required=True, help="Managed disk resource name")
    parser.add_argument("--tenant", default=MICROSOFT_TENANT_ID, help="Azure AD tenant ID")
    parser.add_argument("--max-rows", type=int, default=50, help="Max rows per query (default: 50)")
    parser.add_argument("--lookback-days", type=int, default=90, help="Lookback period in days (default: 90)")
    args = parser.parse_args()

    sub_id = args.subscription_id
    disk_name = args.disk_name
    lookback = args.lookback_days

    print(f"Disk Investigation Started")
    print(f"  Subscription: {sub_id}")
    print(f"  Disk Name:    {disk_name}")
    print(f"  Lookback:     {lookback} days")
    print(f"  Cluster:      {DISKS_CLUSTER}")
    print(f"  Database:     {DISKS_DB}")

    client = create_client(DISKS_CLUSTER, args.tenant)

    # ====================================================================
    # Step 1: DiskRPResourceLifecycleEvent - Full lifecycle
    # ====================================================================
    q1 = f"""DiskRPResourceLifecycleEvent
| where subscriptionId == "{sub_id}"
| where resourceName == "{disk_name}"
| where PreciseTimeStamp >= ago({lookback}d)
| project PreciseTimeStamp, resourceName, subscriptionId, resourceGroupName,
          diskType, diskEvent, stage, state, storageAccountType,
          diskSizeBytes, diskOwner, id, crpDiskId, blobUrl, storageAccountName
| order by PreciseTimeStamp asc"""

    rows1 = execute_and_print(client, DISKS_DB, q1, "1. DiskRPResourceLifecycleEvent (Lifecycle History)", args.max_rows)

    # Extract disk internal ID for XStore query
    disk_rp_id = None
    resource_group = None
    if rows1:
        # Use the last row for the most recent state
        last = rows1[-1]
        disk_rp_id = last.get("id")
        resource_group = last.get("resourceGroupName")
        print(f"\n  >> Extracted identifiers for subsequent queries:")
        print(f"     Disk RP internal ID: {disk_rp_id}")
        print(f"     Resource Group:      {resource_group}")
    else:
        print("\n  >> WARNING: No lifecycle events found. The disk may not exist in this subscription,")
        print("     or may be older than the lookback period. Try increasing --lookback-days.")

    # ====================================================================
    # Step 2: DiskManagerApiQoSEvent - API operations & existence check
    # ====================================================================
    q2 = f"""DiskManagerApiQoSEvent
| where resourceName == "{disk_name}"
| where subscriptionId == "{sub_id}"
| project PreciseTimeStamp, operationName, httpStatusCode, resourceName,
          clientApplicationId, userAgent, region
| order by PreciseTimeStamp desc
| limit 20"""

    rows2 = execute_and_print(client, DISKS_DB, q2, "2. DiskManagerApiQoSEvent (API Operations & Existence Check)", args.max_rows)

    if rows2:
        # Check latest status
        latest = rows2[0]
        status = latest.get("httpStatusCode")
        client_app = latest.get("clientApplicationId", "")
        if status == 200:
            print(f"\n  >> Latest API status: 200 OK - Disk EXISTS")
        elif status == 404:
            print(f"\n  >> Latest API status: 404 - Disk has been DELETED")
        else:
            print(f"\n  >> Latest API status: {status}")
        if "Azure Resource Graph" in str(client_app):
            print(f"     (via Azure Resource Graph periodic crawl)")

    # ====================================================================
    # Step 3: Disk snapshot table - Current state
    # ====================================================================
    q3 = f"""Disk
| where DisksName has "{disk_name}"
| order by PreciseTimeStamp desc
| limit 5
| project PreciseTimeStamp, DisksId, DisksName, DiskResourceType,
          OwnershipState, AccountType, ResourceGroup, DiskSizeBytes,
          BlobUrl, StorageAccountName, CrpDiskId"""

    execute_and_print(client, DISKS_DB, q3, "3. Disk Snapshot Table (Current State)", args.max_rows)

    # ====================================================================
    # Step 4: AssociatedXStoreEntityResourceLifecycleEvent - Storage layer
    # ====================================================================
    filter_xstore = []
    if disk_rp_id:
        filter_xstore.append(f'parentDiskId == "{disk_rp_id}"')
    filter_xstore.append(f'entityName has "{disk_name}"')
    filter_xstore_str = " or ".join(filter_xstore)

    q4 = f"""AssociatedXStoreEntityResourceLifecycleEvent
| where {filter_xstore_str}
| project PreciseTimeStamp, id, parentDiskId, entityName, entityType,
          lifecycleEventType, stage, entityUri, storageAccountName,
          storageAccountType, entitySizeBytes, isHydrated, subscriptionId
| order by PreciseTimeStamp asc"""

    execute_and_print(client, DISKS_DB, q4, "4. XStore Entity Lifecycle (Storage Layer)", args.max_rows)

    # ====================================================================
    # Summary
    # ====================================================================
    print(f"\n{'=' * 100}")
    print("INVESTIGATION COMPLETE")
    print(f"{'=' * 100}")
    print(f"  Subscription:  {sub_id}")
    print(f"  Disk Name:     {disk_name}")
    if resource_group:
        print(f"  Resource Group: {resource_group}")
    if disk_rp_id:
        print(f"  Disk RP ID:    {disk_rp_id}")
    print()


if __name__ == "__main__":
    main()
