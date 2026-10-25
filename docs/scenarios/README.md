# Scenarios

Every scenario was run against the live stack, and its "What you'll see" section is the real output of that run (trimmed only where marked). Where an attempt did not behave as expected, the scenario says so and shows what happened instead.

| # | Scenario | What it proves | Layer |
|---|---|---|---|
| 01 | [SPIRE workload identity](01-spire-workload-identity.md) | Identities are issued from container attestation, last one hour and rotate without a restart | Identity |
| 02 | [No SVID, no backend](02-no-svid-no-start.md) | The backend refuses to start without a workload identity and recovers when it returns | Identity |
| 03 | [Scoped secrets brokering](03-scoped-secrets-brokering.md) | Each machine identity can read only its own secret; every other read is a 403 | Identity |
| 04 | [Self-expiring credentials](04-self-expiring-credentials.md) | A secrets-platform token works at 290 s and is refused at 301 s, with no revocation | Identity |
| 05 | [Data-quality gate](05-data-quality-gate.md) | The checkpoint's self-test, plus real defects in SROIE/CORD, and a plausible wrong value only found by diffing | Data |
| 06 | [Catalog classification](06-catalog-classification.md) | OpenMetadata tags and Cedar clearances come from one file and agree | Data |
| 07 | [PII redaction](07-pii-redaction.md) | Identifiers are replaced before anything is stored, with the real false positives | Data |
| 08 | [Gateway route scopes](08-gateway-route-scopes.md) | Each agent key reaches only its own model routes (403 otherwise); no silent cross-provider fallback | Model |
| 09 | [Cost-cap enforcement](09-cost-cap-enforcement.md) | The gateway refuses calls once a key's budget is spent (and overshoots by one call) | Model |
| 10 | [Prompt promotion gate](10-prompt-promotion-gate.md) | A prompt reaches production only by beating 0.80 on held-out ground truth; v5 passed (0.883), v4 blocked (0.339) | Model |
| 11 | [Policy change rejected](11-policy-change-rejected.md) | An over-permissive policy is rejected offline and by the live service's reload | Policy |
| 12 | [Policy change accepted](12-policy-change-accepted.md) | A one-line limit change is validated, hot-reloaded, and flips the next decision | Policy |
| 13 | [Policy decisions, default deny](13-policy-decisions-default-deny.md) | Only explicitly permitted actions are allowed; malformed requests are denied; every decision is recorded | Policy |
| 14 | [Temporal vendor rate limit](14-temporal-vendor-rate-limit.md) | The fourth approval for one vendor within 24 h is denied from the decision history | Policy |
| 15 | [Sandboxed OCR](15-sandboxed-ocr.md) | Documents are parsed in a throwaway, networkless, capability-free container under Landlock | Agent runtime |
| 16 | [Prompt injection in a poisoned invoice](16-prompt-injection-poisoned-invoice.md) | Instructions aimed at the AI are caught before any agent acts; the first, fainter attempt never reached the model | Agent runtime |
| 17 | [Payment redirection blocked](17-payment-redirection-blocked.md) | A "bank details changed" request is rejected, and payees never come from documents | Agent runtime |
| 18 | [Ledger dry run](18-ledger-dry-run.md) | Unbalanced, unknown-account, zero and overdraft entries are rejected without touching balances | Agent runtime |
| 19 | [Kill switch, graduated scopes](19-kill-switch-graduated-scopes.md) | Tool, agent, thread and global switches each stop exactly their scope; a clerk cannot operate them | Agent runtime |
| 20 | [Kill switch fails closed](20-kill-switch-fails-closed.md) | No control plane, no allows; and the outage-to-frozen-agent cascade it exposed, fixed | Agent runtime |
| 21 | [Auto-trip on repeated denials](21-auto-trip-repeated-denials.md) | Five policy refusals in ten minutes freeze the agent within 16 s, until a controller resets it | Agent runtime |
| 22 | [Audit tamper detection](22-audit-tamper-detection.md) | Rewriting a decision is caught by the hash chain and by the WORM copy, and recorded in the chain | Operations |
| 23 | [Watchdog catches a reverted tamper](23-audit-watchdog-reverted-tamper.md) | A tamper undone before anyone checks is still on record; one undone within 2 s is not | Operations |
| 24 | [Object lock against root](24-object-lock-vs-root.md) | Root cannot delete or weaken locked entries; root could remove the bucket default, now closed off | Operations |
| 25 | [Metrics and traces](25-observability-metrics-and-traces.md) | A denial counter moves 0 to 3 within one scrape; agent LLM calls arrive in Langfuse as GenAI spans | Operations |

## Not yet run

These are designed and the code paths exist, but they have not been run to completion, so they have no scenario files yet. A scenario without real output would break the rule this directory follows. Each needs the reasoning route (the OpenAI account used for the build had no credits: scenario 08), and most also need a day's Groq quota for `gpt-oss-120b` (scenario 10).

| Planned | Needs | Covers |
|---|---|---|
| Routine invoice end to end (`01-routine-known-vendor.png`) | reasoning route | the success path: extraction, risk, critic, auto-approval, settlement hold, dry run, commit, vendor history update |
| Anomalous amount from a known vendor (`02-...`) | reasoning route | the cross-provider critic and the 0.75 confidence gate, including whether they disagree at all |
| First-seen vendor and human approval tiers (`03-...`) | reasoning route | `interrupt()`/resume, clerk refused above $10,000, controller approves |
| Canary vendor (`06-canary-vendor.png`) | routine model (Groq quota) | the canary auto-trip of the global kill switch |
| Kill switch during the settlement hold | reasoning route | a switch tripped in the 10 to 30 s hold is caught by the fresh re-check before commit |
| Missed heartbeat | reasoning route | the per-thread watchdog trips a stalled run |
| Overdraft caught at dry run in the pipeline (`07-...`) | reasoning route | a human-approved $612,480.00 payment rejected by the ledger, then duplicate idempotency key on retry |
| Vendor trust before and after | reasoning route | the same vendor's risk inputs before and after a settled payment |
| Rate limit through the pipeline (`08-rate-limit-1..4`) | reasoning route | scenario 14's rule reached through real approvals |

## Suggested teaching order (by layer)

1. **Identity:** 01, 04, 03, 02. What an identity is, that it expires, that it is narrow, and what happens without one.
2. **Data:** 05, 06, 07. Is the data what we think it is, who may see it, and what gets stored.
3. **Model:** 08, 09, 10. One door to the models, a spending limit on it, and an evidence bar for prompts.
4. **Policy:** 13, 11, 12, 14. Default deny, then changing policy safely, then rules over time.
5. **Agent runtime:** 15, 16, 17, 18, 19, 21, 20. Untrusted input, the two attacks, money-side validation, then stopping things by hand, automatically, and when the stopper itself is down.
6. **Operations:** 22, 23, 24, 25. Detecting tampering, catching it after the fact, the immutable anchor, and watching it all.

## Which scenarios leave state behind

Every call to `/authorize`, every run and every kill-switch operation appends to the audit log. Those entries are hash-chained and written as WORM objects under COMPLIANCE retention, so **no scenario that touches the policy service, the backend or the control plane can be fully undone**. Beyond those audit entries:

- **Leave real, permanent state:**
  - **05** re-derives `gt_total_amount` (4 values corrected).
  - **06** registers catalog entities (idempotent).
  - **10** adds prompt versions and MLflow runs, and moves the `production` alias.
  - **13, 14, 19, 20, 21, 25** add rows to `policy_decisions`. 14's approvals count against that vendor for 24 h.
  - **16, 17** add runs to the run history.
  - **19, 20, 21** add kill-switch history (every switch is reset at the end).
  - **22, 23** add `audit_log_tamper_detected`/`resolved` entries to the chain permanently.
  - **24** adds a `diagnostic` entry; its first run briefly removed and restored the bucket's default lock rule.
  - **09** leaves its spend in LiteLLM's spend log (the key itself is deleted).
- **Fully self-revert (apart from audit entries):** 01, 02, 03, 04, 07, 08, 11, 12, 15, 18.
