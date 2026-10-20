#!/usr/bin/env python3
"""Builds the Logic App (Consumption) definition and an ARM template from one source.

Outputs (next to this script):
  workflow-definition.json   paste into Logic App > Logs/Code view ("Code view")
  azuredeploy.json           ARM template that deploys the Logic App with identities

Pattern: actor agent -> policy gate -> sampled independent audit -> autonomy ratchet
-> append to audit log. Autonomy state lives in Azure Table Storage.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent

TABLE_HEADERS = {
    "Accept": "application/json;odata=nometadata",
    "Content-Type": "application/json",
    "x-ms-version": "2019-02-02",
    "x-ms-date": "@{utcNow('R')}",
}
STORAGE_AUTH = {"type": "ManagedServiceIdentity", "audience": "https://storage.azure.com/"}
AOAI_AUTH = {"type": "ManagedServiceIdentity", "audience": "https://cognitiveservices.azure.com"}
AUDITOR_AUTH = {
    "type": "ManagedServiceIdentity",
    "identity": "@parameters('auditorIdentity')",
    "audience": "https://cognitiveservices.azure.com",
}

TABLE_BASE = "concat('https://', parameters('storageAccount'), '.table.core.windows.net/', "
STATE_URL = (
    "@{" + TABLE_BASE + "parameters('stateTable'), '(PartitionKey=''', "
    "triggerBody()?['workflowName'], ''',RowKey=''state'')')}"
)
AUDIT_URL = (
    "@{" + TABLE_BASE + "parameters('auditTable'), '(PartitionKey=''', "
    "triggerBody()?['workflowName'], ''',RowKey=''', workflow()['run']['name'], ''')')}"
)

ACTOR_SYSTEM = (
    "You are the actor agent in an automated workflow. Decide how to handle the task. "
    "Reply with JSON only, in this shape: "
    "{\"decision\": string, \"confidence\": number between 0 and 1, \"rationale\": string}. "
    "Be honest about uncertainty. Low confidence is better than a confident guess."
)
AUDITOR_SYSTEM = (
    "You are an independent auditor. You did not make this decision. Check whether the decision is "
    "supported by the task and is safe to execute. Reply with JSON only, in this shape: "
    "{\"verdict\": \"pass\" or \"fail\", \"reason\": string}. Fail it if you are unsure."
)


def http(method, uri, body=None, auth=None, headers=None, run_after=None):
    inputs = {"method": method, "uri": uri}
    if headers:
        inputs["headers"] = headers
    if body is not None:
        inputs["body"] = body
    if auth:
        inputs["authentication"] = auth
    action = {"type": "Http", "inputs": inputs, "runAfter": run_after or {}}
    return action


def chat_body(system, user_expr):
    return {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_expr},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }


def after(name, status="Succeeded"):
    return {name: [status]}


# ---- inside the audit branch -------------------------------------------------------------
audit_branch = {
    "Call_Auditor": http(
        "POST",
        "@parameters('auditorUrl')",
        chat_body(
            AUDITOR_SYSTEM,
            "@{concat('Task: ', triggerBody()?['task'], '\nActor decision: ', "
            "body('Parse_Actor')?['decision'], '\nActor rationale: ', body('Parse_Actor')?['rationale'])}",
        ),
        AUDITOR_AUTH,
    ),
    "Parse_Auditor": {
        "type": "ParseJson",
        "inputs": {
            "content": "@json(body('Call_Auditor')?['choices']?[0]?['message']?['content'])",
            "schema": {
                "type": "object",
                "properties": {"verdict": {"type": "string"}, "reason": {"type": "string"}},
            },
        },
        "runAfter": after("Call_Auditor"),
    },
    "Set_Verdict": {
        "type": "SetVariable",
        "inputs": {
            "name": "verdict",
            # demoMode lets you force a verdict on stage so the ratchet demo is repeatable.
            "value": "@if(and(parameters('demoMode'), not(empty(triggerBody()?['forceVerdict']))), "
            "triggerBody()?['forceVerdict'], toLower(body('Parse_Auditor')?['verdict']))",
        },
        "runAfter": after("Parse_Auditor"),
    },
    "Set_Verdict_Reason": {
        "type": "SetVariable",
        "inputs": {"name": "verdictReason", "value": "@body('Parse_Auditor')?['reason']"},
        "runAfter": after("Set_Verdict"),
    },
}

# ---- escalate or execute -----------------------------------------------------------------
escalate_true = {
    "Post_To_Teams": http(
        "POST",
        "@parameters('teamsWebhookUrl')",
        {
            "text": "@{concat('Agent escalation for ', triggerBody()?['workflowName'], '. Action class: ', "
            "triggerBody()?['actionClass'], '. Audit verdict: ', variables('verdict'), '. Task: ', "
            "triggerBody()?['task'], '. Proposed decision: ', body('Parse_Actor')?['decision'])}"
        },
    ),
    "Set_Outcome_Escalated": {
        "type": "SetVariable",
        "inputs": {"name": "outcome", "value": "escalated_to_human"},
        "runAfter": after("Post_To_Teams"),
    },
}
escalate_false = {
    "Execute_Action": {
        "type": "Compose",
        "description": "Replace this with the real action: an HTTP call to your ERP, ticketing or claims system.",
        "inputs": "@body('Parse_Actor')?['decision']",
        "runAfter": {},
    },
    "Set_Outcome_Executed": {
        "type": "SetVariable",
        "inputs": {"name": "outcome", "value": "auto_executed"},
        "runAfter": after("Execute_Action"),
    },
}

# ---- the workflow ------------------------------------------------------------------------
actions = {
    "Init_Verdict": {
        "type": "InitializeVariable",
        "inputs": {"variables": [{"name": "verdict", "type": "string", "value": "skipped"}]},
        "runAfter": {},
    },
    "Init_Verdict_Reason": {
        "type": "InitializeVariable",
        "inputs": {"variables": [{"name": "verdictReason", "type": "string", "value": ""}]},
        "runAfter": after("Init_Verdict"),
    },
    "Init_Outcome": {
        "type": "InitializeVariable",
        "inputs": {"variables": [{"name": "outcome", "type": "string", "value": "pending"}]},
        "runAfter": after("Init_Verdict_Reason"),
    },
    "Get_State": http(
        "GET", STATE_URL, auth=STORAGE_AUTH, headers=TABLE_HEADERS, run_after=after("Init_Outcome")
    ),
    "Parse_State": {
        "type": "ParseJson",
        "inputs": {
            "content": "@body('Get_State')",
            "schema": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string"},
                    "sampleRate": {"type": "integer"},
                    "audits": {"type": "integer"},
                    "disagreements": {"type": "integer"},
                    "killSwitch": {"type": "boolean"},
                },
            },
        },
        "runAfter": after("Get_State"),
    },
    "Check_Kill_Switch": {
        "type": "If",
        "expression": {"equals": ["@body('Parse_State')?['killSwitch']", True]},
        "actions": {
            "Reject_Kill_Switch": {
                "type": "Response",
                "kind": "Http",
                "inputs": {
                    "statusCode": 503,
                    "body": {"outcome": "blocked_by_kill_switch"},
                },
                "runAfter": {},
            },
            "Terminate_Kill_Switch": {
                "type": "Terminate",
                "inputs": {"runStatus": "Cancelled"},
                "runAfter": after("Reject_Kill_Switch"),
            },
        },
        "else": {"actions": {}},
        "runAfter": after("Parse_State"),
    },
    "Call_Actor": http(
        "POST",
        "@parameters('actorUrl')",
        chat_body(ACTOR_SYSTEM, "@{triggerBody()?['task']}"),
        AOAI_AUTH,
        run_after=after("Check_Kill_Switch"),
    ),
    "Parse_Actor": {
        "type": "ParseJson",
        "inputs": {
            "content": "@json(body('Call_Actor')?['choices']?[0]?['message']?['content'])",
            "schema": {
                "type": "object",
                "properties": {
                    "decision": {"type": "string"},
                    "confidence": {"type": "number"},
                    "rationale": {"type": "string"},
                },
            },
        },
        "runAfter": after("Call_Actor"),
    },
    "Compose_Audit_Required": {
        "type": "Compose",
        "description": "Gated mode audits every run. Sampled mode audits a random slice. "
        "Irreversible actions and low confidence are always audited.",
        "inputs": "@or(or(equals(body('Parse_State')?['mode'], 'gated'), "
        "less(rand(0, 100), body('Parse_State')?['sampleRate'])), "
        "or(equals(triggerBody()?['actionClass'], 'irreversible'), "
        "less(body('Parse_Actor')?['confidence'], 0.7)))",
        "runAfter": after("Parse_Actor"),
    },
    "Run_Audit": {
        "type": "If",
        "expression": {"equals": ["@outputs('Compose_Audit_Required')", True]},
        "actions": audit_branch,
        "else": {"actions": {}},
        "runAfter": after("Compose_Audit_Required"),
    },
    "Escalate_Or_Execute": {
        "type": "If",
        "description": "Policy gate. Humans own irreversible actions, low confidence and failed audits.",
        "expression": {
            "or": [
                {"equals": ["@triggerBody()?['actionClass']", "irreversible"]},
                {"less": ["@body('Parse_Actor')?['confidence']", 0.7]},
                {"equals": ["@variables('verdict')", "fail"]},
            ]
        },
        "actions": escalate_true,
        "else": {"actions": escalate_false},
        "runAfter": after("Run_Audit"),
    },
    # ---- the autonomy ratchet ----
    "Calc_Audits": {
        "type": "Compose",
        "inputs": "@add(body('Parse_State')?['audits'], if(outputs('Compose_Audit_Required'), 1, 0))",
        "runAfter": after("Escalate_Or_Execute"),
    },
    "Calc_Disagreements": {
        "type": "Compose",
        "inputs": "@add(body('Parse_State')?['disagreements'], "
        "if(and(outputs('Compose_Audit_Required'), equals(variables('verdict'), 'fail')), 1, 0))",
        "runAfter": after("Calc_Audits"),
    },
    "Calc_Rate": {
        "type": "Compose",
        "inputs": "@if(greater(outputs('Calc_Audits'), 0), "
        "div(float(outputs('Calc_Disagreements')), outputs('Calc_Audits')), 0)",
        "runAfter": after("Calc_Disagreements"),
    },
    "Calc_Decision": {
        "type": "Compose",
        "description": "Hold until enough audits exist. Demote fast on a high disagreement rate. "
        "Promote slowly, only on a low rate over a full evidence window. Windows reset when they fill so old clean audits cannot hide new drift. Trust is slow to earn, quick to lose.",
        "inputs": "@if(less(outputs('Calc_Audits'), parameters('minAudits')), 'hold', "
        "if(greater(outputs('Calc_Rate'), parameters('demoteAbove')), 'demote', "
        "if(and(greaterOrEquals(outputs('Calc_Audits'), parameters('windowAudits')), "
        "lessOrEquals(outputs('Calc_Rate'), parameters('promoteBelow'))), 'promote', 'hold')))",
        "runAfter": after("Calc_Rate"),
    },
    "Calc_New_Sample_Rate": {
        "type": "Compose",
        "description": "Promote halves the sample rate down to a floor of 5. Demote snaps back to 100.",
        "inputs": "@if(equals(outputs('Calc_Decision'), 'promote'), "
        "max(5, div(body('Parse_State')?['sampleRate'], 2)), "
        "if(equals(outputs('Calc_Decision'), 'demote'), 100, body('Parse_State')?['sampleRate']))",
        "runAfter": after("Calc_Decision"),
    },
    "Update_State": http(
        "PUT",
        STATE_URL,
        {
            "PartitionKey": "@triggerBody()?['workflowName']",
            "RowKey": "state",
            "mode": "@if(equals(outputs('Calc_New_Sample_Rate'), 100), 'gated', 'sampled')",
            "sampleRate": "@outputs('Calc_New_Sample_Rate')",
            "audits": "@if(or(not(equals(outputs('Calc_Decision'), 'hold')), "
            "greaterOrEquals(outputs('Calc_Audits'), parameters('windowAudits'))), 0, outputs('Calc_Audits'))",
            "disagreements": "@if(or(not(equals(outputs('Calc_Decision'), 'hold')), "
            "greaterOrEquals(outputs('Calc_Audits'), parameters('windowAudits'))), 0, outputs('Calc_Disagreements'))",
            "killSwitch": "@body('Parse_State')?['killSwitch']",
            "lastDecision": "@outputs('Calc_Decision')",
            "lastUpdated": "@utcNow()",
        },
        STORAGE_AUTH,
        TABLE_HEADERS,
        after("Calc_New_Sample_Rate"),
    ),
    "Write_Audit_Log": http(
        "PUT",
        AUDIT_URL,
        {
            "PartitionKey": "@triggerBody()?['workflowName']",
            "RowKey": "@workflow()['run']['name']",
            "timestamp": "@utcNow()",
            "task": "@triggerBody()?['task']",
            "actionClass": "@triggerBody()?['actionClass']",
            "actorDecision": "@body('Parse_Actor')?['decision']",
            "actorConfidence": "@body('Parse_Actor')?['confidence']",
            "actorRationale": "@body('Parse_Actor')?['rationale']",
            "audited": "@outputs('Compose_Audit_Required')",
            "verdict": "@variables('verdict')",
            "verdictReason": "@variables('verdictReason')",
            "outcome": "@variables('outcome')",
            "sampleRateAtRun": "@body('Parse_State')?['sampleRate']",
            "ratchetDecision": "@outputs('Calc_Decision')",
            "newSampleRate": "@outputs('Calc_New_Sample_Rate')",
        },
        STORAGE_AUTH,
        TABLE_HEADERS,
        after("Update_State"),
    ),
    "Respond": {
        "type": "Response",
        "kind": "Http",
        "inputs": {
            "statusCode": 200,
            "body": {
                "runId": "@{workflow()['run']['name']}",
                "outcome": "@variables('outcome')",
                "audited": "@outputs('Compose_Audit_Required')",
                "verdict": "@variables('verdict')",
                "ratchetDecision": "@outputs('Calc_Decision')",
                "sampleRateNow": "@outputs('Calc_New_Sample_Rate')",
            },
        },
        "runAfter": after("Write_Audit_Log"),
    },
}

PARAMS = {
    "storageAccount": ("String", "<storage-account-name>"),
    "stateTable": ("String", "AutonomyState"),
    "auditTable": ("String", "AgentAudit"),
    "actorUrl": (
        "String",
        "https://<aoai-resource>.openai.azure.com/openai/deployments/<actor-deployment>"
        "/chat/completions?api-version=2024-10-21",
    ),
    "auditorUrl": (
        "String",
        "https://<aoai-resource>.openai.azure.com/openai/deployments/<auditor-deployment>"
        "/chat/completions?api-version=2024-10-21",
    ),
    "auditorIdentity": (
        "String",
        "/subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.ManagedIdentity"
        "/userAssignedIdentities/<auditor-identity-name>",
    ),
    "minAudits": ("Int", 20),
    "windowAudits": ("Int", 50),
    "promoteBelow": ("Float", 0.02),
    "demoteAbove": ("Float", 0.05),
    "demoMode": ("Bool", False),
}

definition = {
    "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
    "contentVersion": "1.0.0.0",
    "parameters": {
        **{k: {"type": t, "defaultValue": d} for k, (t, d) in PARAMS.items()},
        "teamsWebhookUrl": {"type": "SecureString"},
    },
    "triggers": {
        "manual": {
            "type": "Request",
            "kind": "Http",
            "inputs": {
                "schema": {
                    "type": "object",
                    "required": ["workflowName", "actionClass", "task"],
                    "properties": {
                        "workflowName": {"type": "string"},
                        "actionClass": {"type": "string", "enum": ["reversible", "irreversible"]},
                        "task": {"type": "string"},
                        "forceVerdict": {"type": "string", "enum": ["pass", "fail"]},
                    },
                }
            },
            # One run at a time: the ratchet does read-modify-write on a single state row.
            "runtimeConfiguration": {"concurrency": {"runs": 1}},
        }
    },
    "actions": actions,
    "outputs": {},
}


def walk_actions(block, found=None):
    found = {} if found is None else found
    for name, act in block.items():
        found[name] = act
        for key in ("actions",):
            if key in act:
                walk_actions(act[key], found)
        if "else" in act:
            walk_actions(act["else"].get("actions", {}), found)
    return found


def check(defn):
    """Static checks: runAfter targets exist, referenced actions exist, no em or en dashes."""
    problems = []
    everything = walk_actions(defn["actions"])
    names = set(everything)
    for name, act in everything.items():
        for dep in act.get("runAfter", {}):
            if dep not in names:
                problems.append(f"{name}: runAfter target {dep} does not exist")
    text = json.dumps(defn)
    for ref in set(re.findall(r"(?:body|outputs|actions)\('([A-Za-z_]+)'\)", text)):
        if ref not in names:
            problems.append(f"expression references unknown action {ref}")
    for ref in set(re.findall(r"parameters\('([A-Za-z]+)'\)", text)):
        if ref not in defn["parameters"]:
            problems.append(f"expression references unknown parameter {ref}")
    for ref in set(re.findall(r"variables\('([A-Za-z]+)'\)", text)):
        if ref not in {"verdict", "verdictReason", "outcome"}:
            problems.append(f"expression references unknown variable {ref}")
    if "\u2014" in text or "\u2013" in text:
        problems.append("contains an em or en dash")
    return problems


def arm(defn):
    arm_params = {
        "logicAppName": {"type": "string", "defaultValue": "la-agent-ratchet-demo"},
        "location": {"type": "string", "defaultValue": "[resourceGroup().location]"},
        "auditorIdentityResourceId": {"type": "string"},
        "storageAccount": {"type": "string"},
        "actorUrl": {"type": "string"},
        "auditorUrl": {"type": "string"},
        "teamsWebhookUrl": {"type": "securestring"},
        "minAudits": {"type": "int", "defaultValue": 20},
        "windowAudits": {"type": "int", "defaultValue": 50},
        "demoMode": {"type": "bool", "defaultValue": False},
    }
    values = {
        "storageAccount": {"value": "[parameters('storageAccount')]"},
        "actorUrl": {"value": "[parameters('actorUrl')]"},
        "auditorUrl": {"value": "[parameters('auditorUrl')]"},
        "auditorIdentity": {"value": "[parameters('auditorIdentityResourceId')]"},
        "teamsWebhookUrl": {"value": "[parameters('teamsWebhookUrl')]"},
        "minAudits": {"value": "[parameters('minAudits')]"},
        "windowAudits": {"value": "[parameters('windowAudits')]"},
        "demoMode": {"value": "[parameters('demoMode')]"},
    }
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "contentVersion": "1.0.0.0",
        "parameters": arm_params,
        "resources": [
            {
                "type": "Microsoft.Logic/workflows",
                "apiVersion": "2019-05-01",
                "name": "[parameters('logicAppName')]",
                "location": "[parameters('location')]",
                "identity": {
                    "type": "SystemAssigned, UserAssigned",
                    "userAssignedIdentities": {"[parameters('auditorIdentityResourceId')]": {}},
                },
                "properties": {"state": "Enabled", "definition": defn, "parameters": values},
            }
        ],
    }


if __name__ == "__main__":
    problems = check(definition)
    if problems:
        print("PROBLEMS:")
        for p in problems:
            print(" -", p)
        sys.exit(1)
    (HERE / "workflow-definition.json").write_text(json.dumps(definition, indent=2) + "\n")
    (HERE / "azuredeploy.json").write_text(json.dumps(arm(definition), indent=2) + "\n")
    print(f"ok: {len(walk_actions(actions))} actions, static checks passed")
