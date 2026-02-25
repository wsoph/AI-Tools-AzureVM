#!/usr/bin/env python3
"""
Get and open the EEE HostNode page link for a VM at a given issue time.

Usage:
    python get_eee_link.py --subscription <sub_id> --vm-name <vm_name> --issue-time "2026-02-21 11:21:19"
    python get_eee_link.py --resource-id "/subscriptions/.../virtualMachines/<vm_name>" --issue-time "2026-02-21 11:21:19"

Optional:
    --query-start "2026-02-19 00:00:00"   Custom query start time (default: 3 days before issue time)
    --query-end   "2026-02-25 23:59:59"   Custom query end time   (default: now)
    --no-browser                           Print URL(s) only, do not open browser

Authentication:
    Requires az CLI logged in to the Microsoft Corp tenant (72f988bf-86f1-41af-91ab-2d7cd011db47).
    Run: az login --tenant 72f988bf-86f1-41af-91ab-2d7cd011db47
"""

import argparse
import json
import subprocess
import sys
import urllib.parse
import webbrowser
from datetime import datetime, timezone, timedelta

AZ_CMD = r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
KUSTO_CLUSTER = "https://azurecm.kusto.windows.net"
KUSTO_DATABASE = "AzureCM"
MSFT_TENANT = "72f988bf-86f1-41af-91ab-2d7cd011db47"


def get_token():
    """Get an access token for the AzureCM Kusto cluster via az CLI."""
    result = subprocess.run(
        [AZ_CMD, "account", "get-access-token",
         "--resource", KUSTO_CLUSTER,
         "--tenant", MSFT_TENANT,
         "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, shell=True
    )
    if result.returncode != 0 or not result.stdout.strip():
        print("ERROR: Failed to get access token.", file=sys.stderr)
        print("Make sure you are logged in:", file=sys.stderr)
        print(f"  az login --tenant {MSFT_TENANT}", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def run_kusto_query(token, subscription_id, vm_name, query_start, query_end):
    """Run LogContainerSnapshot query and return rows as list of dicts."""
    from azure.kusto.data import KustoClient, KustoConnectionStringBuilder

    kcsb = KustoConnectionStringBuilder.with_token_provider(
        KUSTO_CLUSTER, lambda: token
    )
    client = KustoClient(kcsb)

    query = f"""LogContainerSnapshot
| where PreciseTimeStamp >= datetime({query_start}) and PreciseTimeStamp <= datetime({query_end})
| where subscriptionId == "{subscription_id}"
| where roleInstanceName contains "{vm_name}"
| summarize STARTTIME=min(TIMESTAMP), ENDTIME=max(TIMESTAMP)
    by nodeId, containerId, roleInstanceName, tenantName, Tenant,
       containerType, availabilitySetName, virtualMachineUniqueId, tenantOwners, AvailabilityZone
| project STARTTIME, ENDTIME, nodeId, containerId, roleInstanceName, tenantName, Tenant,
          containerType, availabilitySetName, virtualMachineUniqueId, tenantOwners, AvailabilityZone"""

    print(f"Running KQL query on {KUSTO_CLUSTER}/{KUSTO_DATABASE}...")
    response = client.execute(KUSTO_DATABASE, query)
    rows = [row.to_dict() for row in response.primary_results[0]]
    print(f"Query returned {len(rows)} row(s).")
    return rows


def parse_time(s):
    """Parse a datetime string to a UTC-aware datetime."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s.strip(), fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unrecognized datetime format: {s!r}")


def build_eee_url(row, globalFrom, globalTo):
    """Construct the EEE HostNode URL from a KQL result row and time window."""
    def enc(v):
        return urllib.parse.quote(str(v), safe="")

    gf = globalFrom.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    gt = globalTo.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    return (
        "https://asi.azure.ms/services/EEE%20RDOS/pages/Start%20Hub"
        f"?cluster={enc(row['Tenant'])}"
        f"&containerid={enc(row['containerId'])}"
        f"&nodeid={enc(row['nodeId'])}"
        f"&roleInstanceName={enc(row['roleInstanceName'])}"
        f"&tenantname={enc(row['tenantName'])}"
        f"&vmid={enc(row['virtualMachineUniqueId'])}"
        f"&globalFrom={enc(gf)}"
        f"&globalTo={enc(gt)}"
    )


def main():
    parser = argparse.ArgumentParser(description="Generate and open EEE HostNode links for a VM.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--resource-id", help="Full VM resource ID")
    group.add_argument("--subscription", help="Azure subscription ID")
    parser.add_argument("--vm-name", help="VM name (required if --subscription is used)")
    parser.add_argument("--issue-time", required=True, help="Issue timestamp, e.g. '2026-02-21 11:21:19'")
    parser.add_argument("--query-start", help="KQL query start time (default: 3 days before issue time)")
    parser.add_argument("--query-end", help="KQL query end time (default: now)")
    parser.add_argument("--no-browser", action="store_true", help="Print URLs only, do not open browser")
    args = parser.parse_args()

    # Parse VM identity
    if args.resource_id:
        parts = args.resource_id.strip().split("/")
        try:
            sub_idx = parts.index("subscriptions") + 1
            vm_idx = parts.index("virtualMachines") + 1
            subscription_id = parts[sub_idx]
            vm_name = parts[vm_idx]
        except (ValueError, IndexError):
            print("ERROR: Could not parse subscription ID and VM name from resource ID.", file=sys.stderr)
            sys.exit(1)
    else:
        if not args.vm_name:
            print("ERROR: --vm-name is required when using --subscription.", file=sys.stderr)
            sys.exit(1)
        subscription_id = args.subscription
        vm_name = args.vm_name

    # Parse times
    issue_time = parse_time(args.issue_time)
    query_start = parse_time(args.query_start) if args.query_start else issue_time - timedelta(days=3)
    query_end = parse_time(args.query_end) if args.query_end else datetime.now(timezone.utc)

    qs = query_start.strftime("%Y-%m-%d %H:%M:%S")
    qe = query_end.strftime("%Y-%m-%d %H:%M:%S")

    print(f"Subscription: {subscription_id}")
    print(f"VM Name:      {vm_name}")
    print(f"Issue Time:   {issue_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Query Range:  {qs} to {qe}")
    print()

    # Auth + query
    token = get_token()
    rows = run_kusto_query(token, subscription_id, vm_name, qs, qe)

    if not rows:
        print("No results found. Check subscription ID, VM name, and time range.")
        sys.exit(0)

    # Match issue time
    def to_utc(dt):
        if hasattr(dt, "tzinfo") and dt.tzinfo:
            return dt.astimezone(timezone.utc)
        return dt.replace(tzinfo=timezone.utc)

    matched = [
        r for r in rows
        if to_utc(r["STARTTIME"]) <= issue_time <= to_utc(r["ENDTIME"])
    ]

    if matched:
        print(f"Issue time matched row(s): {len(matched)}")
        selected = matched
        gf = issue_time - timedelta(hours=6)
        gt = issue_time + timedelta(hours=6)
        time_windows = [(gf, gt)] * len(selected)
    else:
        print("Issue time did not match any row's STARTTIME-ENDTIME range.")
        print("Generating links for ALL rows.")
        selected = rows
        time_windows = [
            (to_utc(r["STARTTIME"]) - timedelta(hours=1),
             to_utc(r["ENDTIME"]) + timedelta(hours=1))
            for r in selected
        ]

    print()
    urls = []
    for i, (row, (gf, gt)) in enumerate(zip(selected, time_windows), 1):
        url = build_eee_url(row, gf, gt)
        urls.append(url)
        print(f"Link {i}:")
        print(f"  Node:      {row['nodeId']}")
        print(f"  Tenant:    {row['Tenant']}")
        print(f"  Container: {row['containerId']}")
        print(f"  Window:    {gf.strftime('%Y-%m-%dT%H:%M:%SZ')} → {gt.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        print(f"  URL: {url}")
        print()

    if not args.no_browser:
        for url in urls:
            webbrowser.open(url)
        print(f"Opened {len(urls)} link(s) in the browser.")


if __name__ == "__main__":
    main()
