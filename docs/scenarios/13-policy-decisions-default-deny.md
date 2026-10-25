# 13. Every action is authorized by the Policy Decision Point, and the default is no

**What this proves:** each agent action is checked against the kill switch, Cedar and the temporal rules. Anything not explicitly permitted is denied, a malformed request is denied rather than erroring into an allow, and every decision is recorded.

## Background
Before every consequential step, `custodian-backend/app/governance.py` checks two things. First, the agent's capability manifest (`custodian-backend/manifests/*.json`); only `payment-execution` lists `ledger.write`. Then the policy service's `POST /authorize` (`infra/policy-service/app/main.py`), which:
1. Asks the control plane whether a kill switch covers this agent, thread or action. If the control plane is unreachable, it fails closed (scenario 20).
2. Evaluates Cedar against `policies/*.cedar`, with agents' clearance and trust tier from `policies/entities.json`. No matching permit means deny.
3. Inside the same transaction, counts the temporal rule's window (scenario 14).
4. Appends the decision to the audit log. If that append fails, an allow is turned into a deny ("an unaudited allow is not permitted").
5. Writes the decision, its reasons and per-check verdicts to `policy_decisions`, and increments `policy_decisions_total`.

The policy service is not published to the host; `infra/scripts/call.sh` runs the request from inside its container.

## Steps
```
infra/scripts/call.sh policy-service POST /authorize '<request>'
```
with these seven requests (resource `{"type":"Invoice","id":"scenario-11"}` unless stated):

| # | principal | action | context |
|---|---|---|---|
| 1 | Agent `approval` | AutoApproveInvoice | $1,200, known vendor, risk 0.12, confidence 0.91 |
| 2 | Agent `approval` | AutoApproveInvoice | $6,200, same otherwise |
| 3 | Agent `approval` | AutoApproveInvoice | $1,200, `vendorKnown: false` |
| 4 | Agent `extraction` | ExecutePayment | $1,200, approvalRoute auto |
| 5 | Human `clerk` (role `ap_clerk`) | HumanApproveInvoice | $15,000 |
| 6 | Agent `extraction` | ReadData on DataAsset `historical_payments` | |
| 7 | Agent `approval` | AutoApproveInvoice | `{"amountCents": "lots"}` |

## What you'll see
```
1  "decision": "allow"  reasons ["cedar: auto-approve-routine"]
   checks {"kill_switch": "clear", "cedar": "allow", "temporal": "allow"}
2  "decision": "deny"   reasons ["cedar: no permit policy matched (default deny)"]
3  "decision": "deny"   reasons ["cedar: first-seen-vendor-requires-human"]
4  "decision": "deny"   reasons ["cedar: no permit policy matched (default deny)"]
5  "decision": "deny"   reasons ["cedar: no permit policy matched (default deny)"]
6  "decision": "deny"   reasons ["cedar: no permit policy matched (default deny)"]
7  "decision": "deny"   reasons ["failed to build request: while parsing context, expected the record to have an attribute `decisionConfidenceBp`, but it does not"]
```
(Each response also carries `"checks"`; for 2 to 7 the kill switch was `clear` and the temporal check `allow`, so Cedar alone denied.)

## A real failure the first attempt hit
The first time this scenario ran, request 1 came back **deny** with Cedar, temporal and the kill switch all allowing:
```
"decision": "deny",
"reasons": ["cedar: auto-approve-routine", "audit log unavailable; an unaudited allow is not permitted"]
```
The audit log was taking 31 s per append. ClickHouse's self-monitoring tables were using 2.3 cores while idle and starving MinIO, which was taking 15 s per request. Policy-service waits 5 s for the audit append, so it failed closed. Turning ClickHouse's self-logging off (`infra/clickhouse/*.xml`) brought MinIO back to milliseconds, and the rerun above allowed request 1.

The same incident exposed a one-directional mismatch. The audit append that timed out did complete later, so the chain recorded `allow` for a request whose caller got `deny`. `policy_decisions` holds the effective decision. The reverse, an allow without a confirmed audit entry, cannot happen.

## What this actually teaches
Default deny means the permits are the whole specification of what agents may do. Everything in this table that was refused was refused because nobody wrote a permit for it, not because someone remembered to write a forbid. Making the audit write a precondition of an allow turns audit availability into a safety property, at the cost of turning slow storage into refused payments, which is what happened.
