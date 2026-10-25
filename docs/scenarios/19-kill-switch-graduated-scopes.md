# 19. The kill switch, at four scopes: one tool, one agent, one run, everything

**What this proves:** an operator with the right role can stop exactly the part of the system that is misbehaving: one action, one agent, one run, or all of it. A clerk cannot, and every switch takes effect on the very next authorization.

## Background
`custodian-control-plane` stores switches in `kill_switches` (scope `tool` | `agent` | `thread` | `global`, a target, a reason, a trigger, who tripped it and when). `POST /trip` and `POST /reset` need a Keycloak token carrying the `finance_controller` or `cfo` role (`custodian-control-plane/app/auth.py`). The policy service calls `GET /check?agent=&thread=&tool=` on every `/authorize`, so there is no cache to wait out. The console's Kill switch page drives the same API.

`infra/scripts/token.sh clerk|controller|cfo` gets an access token through the realm's `custodian-cli` direct-grant client (local development only).

## Steps
Let `trip`/`reset` be `curl -s -X POST http://127.0.0.1:18011/{trip,reset} -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '<body>'`, and check with three requests: the payment agent's `ExecutePayment`, the risk agent's `ScoreRisk` and the extraction agent's `ExtractInvoice` (scenario 13's format; the first two on thread `scenario-13-thread-a`).
0. Baseline: all three allowed.
1. `TOKEN=$(infra/scripts/token.sh clerk)`; trip `{"scope":"global","reason":"clerk attempt"}`
2. `TOKEN=$(infra/scripts/token.sh controller)`; trip `{"scope":"tool","target":"ExecutePayment","reason":"scenario 13: bank file under review"}`; retry payment and risk
3. Trip `{"scope":"agent","target":"risk-scoring",...}`; retry risk and extraction
4. Reset the agent switch, trip `{"scope":"thread","target":"scenario-13-thread-a",...}`; retry risk on thread a and on thread b
5. Trip `{"scope":"global","reason":"scenario 13: incident drill"}`; retry extraction
6. Reset global, thread and tool; retry payment

## What you'll see
```
=== 0. baseline
allow ['cedar: execute-approved-payment']
allow ['cedar: risk-agent-scores']
allow ['cedar: extraction-agent-extracts']
=== 1. clerk cannot operate the kill switch
{"detail":"kill switch operations need the finance_controller or cfo role"}
HTTP 403
=== 2. tool scope: freeze ExecutePayment
{"id":1,"scope":"tool","target":"ExecutePayment","reason":"scenario 13: bank file under review","trigger":"manual","tripped_by":"controller","tripped_at":"2026-10-24T16:02:59.192191Z"}
deny  {'kill_switch': 'blocked', 'cedar': 'allow', 'temporal': 'allow'} ['kill switch: tool ExecutePayment: scenario 13: bank file under review', 'cedar: execute-approved-payment']
allow {'kill_switch': 'clear', 'cedar': 'allow', 'temporal': 'allow'} ['cedar: risk-agent-scores']
=== 3. agent scope: freeze risk-scoring
deny  {'kill_switch': 'blocked', ...} ['kill switch: agent risk-scoring: scenario 13: model drift suspected', 'cedar: risk-agent-scores']
allow {'kill_switch': 'clear', ...} ['cedar: extraction-agent-extracts']
=== 4. thread scope: freeze one run
deny  {'kill_switch': 'blocked', ...} ['kill switch: thread scenario-13-thread-a: scenario 13: suspicious run', 'cedar: risk-agent-scores']
allow {'kill_switch': 'clear', ...} ['cedar: risk-agent-scores']
=== 5. global
deny  {'kill_switch': 'blocked', ...} ['kill switch: global *: scenario 13: incident drill', 'cedar: extraction-agent-extracts']
=== 6. reset everything
allow {'kill_switch': 'clear', 'cedar': 'allow', 'temporal': 'allow'} ['cedar: execute-approved-payment']
```
Note that in every blocked case Cedar still said `allow`: the kill switch overrides policy, it does not replace it.

## What this actually teaches
A single big red button makes the stop expensive enough that people hesitate to press it. Graduated scopes make stopping cheap: freezing payments while a bank file is checked leaves invoice intake and scoring running, and freezing one suspicious run leaves the other runs alone. Requiring the controller or CFO role for both trip and reset keeps a clerk from either stopping the floor or quietly un-stopping it, and every trip and reset is written to the audit log with the operator's name. Honest limit: a kill switch stops the next authorization, not a step already past its check. The settlement hold scenario covers the window between approval and commit (pending the reasoning route; see the index).
