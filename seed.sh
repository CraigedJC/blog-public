#!/usr/bin/env bash
# Creates the two tables and seeds the autonomy state row for one workflow.
# Usage: ./seed.sh <storage-account> <workflow-name>
# Needs: az CLI signed in, and your user holding "Storage Table Data Contributor" on the account.
set -euo pipefail
ACCT="${1:?storage account name}"
WF="${2:-invoice-triage}"
TOKEN="$(az account get-access-token --resource https://storage.azure.com/ --query accessToken -o tsv)"
BASE="https://${ACCT}.table.core.windows.net"
hdr=(-H "Authorization: Bearer ${TOKEN}" -H "x-ms-version: 2019-02-02" -H "Accept: application/json;odata=nometadata" \
     -H "Content-Type: application/json" -H "x-ms-date: $(date -u '+%a, %d %b %Y %H:%M:%S GMT')")

for t in AutonomyState AgentAudit; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "${BASE}/Tables" "${hdr[@]}" -d "{\"TableName\":\"${t}\"}")
  echo "create ${t}: HTTP ${code} (201 created, 409 already exists)"
done

# JSON numbers and booleans keep their types, which the Logic App's schema expects.
code=$(curl -s -o /dev/null -w '%{http_code}' -X PUT "${BASE}/AutonomyState(PartitionKey='${WF}',RowKey='state')" "${hdr[@]}" \
  -d '{"mode":"gated","sampleRate":100,"audits":0,"disagreements":0,"killSwitch":false,"lastDecision":"none"}')
echo "seed state for ${WF}: HTTP ${code} (204 is success)"
