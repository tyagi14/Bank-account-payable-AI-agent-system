# 12. A legitimate policy change is accepted and takes effect live, without a restart

**What this proves:** tightening a business rule is a one-line policy change that is validated, hot-reloaded, and changes the next decision immediately, with no code change or redeploy.

## Background
The auto-approve limit lives only in `policies/approval.cedar` (`context.amountCents <= 500000`, i.e. $5,000); no Python code knows the number. The policy service evaluates whatever policy set it last loaded successfully.

## Steps
1. Ask for a $4,000 auto-approval from a known vendor at low risk and high confidence:
   ```
   infra/scripts/call.sh policy-service POST /authorize '{"principal":{"type":"Agent","id":"approval"},"action":"AutoApproveInvoice","resource":{"type":"Invoice","id":"scenario-10"},"context":{"amountCents":400000,"vendor":"SCENARIO 10 VENDOR","vendorKnown":true,"riskScoreBp":800,"decisionConfidenceBp":9200}}'
   ```
2. Lower the limit to $3,000: `sed -i.bak 's/context.amountCents <= 500000/context.amountCents <= 300000/' policies/approval.cedar && rm policies/approval.cedar.bak`
3. `python3 infra/scripts/validate-cedar-policies.py`
4. `infra/scripts/call.sh policy-service POST /reload`, then repeat step 1
5. Revert (`git checkout policies/approval.cedar`), reload, repeat step 1

## What you'll see
Step 1: `HTTP 200 allow ['cedar: auto-approve-routine']`

Step 2's diff:
```
12c12
<     context.amountCents <= 500000 &&
---
>     context.amountCents <= 300000 &&
```
Step 3:
```
[schema]   PASS
[lint]     PASS
[temporal] PASS ["vendor-approvals-per-24h: 3 per 24h on ['AutoApproveInvoice', 'HumanApproveInvoice']"]
[matrix]   26 cases

ACCEPTED
```
Step 4: `HTTP 200` for the reload, then `HTTP 200 deny ['cedar: no permit policy matched (default deny)']` for the same $4,000 request.

Step 5: `HTTP 200 allow ['cedar: auto-approve-routine']` again.

## What this actually teaches
Governance rules that live in policy files can be reviewed, diffed, validated and rolled out by people who do not edit application code, and the effect is visible on the very next decision. The run also showed a real gap in the validator: the 26-case matrix accepted the new limit because it has cases at $1,000 and $6,000 but none between $3,000 and $5,000. A matrix proves what it tests and nothing in between. A policy change should come with a matrix case that pins down the new boundary.
