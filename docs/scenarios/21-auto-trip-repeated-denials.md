# 21. An agent that keeps asking for forbidden things is stopped automatically

**What this proves:** without any human involved, the control plane's watchdog freezes an agent that collects five policy refusals in ten minutes, and the freeze then blocks even that agent's legitimate work until a controller resets it.

## Background
`custodian-control-plane/app/watchdog.py`'s `denial_offenders` runs every `WATCHDOG_INTERVAL_SECONDS=15`. It counts, per agent, denials in `policy_decisions` within `DENIAL_TRIP_WINDOW_SECONDS=600` that:
- are not routing denials (`AutoApproveInvoice` being refused is the normal "send it to a human" signal),
- were refused by Cedar or the temporal rule, not by a kill switch or an outage (scenario 20), and
- happened since that agent's last reset.

At `DENIAL_TRIP_COUNT=5` it trips an `agent` switch with trigger `repeated_denials`. The other automatic triggers are a canary vendor and a missed heartbeat. Those need the full pipeline and are listed as pending in the index.

## Steps
1. Five times, ask for something the risk agent may not do (execute a payment):
   `infra/scripts/call.sh policy-service POST /authorize '{"principal":{"type":"Agent","id":"risk-scoring"},"action":"ExecutePayment","resource":{"type":"Invoice","id":"scenario-15-1"},"context":{"amountCents":100000,"vendor":"SCENARIO 15 CO","approvalRoute":"auto"}}'`
2. Poll `infra/scripts/call.sh custodian-control-plane GET '/check?agent=risk-scoring'` every 5 s
3. Ask for something the risk agent normally may do (`ScoreRisk`)
4. Reset it: `TOKEN=$(infra/scripts/token.sh controller)`; `curl -s -X POST http://127.0.0.1:18011/reset -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"scope":"agent","target":"risk-scoring"}'`

## What you'll see
Step 1, five times:
```
HTTP 200 deny {'kill_switch': 'clear', 'cedar': 'deny', 'temporal': 'allow'} ['cedar: no permit policy matched (default deny)']
```
Step 2 (the last denial was at 16:04:30):
```
16:04:46 HTTP 200
{
  "blocked_by": [
    "agent risk-scoring: 5 policy denials in 600s"
  ]
}
```
Step 3:
```
HTTP 200 deny {'kill_switch': 'blocked', 'cedar': 'allow', 'temporal': 'allow'} ['kill switch: agent risk-scoring: 5 policy denials in 600s', 'cedar: risk-agent-scores']
```
After step 4, `/check` returns `{"blocked_by": []}`.

## What this actually teaches
An agent repeatedly asking for things outside its permissions is a symptom (a manipulated prompt, a broken model version, an attacker probing). Each individual request was refused anyway, but the pattern is the signal, and acting on it within 16 s limits how long a compromised agent gets to keep probing. Requiring a human with the controller role to reset makes someone look at why before it resumes. The thresholds are a judgment call, and they depend on the exclusions. Without them, a burst of legitimate first-seen-vendor invoices (each one an `AutoApproveInvoice` refusal), or a control-plane outage (scenario 20), would trip a well-behaved agent.
