# 14. A temporal rule: no more than three approvals per vendor in 24 hours

**What this proves:** a rule that depends on history, which stateless Cedar cannot express, is enforced on every decision from the decision log itself, and trips on the fourth approval.

## Background
`policies/temporal/vendor-approval-rate.dw` states the rule in Dogwood's temporal syntax: forbid `AutoApproveInvoice` or `HumanApproveInvoice` when the same vendor already had 3 approval responses within 24 h. Cedar is stateless, so `infra/policy-service/app/temporal.py` enforces it. It reads the window and the limit from the `.dw` text and counts `allow` decisions for that vendor in `policy_decisions`. It takes a per-vendor Postgres advisory lock inside the same transaction that records the new decision, so concurrent approvals cannot all see "under the limit". Denied approvals do not use up the budget.

## Steps
Send four otherwise-valid auto-approvals for the same new vendor (pick a vendor name nobody has used in the last 24 h, e.g. add a timestamp):
```
infra/scripts/call.sh policy-service POST /authorize '{"principal":{"type":"Agent","id":"approval"},"action":"AutoApproveInvoice","resource":{"type":"Invoice","id":"scenario-12-1"},"context":{"amountCents":125001,"vendor":"SCENARIO 12 RATE CO","vendorKnown":true,"riskScoreBp":900,"decisionConfidenceBp":9300}}'
```
(then `-2`, `-3`, `-4`, amounts 125002 to 125004), and read the decision log:
```
infra/scripts/compose.sh exec -T postgres psql -U custodian -d custodian -c "SELECT id, ts, resource, decision, reasons FROM policy_decisions WHERE vendor = 'SCENARIO 12 RATE CO' ORDER BY id"
```

## What you'll see
```
--- approval 1   "decision": "allow"
--- approval 2   "decision": "allow"
--- approval 3   "decision": "allow"
--- approval 4   "decision": "deny"
    "temporal: vendor-approvals-per-24h: 3 approvals for this vendor in the last 24h (limit 3)"
```
```
 15 | 16:02:07 | Invoice::scenario-12-1 | allow    | ["cedar: auto-approve-routine"]
 16 | 16:02:07 | Invoice::scenario-12-2 | allow    | ["cedar: auto-approve-routine"]
 17 | 16:02:08 | Invoice::scenario-12-3 | allow    | ["cedar: auto-approve-routine"]
 18 | 16:02:08 | Invoice::scenario-12-4 | deny     | ["cedar: auto-approve-routine", "temporal: vendor-approvals-per-24h: 3 approvals for this vendor in the last 24h (limit 3)"]
(4 rows)
```
Cedar permitted the fourth one (it is a perfectly ordinary $1,250 invoice); only the history refused it.

## What this actually teaches
Some of the most useful fraud controls are about patterns over time (velocity, splitting one payment into several under a threshold), and they need state that a stateless policy language does not have. Keeping the rule in a declarative file, and counting from the same log that records every decision, keeps it reviewable and auditable. Honest limits:
- **Not machine-validated as Dogwood.** The `.dw` file follows Dogwood's documented syntax but was not checked with the Dogwood CLI, and `temporal.py` accepts only this one rule shape.
- **The rule is per vendor-name string.** Vendor names are normalised, but an attacker who can vary the name defeats it; scenario 17's guardrail and the vendor master are the other defences.
- **The scenario leaves state behind.** Its approvals stay in the window for 24 h. Re-running with the same vendor name within a day starts from the fourth request's result.
