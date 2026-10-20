# Logic Apps autonomy ratchet

A working pattern for earning an AI agent's autonomy instead of granting it. One Azure Logic App (Consumption) calls
an actor agent, checks it with an independent auditor, escalates anything risky to a human, and then adjusts its own
audit sample rate based on measured results.

Think of the autonomy ratchet as a dial. It turns up in small, earned steps and snaps straight back when the
evidence turns bad.

This is the companion repo for a two part blog series on [blog.chiffers.com](https://blog.chiffers.com):

1. [How to Move from Logic Apps to Autonomous AI Agents on Azure, Safely](https://blog.chiffers.com/how-to-move-from-logic-apps-to-autonomous-ai-agents-on-azure-safely/), the ladder, the control plane and a five step migration path
2. Building a Sampled Audit and Autonomy Ratchet in Azure Logic Apps, the hands-on build in this repo

The demo workflow is called `invoice-triage`, the "Tuesday queue" from the series.

## Quick start

1. Deploy `azuredeploy.json` (see Deploy below).
2. Grant the four role assignments.
3. Run `./seed.sh` to create the tables and the state row.
4. Run `./demo.sh` and watch the ratchet promote, demote and hold the line on irreversible actions.
5. Flip the kill switch and watch a run return a 503.

## What it demonstrates

| Idea from the post | Where it lives in the demo |
|---|---|
| Autonomy is earned, not granted | The ratchet: `Calc_Decision` and `Update_State` |
| Auditor independent of the actor | `Call_Auditor` uses a different deployment and a different managed identity |
| Gates demoted, not removed | `gated` mode audits every run. `sampled` mode audits a random slice |
| Action classification | `actionClass` is `reversible` or `irreversible`. Irreversible is always audited and always goes to a human |
| Kill switch | `killSwitch` on the state row. The run returns 503 and terminates |
| Decision level traces | One row per run in the `AgentAudit` table |
| Trust slow to earn, quick to lose | Demote after 20 audits. Promote only after a full 50 audit window |

![Flow](graphics/2-logic-app-flow.png)

## Files

| File | Purpose |
|---|---|
| `azuredeploy.json` | ARM template. Deploys the Logic App with a system identity and a user assigned auditor identity |
| `workflow-definition.json` | Just the workflow definition, for reading or pasting into Code view |
| `build_logicapp.py` | Source of truth. Regenerates both JSON files and runs static checks |
| `seed.sh` | Creates the two tables and seeds the state row |
| `demo.sh`, `show_state.sh` | Drive and inspect the ratchet on stage |
| `ratchet_sim.py` | Simulates the same ratchet rules. Produced the third graphic |
| `make_graphics.py`, `graphics/` | The three PNGs for the post |

## Deploy

You need an Azure OpenAI resource with **two different model deployments** (actor and auditor), a storage account,
and a user assigned managed identity for the auditor.

```bash
az deployment group create -g <rg> --template-file azuredeploy.json --parameters \
  storageAccount=<storage-account> \
  actorUrl="https://<aoai>.openai.azure.com/openai/deployments/<actor>/chat/completions?api-version=2024-10-21" \
  auditorUrl="https://<aoai>.openai.azure.com/openai/deployments/<auditor>/chat/completions?api-version=2024-10-21" \
  auditorIdentityResourceId=<resource id of the user assigned identity> \
  teamsWebhookUrl=<teams workflow webhook url> \
  minAudits=5 windowAudits=10 demoMode=true
```

Then grant roles. Allow a few minutes for them to propagate.

| Identity | Role | Scope |
|---|---|---|
| Logic App system identity | Storage Table Data Contributor | the storage account |
| Logic App system identity | Cognitive Services OpenAI User | the Azure OpenAI resource (actor calls) |
| Auditor user assigned identity | Cognitive Services OpenAI User | the Azure OpenAI resource (auditor calls) |
| You | Storage Table Data Contributor | the storage account (so `seed.sh` works) |

Seed the state, then run the demo:

```bash
./seed.sh <storage-account> invoice-triage
./demo.sh "<logic app callback url>" <storage-account> invoice-triage
```

`demo.sh` needs `demoMode=true`, `minAudits=5` and `windowAudits=10`. That lets the trigger carry a `forceVerdict` so the audit outcome is repeatable on
stage. Leave `demoMode` off for anything real, because it lets a caller override the auditor.

## The ratchet rules

- **Gated** (sample rate 100): every run is audited.
- **Promote** halves the sample rate (100, 50, 25, 12, 6, 5), only when a full 50 audit window has a failure rate of 2% or less.
- **Demote** snaps back to 100 as soon as 20 audits exist and failures exceed 5%.
- The evidence window resets whenever it fills or a decision fires, so old clean audits cannot hide new drift.
- All thresholds are parameters: `minAudits`, `windowAudits`, `promoteBelow`, `demoteAbove`.

![Ratchet](graphics/3-ratchet-in-action.png)

## What the simulation found

Two flaws showed up while I tested the rules in `ratchet_sim.py`, and both are fixed in the workflow.

1. **Re-promotion in the middle of an incident.** With symmetric thresholds, one lucky window of 20 clean audits
   promoted the agent while it was still drifting. Promotion now needs a bigger window than demotion.
2. **Drift hidden by old data.** Counters that only reset on a decision let a long clean history dilute a new
   failure rate until it was never detected. The tumbling window fixed that.

The result worth discussing on stage: at the 5% floor, detection takes time. Across 200 random seeds with a 12%
error burst, the first demotion came a median of 284 runs after drift began (90th percentile 580), and roughly 60
bad outputs executed unaudited in the plotted example. Your floor sample rate is your blast radius. That is why
irreversible actions are always audited regardless of mode.

## Status and limits

- **Verified so far:** the template passes static checks (every action reference, parameter and variable
  resolves) and the ratchet rules are exercised by simulation. A live Azure deployment is the next milestone, so
  expect small fixes on first deploy, such as the OpenAI `api-version` or role propagation delays. Issues and pull
  requests are very welcome.
- **The simulation is illustrative.** It assumes the auditor catches every error it samples. Real auditors miss
  things, so also measure auditor disagreement against human review.
- **Sampled mode audits inline.** To keep the demo simple, a sampled audit runs before the action. In production,
  execute first and audit asynchronously, with rollback for reversible actions.
- **The audit table is a trace, not a tamper proof log.** For regulated work, write to immutable storage or Log
  Analytics as well.
- **Throughput is capped.** The ratchet updates one state row per workflow, so the trigger runs one at a time.
  Scale out with one state row per workflow, or move the counters to a service built for concurrency.
- **Independence is only real if you deploy it.** An auditor using the same model and the same identity as the
  actor mostly agrees with it.
- **Cost.** Consumption bills per action and there are about 29 per run, plus model tokens for one or two calls.
- **`Execute_Action` is a placeholder.** Replace it with your real downstream call.

## Contributing

Found a bug, tried it on a different model, or built the approval step or the asynchronous audit? Open an issue or a
pull request. Regenerate the JSON from `build_logicapp.py` rather than editing it by hand, and run
`python3 build_logicapp.py` to confirm the static checks pass.

## Licence

MIT. See [LICENSE](LICENSE).
