# 11. A dangerous policy change is rejected, by the validator and by the running service

**What this proves:** an over-permissive Cedar policy cannot reach production. The offline validator rejects it, and the live Policy Decision Point refuses to reload it and keeps serving the last good policy set.

## Background
`infra/scripts/validate-cedar-policies.py` re-runs itself inside the `policy-service` image, so it uses the exact engine the live service uses (`cedarpy`), and runs four stages:
- schema validation against `policies/schema.cedarschema.json`
- a permissiveness lint (`infra/policy-service/app/lint.py`) that rejects unconstrained permits, and money-moving permits with no principal constraint or no amount constraint
- a parse of the temporal `.dw` rule
- a 26-case authorization matrix with expected outcomes

The same lint and schema check run when the live service is asked to `/reload`. There is no CI in this project, so the validator is run by hand.

## Steps
1. `python3 infra/scripts/validate-cedar-policies.py`
2. Add a "temporary hotfix" as `policies/zz-hotfix.cedar`:
   ```
   // "temporary" hotfix to unblock the month-end close
   @id("hotfix-let-payments-through")
   permit (principal, action == Custodian::Action::"ExecutePayment", resource);
   ```
3. `python3 infra/scripts/validate-cedar-policies.py`
4. Ask the running service to load it: `infra/scripts/call.sh policy-service POST /reload`, then `infra/scripts/call.sh policy-service GET /health`
5. `rm policies/zz-hotfix.cedar` and `infra/scripts/call.sh policy-service POST /reload`

## What you'll see
Step 1:
```
[schema]   PASS
[lint]     PASS
[temporal] PASS ["vendor-approvals-per-24h: 3 per 24h on ['AutoApproveInvoice', 'HumanApproveInvoice']"]
[matrix]   26 cases
  ok   allow approval agent auto-approves $1,000 from a known vendor
  ok   deny  first-seen vendor cannot be auto-approved
  ok   deny  $6,000 exceeds the auto-approve limit
  ...
  ok   deny  payment agent refuses an auto-approved $50,000
  ...
  ok   allow risk agent scores risk

ACCEPTED
```
Step 3:
```
[schema]   PASS
[lint]     FAIL
           hotfix-let-payments-through: unconstrained permit (no principal, resource or condition)
           hotfix-let-payments-through: money-moving permit without a principal constraint
           hotfix-let-payments-through: money-moving permit without an amount constraint
[temporal] PASS ["vendor-approvals-per-24h: 3 per 24h on ['AutoApproveInvoice', 'HumanApproveInvoice']"]

REJECTED: fix the problems above before the matrix can run
exit 1
```
Step 4:
```
HTTP 422
{
  "detail": "reload rejected, previous policies still active: policies are overly permissive: ['hotfix-let-payments-through: unconstrained permit (no principal, resource or condition)', 'hotfix-let-payments-through: money-moving permit without a principal constraint', 'hotfix-let-payments-through: money-moving permit without an amount constraint']"
}
HTTP 200
{
  "status": "ok",
  "policies": 10
}
```
Step 5 reloads the ten original policies.

## What this actually teaches
The hotfix is schema-valid Cedar. A type checker would accept it, and it would let every principal execute any payment of any size. Catching it takes a check that knows what "dangerous" means in this domain, and that check has to run where the policy is loaded, not only in a pipeline someone might skip. Honest limit: the lint is a short list of hand-written patterns. A permit that is broad in a way it does not recognise (for example, one constrained to a principal that every agent happens to match) would pass the lint and fall through to the matrix, which only catches what its 26 cases exercise.
