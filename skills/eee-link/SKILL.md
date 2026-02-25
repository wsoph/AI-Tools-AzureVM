---
name: eee-link
description: Generate and open EEE HostNode page links for Azure VM investigation. Use when the user asks to get an EEE link, open EEE HostNode page, investigate a VM on EEE, or generate an EEE RDOS link. Requires a VM resource ID (or subscription ID + VM name) and an issue time.
---

# EEE HostNode Link Generator

Generate EEE RDOS HostNode page URLs from VM node history and open them in the browser.

## Workflow

1. Collect inputs from the user
2. Run KQL query to get VM node history
3. Match issue time to the correct node placement
4. Build EEE HostNode URL(s) and open in browser

## Step 1: Collect Inputs

Required:
- **VM identity** — either a full resource ID (`/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Compute/virtualMachines/{vmName}`) or subscription ID + VM name separately
- **Issue time** — timestamp of the issue (e.g., `2026-02-21 11:21:19`)

If the user does not provide an issue time, ask for it before proceeding.

Optional:
- **Query time range** — custom start/end datetime. Default: 3 days before issue time → now.

## Step 2: Run the script

Run the bundled script — it handles authentication, KQL query, time matching, URL building, and browser opening all in one:

```bash
PYTHONIOENCODING=utf-8 python <skill-base-dir>/scripts/get_eee_link.py \
  --resource-id "<full_resource_id>" \
  --issue-time "2026-02-21 11:21:19"
```

> **Windows note:** Always prefix with `PYTHONIOENCODING=utf-8` to avoid encoding errors in the terminal.

Or with subscription ID + VM name separately:

```bash
PYTHONIOENCODING=utf-8 python <skill-base-dir>/scripts/get_eee_link.py \
  --subscription "<subscription_id>" \
  --vm-name "<vm_name>" \
  --issue-time "2026-02-21 11:21:19"
```

With a custom query time range:

```bash
PYTHONIOENCODING=utf-8 python <skill-base-dir>/scripts/get_eee_link.py \
  --resource-id "<full_resource_id>" \
  --issue-time "2026-02-21 11:21:19" \
  --query-start "2026-02-19 00:00:00" \
  --query-end "2026-02-25 23:59:59"
```

## Authentication

The script authenticates to `azurecm.kusto.windows.net` using the az CLI token for the **Microsoft Corp tenant** (`72f988bf-86f1-41af-91ab-2d7cd011db47`).

**If you get a 401 error**, the az CLI token may not have access. Check the error output — the script prints a fix. The usual fix is to ensure `sophiewang@microsoft.com` is logged in to the correct tenant. You can verify with:

```bash
az account list --query "[?tenantId=='72f988bf-86f1-41af-91ab-2d7cd011db47'].{name:name,user:user.name}" -o table
```

If not logged in to that tenant, log in with device code (no browser pop-up):

```bash
az login --tenant 72f988bf-86f1-41af-91ab-2d7cd011db47 --use-device-code
```

## Script Logic Summary

- **Match found** (issue time falls within a row's STARTTIME–ENDTIME): generates 1 link with a ±6 hour window around the issue time.
- **No match**: generates links for every row, with STARTTIME−1h → ENDTIME+1h as the time window.

The script prints each link to the console and opens all of them in the browser automatically.
