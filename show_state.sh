#!/usr/bin/env bash
# Prints the current autonomy state row. Usage: ./show_state.sh <storage-account> <workflow-name>
set -euo pipefail
ACCT="${1:?storage account name}"; WF="${2:-invoice-triage}"
TOKEN="$(az account get-access-token --resource https://storage.azure.com/ --query accessToken -o tsv)"
curl -s "https://${ACCT}.table.core.windows.net/AutonomyState(PartitionKey='${WF}',RowKey='state')" \
  -H "Authorization: Bearer ${TOKEN}" -H "x-ms-version: 2019-02-02" -H "Accept: application/json;odata=nometadata" \
  -H "x-ms-date: $(date -u '+%a, %d %b %Y %H:%M:%S GMT')" | python3 -m json.tool
