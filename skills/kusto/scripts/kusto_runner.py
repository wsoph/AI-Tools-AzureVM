#!/usr/bin/env python3
"""
General-purpose Kusto (KQL) query runner.

Usage:
    python kusto_runner.py --cluster azurecm.kusto.windows.net --database AzureCM --query "LogContainerSnapshot | take 5"
    python kusto_runner.py --cluster disks.kusto.windows.net --database Disks --query ".show tables" --format json
    python kusto_runner.py --cluster azurecm.kusto.windows.net --database AzureCM --query-file my_query.kql --format csv
"""
import sys
import io
import argparse
import json
import csv as csv_mod

# Fix UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
from azure.identity import AzureCliCredential

MICROSOFT_TENANT_ID = "72f988bf-86f1-41af-91ab-2d7cd011db47"


def create_client(cluster_uri: str, tenant_id: str) -> KustoClient:
    """Create an authenticated KustoClient."""
    if not cluster_uri.startswith("https://"):
        cluster_uri = f"https://{cluster_uri}"
    cred = AzureCliCredential(tenant_id=tenant_id)
    kcsb = KustoConnectionStringBuilder.with_azure_token_credential(
        cluster_uri, credential=cred
    )
    return KustoClient(kcsb)


def execute_query(client: KustoClient, database: str, query: str):
    """Execute a KQL query and return (columns, rows)."""
    query_stripped = query.strip()
    # Management commands start with '.'
    if query_stripped.startswith("."):
        response = client.execute_mgmt(database, query_stripped)
    else:
        response = client.execute(database, query_stripped)

    columns = [c.column_name for c in response.primary_results[0].columns]
    rows = []
    for row in response.primary_results[0]:
        rows.append({col: row[col] for col in columns})
    return columns, rows


def format_table(columns: list, rows: list, max_col_width: int = 60) -> str:
    """Format results as a readable text table."""
    if not rows:
        return "(no results)"

    # Calculate column widths
    col_widths = {}
    for col in columns:
        col_widths[col] = min(
            max(len(col), max(len(str(row.get(col, ""))[:max_col_width]) for row in rows)),
            max_col_width,
        )

    # Header
    header = " | ".join(col.ljust(col_widths[col]) for col in columns)
    separator = "-+-".join("-" * col_widths[col] for col in columns)
    lines = [header, separator]

    # Rows
    for row in rows:
        line = " | ".join(
            str(row.get(col, ""))[:max_col_width].ljust(col_widths[col]) for col in columns
        )
        lines.append(line)

    lines.append(f"\n({len(rows)} row(s) returned)")
    return "\n".join(lines)


def format_kv(columns: list, rows: list) -> str:
    """Format results as key-value pairs (one record per block), skipping empty values."""
    if not rows:
        return "(no results)"

    blocks = []
    for i, row in enumerate(rows, 1):
        lines = [f"--- Record {i} ---"]
        for col in columns:
            val = row.get(col)
            if val is not None and str(val).strip() and str(val) not in ("0", "False", ""):
                lines.append(f"  {col}: {val}")
        blocks.append("\n".join(lines))

    blocks.append(f"\n({len(rows)} row(s) returned)")
    return "\n".join(blocks)


def format_json_output(columns: list, rows: list) -> str:
    """Format results as JSON."""
    return json.dumps(rows, indent=2, default=str)


def format_csv_output(columns: list, rows: list) -> str:
    """Format results as CSV."""
    output = io.StringIO()
    writer = csv_mod.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: str(v) for k, v in row.items()})
    return output.getvalue()


def run_query(
    cluster: str,
    database: str,
    query: str,
    tenant: str = MICROSOFT_TENANT_ID,
    output_format: str = "table",
    print_query: bool = True,
) -> list:
    """
    High-level function: connect, execute, format, print.
    Returns the list of row dicts for programmatic use.
    """
    client = create_client(cluster, tenant)

    if print_query:
        print(f"\n{'=' * 80}")
        print(f"Cluster:  {cluster}")
        print(f"Database: {database}")
        print(f"Query:")
        for line in query.strip().split("\n"):
            print(f"  {line}")
        print("=" * 80)

    try:
        columns, rows = execute_query(client, database, query)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return []

    if output_format == "json":
        print(format_json_output(columns, rows))
    elif output_format == "csv":
        print(format_csv_output(columns, rows))
    elif output_format == "kv":
        print(format_kv(columns, rows))
    else:
        print(format_table(columns, rows))

    return rows


def main():
    parser = argparse.ArgumentParser(
        description="Execute a KQL query against an Azure Data Explorer (Kusto) cluster."
    )
    parser.add_argument(
        "--cluster",
        required=True,
        help="Kusto cluster hostname (e.g., azurecm.kusto.windows.net)",
    )
    parser.add_argument("--database", required=True, help="Database name")
    parser.add_argument("--query", default=None, help="KQL query string")
    parser.add_argument("--query-file", default=None, help="Path to a .kql file")
    parser.add_argument(
        "--tenant",
        default=MICROSOFT_TENANT_ID,
        help=f"Azure AD tenant ID (default: Microsoft Corp {MICROSOFT_TENANT_ID})",
    )
    parser.add_argument(
        "--format",
        choices=["table", "json", "csv", "kv"],
        default="table",
        help="Output format (default: table). 'kv' = key-value pairs skipping empty fields.",
    )
    args = parser.parse_args()

    if not args.query and not args.query_file:
        parser.error("Must specify either --query or --query-file")

    if args.query_file:
        with open(args.query_file, "r", encoding="utf-8") as f:
            query = f.read()
    else:
        query = args.query

    run_query(
        cluster=args.cluster,
        database=args.database,
        query=query,
        tenant=args.tenant,
        output_format=args.format,
    )


if __name__ == "__main__":
    main()
