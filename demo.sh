#!/usr/bin/env bash
# Drives the ratchet on stage. Deploy with demoMode=true, minAudits=5 and windowAudits=10 first.
# Usage: ./demo.sh "<logic-app-callback-url>" <storage-account> [workflow-name]
set -euo pipefail
URL="${1:?Logic App HTTP callback URL}"; ACCT="${2:?storage account}"; WF="${3:-invoice-triage}"
send() {  # $1 = verdict to force, $2 = action class, $3 = label
  curl -s -X POST "$URL" -H 'Content-Type: application/json' \
    -d "{\"workflowName\":\"${WF}\",\"actionClass\":\"$2\",\"task\":\"Approve vendor invoice INV-1042 for 480 EUR, PO matches.\",\"forceVerdict\":\"$1\"}" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print('$3', '->', d['outcome'], '| verdict', d['verdict'], '| ratchet', d['ratchetDecision'], '| sample rate now', d['sampleRateNow'])"
}
echo "== Phase 1: 10 clean runs. Expect the ratchet to promote from 100 to 50 =="
for i in $(seq 1 10); do send pass reversible "run $i"; done
./show_state.sh "$ACCT" "$WF"
echo "== Phase 2: the auditor starts failing outputs. Expect a demotion back to 100 =="
for i in $(seq 1 20); do send fail reversible "run $i"; done
./show_state.sh "$ACCT" "$WF"
echo "== Phase 3: an irreversible action. It is always audited and always goes to a human =="
send pass irreversible "payment run"
echo "== Phase 4: flip the kill switch in AutonomyState (killSwitch=true) and call again. Expect HTTP 503 =="
