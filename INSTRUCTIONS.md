# Build Prompt for Claude Code — "Custodian": A Governed Multi-Agent Finance Operations Platform

> This is the original build specification, kept verbatim. Everything that the build changed,
> simplified or could not do is recorded at the end under
> **[Build decisions, deviations and honest gaps](#build-decisions-deviations-and-honest-gaps)**.

Give this entire file to Claude Code as the first message in an empty
repository. It is a complete, self-contained build specification — follow
it top to bottom and the result is one specific system, not "a system like
this." Where a decision is prescribed below (an exact library, an exact
dataset, an exact folder name), that decision was already made through real
trial and error building this exact project once before; don't re-litigate
it from scratch.

---

## 1. What you are building

**Custodian** is a multi-agent AI system that runs part of an enterprise's
finance back-office autonomously: it reads incoming invoices, extracts and
verifies their data, scores them for fraud/anomaly risk, decides whether to
auto-approve or escalate to a human, and executes vendor payments through an
internal ledger — with a complete AI governance system wrapped around every
step that touches money.

**The real need this addresses:** giving an autonomous agent the authority
to approve and move money is where a mistake stops being a bug and becomes a
real financial loss. This project proves an agent fleet can be trusted with
that authority because every governance layer around it does real,
load-bearing work — not because it's dressed up to look that way.

Six governance layers, in full: **Identity, Data, Model, Policy, Agent
Runtime, Operations.** Compliance Governance is explicitly out of scope.

---

## 2. Ground rules — read this section twice

1. **Latest stable versions only.** For every library, image, and API model
   mentioned anywhere below, check the actual current latest stable version
   at build time and use that — do not assume a version number mentioned in
   this document is still current.
2. **Keep it simple. Do not over-engineer.** No abstraction layer that isn't
   earning its keep, no speculative extensibility. Minimal comments — only
   where something is genuinely non-obvious (a hidden constraint, a subtle
   invariant, a workaround for a specific real bug). **No emojis anywhere**
   — not in code, not in logs, not in any doc. When two implementations
   deliver identical functionality, ship the shorter one.
3. **100% local, via Docker Desktop, genuinely production-grade.** Every
   service is a container, brought up with `docker compose`.
   Production-grade means real health checks, real restart policies, real
   per-container resource limits where it matters, and secrets pulled from
   the secrets platform at startup — never sitting in plaintext in a
   compose file, and `.env` itself is gitignored and never committed. The
   only network calls leaving the machine go to the OpenAI API and the Groq
   API.
4. **Nothing is mocked. Nowhere. This is the single most important rule in
   this document, and it governs every layer below, especially Model
   Governance.**
   - No stub function that fakes a success response. No hardcoded
     `if vendor == "X": approve` logic dressed up as an AI decision. No
     invented placeholder data.
   - **Invoice documents** come from two real, freely downloadable public
     invoice-extraction datasets, pulled via Hugging Face `datasets`:
     `naver-clova-ix/cord-v2` (CORD) and `jsdnrs/ICDAR2019-SROIE` (SROIE).
     Both include real ground-truth field annotations, which you also use
     as real evaluation data — do not fabricate a separate eval set.
   - **Vendor master data and historical payment ledger** are seeded from a
     real public government spending dataset: the USAspending.gov bulk
     award API (`https://api.usaspending.gov/api/v2/search/spending_by_award/`)
     — real vendor names, real amounts, real dates.
   - **The payment execution boundary**: this system cannot and should not
     connect to a live bank wire network. Build a real, fully-functioning
     internal ledger microservice instead — genuine double-entry
     bookkeeping, real balance tracking, real validation logic
     (unbalanced-entry detection, insufficient-funds detection, duplicate
     idempotency-key detection, unknown-account detection). This is the
     same pattern real fintech companies use for a sandboxed settlement
     layer before ever going live — describe it exactly that way in the
     docs, not as a shortcut.
   - **The Model Governance promotion gate must be a real, computed
     evaluation.** It runs the eval suite against real held-out SROIE/CORD
     ground truth and computes real accuracy against a real threshold you
     define. Build at least one prompt version that genuinely passes this
     gate and one that genuinely fails and is genuinely blocked from
     promotion — if nothing has ever failed it, the gate isn't real yet,
     fix that before calling this done.
5. Every governance layer must be **independently demonstrable** with a
   real, reproducible scenario — not a description of what it would
   theoretically do. If you cannot make a control fail a real, live test on
   its own, it is not done.
6. **When a real design trade-off forces you to leave something out or
   simplify it, say so explicitly in `INSTRUCTIONS.md` and in the affected
   scenario doc, with the real reason** — a fake, hidden shortcut is far
   worse than an honest, documented gap. Section 4 below already bakes in
   several such decisions (why Landlock and not gVisor, why the MCP-style
   tool-trust proxy is deliberately not built, why SPIRE's per-agent split
   isn't literal) — keep that same honesty for anything you decide during
   the build.

---

## 3. LLM configuration

| Purpose | Provider | Model | Notes |
|---|---|---|---|
| Fraud/risk judgment and any payment decision above a routine-amount threshold | OpenAI API | The current flagship reasoning model in the GPT-5 family — check `developers.openai.com` for the current alias at build time | `OPENAI_API_KEY` from environment, never hardcoded |
| Routine invoice field extraction / OCR post-processing / low-risk triage | Groq API | The current `gpt-oss` open-weight model on Groq (check `console.groq.com/docs/models` for the current model ID) | Fast, cheap, narrow task — this is intentional, not a downgrade |
| Guardrail / content-safety classifier on untrusted invoice content | Groq API | The current OpenAI open-weight safety/guardrail model on Groq (check the same docs page) | Policy-driven — you write the safety policy text it checks against, it's not a fixed category list. Treat occasional tool-call-formatting failures from this specific model as a known, transient characteristic to retry, not a bug to work around structurally. |

All three routed through a single self-hosted **LLM gateway** (LiteLLM) —
no agent code calls a provider SDK directly. This is what makes budget
caps, fallback, and per-agent routing actually enforceable. Define three
named model routes on the gateway (`custodian-reasoning`,
`custodian-routine`, `custodian-guardrail`) mapping to the three rows
above — agent code always requests a route name, never a raw provider model
ID.

Every agent's LLM output is a **typed, schema-validated object with
automatic retry on failure** — use **Instructor** wrapping the gateway
client, never free text parsed by hand.

---

## 4. Repository layout

Build exactly this top-level structure — one folder per real, independently
buildable service, plus shared infra:

```
custodian-backend/          FastAPI + LangGraph agent runtime (the 4 agents live here as graph nodes)
custodian-console/          Next.js frontend
custodian-ledger/           double-entry ledger microservice
custodian-control-plane/    kill switch service
custodian-audit-log/        tamper-proof hash-chained audit log service
custodian-data-loader/      one-time (re-runnable) real-data seeding job
custodian-sandbox-runner/   dispatches sandboxed OCR jobs
custodian-sandbox-ocr/      the actual per-invocation sandboxed OCR image (built separately, not a compose service - see 5)
policies/                   Cedar (+ temporal/) policy source files, the real authorization source of truth
docs/scenarios/             one markdown file per governance scenario (section 7)
docs/sample-invoices/       a generator script producing real rendered PNG test invoices
infra/compose/              docker-compose files, split by governance layer (see below)
infra/scripts/              bootstrap/provisioning shell + Python scripts (see section 6)
infra/policy-service/       the Cedar+temporal-rules HTTP wrapper (Policy Decision Point)
infra/keycloak/, infra/spire/, infra/litellm/, infra/mlflow/, infra/prometheus/, infra/grafana/, infra/minio-init/, infra/postgres-init/
                             per-tool config/provisioning files each of those services needs
INSTRUCTIONS.md              this file
README.md                    section 8
CREDENTIALS.md                a plain listing of every local-dev credential and where it lives (not secret - see ground rule 3)
SECRETS GEN GUIDE.md          the exact openssl/python one-liners used to generate every random secret in .env.example
```

Split `infra/compose/` into **six files**, one per governance layer, each
independently runnable on its own (`docker-compose.base.yml`,
`.identity.yml`, `.data.yml`, `.model.yml`, `.app.yml`,
`.observability.yml`), plus a thin wrapper script
`infra/scripts/compose.sh` that runs `docker compose` with all six
`-f` flags already applied, so day-to-day commands don't repeat them. Every
layer must still work completely standalone — this is Ground Rule 5 applied
to the compose layout itself.

---

## 5. The six governance layers — decisive tool stack

### 5.1 Identity Governance
- **Keycloak** — human identity provider: AP clerks, finance controllers,
  and CFO-level approvers for high-value overrides, with role tied directly
  to an approval-authority tier.
- **SPIFFE/SPIRE** — short-lived cryptographic identity. Register 6 SPIRE
  entries: one per agent (Extraction, Risk-Scoring, Approval,
  Payment-Execution), one for the `custodian-backend` process itself, and
  one test/verification entry — each with a 1-hour X.509-SVID TTL. **Design
  decision, made deliberately up front:** SPIRE attests one identity per
  connecting OS process, and the 4 agents run as function calls inside one
  `custodian-backend` process, not as 4 separate workloads — so only the
  process-level entry (`spiffe://<trust-domain>/service/custodian-backend`)
  is genuinely fetched and enforced. `custodian-backend` must fetch a real
  X.509 SVID from the SPIRE Workload API **at process import time, not
  inside a request handler or startup hook** — a failure to get an identity
  must crash the container before it can ever serve a request falsely
  healthy ("no valid identity, no action"). Expose the fetched SPIFFE ID on
  `GET /health`. Per-agent separation is instead genuinely enforced by two
  other independent layers that don't share this limitation: Cedar policy
  (5.5) and capability manifests (5.5) — splitting into 4 separate
  containers to close the SPIRE gap literally is out of scope; document why
  in the code, don't silently paper over it.
- **Infisical** (self-hosted) — secrets platform, Universal Auth. Every
  credential lives here, including the internal ledger's own API key. The
  Payment-Execution code path authenticates as its own narrow machine
  identity and fetches the ledger credential **fresh immediately before
  each use, never cached beyond its own short TTL, never persisted to
  disk/env** — implement this as a small client module
  (`ledger_client.py`-style) that does the two-step Universal Auth login +
  secret fetch on every call.

### 5.2 Data Governance
- **OpenMetadata** — catalogs every data source (invoice inbox, vendor
  master, payment ledger) with a sensitivity tag
  (`public`/`internal`/`RestrictedFinancial`) via a script run once the
  data-loader has populated real tables.
- **Presidio** (`presidio-analyzer` + `presidio-anonymizer`) — strips
  financial/personal PII from any content before it's persisted anywhere
  durable, including the audit log. The raw text may still be used for the
  actual extraction call (it legitimately needs the real data) — only what
  lands in a durable audit record must be redacted. Fail open on the
  redaction call itself (never block a real pipeline step because a
  best-effort PII scan errored), but always log which entity types were
  found.
- **Great Expectations** — a real checkpoint validating the structural
  shape of every loaded invoice record (non-null required fields, values in
  a plausible range, a regex-valid external key) as part of the
  one-time/re-runnable data-loader job — not a live per-request gate. Ship
  it with its own runnable self-test (a deliberately malformed record that
  must genuinely fail validation, and a well-formed one that must genuinely
  pass) so the gate's realness doesn't depend on ever seeing bad production
  data. Do not block loading on a validation failure — print the real
  failure and let a human decide; this is a visibility control for a batch
  job, not a live hard-stop (the live pipeline's guardrail/policy checks
  are what hard-stop a single bad invoice in real time).
- Access to a given classification level is enforced by the same Cedar
  policy service built in 5.5 — do not stand up a second policy engine.

### 5.3 Model Governance
- **LiteLLM Proxy** (self-hosted) — the single gateway every agent calls
  through. One virtual API key per agent, each scoped to only the model
  routes that agent needs and capped with a real per-day budget enforced
  **before** the call goes out (test this: a call against an
  over-budget/wrong-model key must return a real `403`/`429` from the
  gateway itself, not a client-side check).
- **MLflow Prompt Registry** (self-hosted) — every prompt template is a
  versioned artifact staged via alias (`production`). The real Extraction
  agent must load its actual prompt from
  `prompts:/<registry-name>@production` **at process startup**, falling
  back to a bundled default only if MLflow has no promoted version yet or
  is genuinely unreachable — same fail-open posture as the other
  non-security-critical dependencies above. Refresh is on process restart
  by design, not live-polled, matching the policy-service's own
  explicit-reload pattern below — don't build a background poller for
  this. **Set any MLflow client timeout/retry env vars before importing
  `mlflow`** — the client reads them once at import/first-use, not
  per-call; setting them later has no effect and will silently produce a
  multi-minute hang against an unreachable server instead of a fast
  fail-open.
- **DeepEval** — the real, computed promotion gate from Ground Rule 4. Run
  as a one-shot container/CI job, not a persistent service. It must
  register both a genuinely-passing and a genuinely-failing prompt version
  in MLflow and alias only the passing one to `production`.

### 5.4 Policy Governance
- **`policies/`** — every Cedar rule as a plain-text `.cedar` file, the
  real source of truth, plus `policies/temporal/` for real Dogwood-syntax
  temporal rules (rate/time-window conditions Cedar's stateless model
  can't express) and a `schema.cedarschema.json`. At minimum: no single
  agent auto-approves above a defined dollar threshold; a payment to a
  vendor seen for the first time requires human approval regardless of
  amount; no more than a defined number of approvals to the same vendor
  within a rolling 24-hour window.
- A real validation script (`infra/scripts/validate-cedar-policies.py`)
  that rejects anything overly permissive (no principal/amount/vendor
  constraint at all), fails schema validation, or produces the wrong
  outcome on a real multi-case authorization test matrix — run manually per
  the README, not wired into CI (no `.github/workflows/` in this project;
  say so plainly rather than implying an automated gate that doesn't
  exist).
- **Dogwood's own reference interpreter is built for policy exploration,
  not production authorization** (its own maintainers document this) — do
  not shell out to it live. Instead, write a small, real Python module
  (`temporal.py` inside the policy service) that enforces the `.dw` file's
  documented semantics directly against a real Postgres table of past
  decisions (every `/authorize` call, allow or deny, gets logged there
  first). The `.dw` file stays the authoritative spec; the Python module is
  what actually runs.

### 5.5 Agent Runtime Governance
- **LangGraph** — orchestrates Extraction → Risk-Scoring → Approval →
  [human interrupt] → Payment-Execution as one graph, with real Postgres
  checkpointing (`interrupt()` / `Command(resume=...)` for the
  human-in-the-loop pause, not a hand-rolled polling mechanism).
- **`policy-service`** — a lightweight FastAPI wrapper embedding the real
  Cedar engine (via its Python binding) as a Policy Decision Point, plus
  the temporal module above, plus a live kill-switch state check (5.6). One
  `/authorize` endpoint, default-deny, called before every consequential
  agent action — extraction guardrail decisions don't need it, but
  approval and payment-execution do. Every decision (allow or deny) is
  itself written to the tamper-proof audit log (5.6) and increments a real
  Prometheus counter labeled by action/decision/principal.
- **Guardrail model** (Section 3's guardrail route), called on every piece
  of untrusted content, including the invoice document itself — a
  malicious actor can embed hidden instructions inside an invoice the same
  way indirect prompt injection works through any other untrusted
  document. It must catch both classic prompt-injection phrasing *and*
  business-fraud-pattern phrasing (e.g. "remit future payments to this new
  bank account") — write the policy text it checks against to cover both,
  don't scope it to injection alone.
- **Sandboxed execution for untrusted document parsing** (OCR on incoming
  invoice images): a fresh container per execution (`custodian-sandbox-ocr`,
  built separately — `custodian-sandbox-runner` launches it dynamically by
  name per call, it is not a long-running compose service), `--rm`,
  `--network none`, read-only root filesystem except a scratch dir,
  non-root user, `--cap-drop=ALL`, hard CPU/memory/pid limits, a hard
  execution timeout — **plus** a second, independent, kernel-enforced layer
  inside that container: a real **Landlock** ruleset (via Microsoft's
  open-source Agent Governance Toolkit / `nono-py`), restricting the OCR
  process to only the exact file paths it needs, even ones Docker itself
  would otherwise allow. **Use Landlock, not gVisor, as a starting
  decision, not something to discover the hard way**: gVisor conflicts with
  Docker Desktop's own Nvidia-runtime injection logic, which overwrites
  custom-runtime config on every restart and requires a manual per-machine
  workaround — Landlock is a plain Linux kernel feature (mainline since
  5.13) a process applies to itself, needs no host-level runtime
  registration, and works identically on every machine. Firecracker is
  ruled out for the same reason it always is here: it needs `/dev/kvm`
  exposed through nested virtualization Docker Desktop doesn't guarantee on
  macOS/Windows. Spinning up a sandbox execution is itself a governed tool
  call — goes through `/authorize` and the capability manifest like any
  other action.
- **Do not build a third tool-trust-proxy layer** (an MCP-style
  trust-tier/content-scan gate sitting alongside Cedar and the capability
  manifest at every tool call). It was built once in this project's real
  history and found, after live testing, to be fully redundant with
  Cedar + the capability manifest for its trust-tier half, and narrower
  than the guardrail model for its content-scan half (four fixed regex
  patterns vs. a real classifier). Two independent tool-call checks
  (Cedar + capability manifest) is the deliberate, tested target — not
  three.
- **A2A (Agent-to-Agent protocol) convention, lightweight adoption only**:
  the pipeline's run-state field mirrors `a2a.types.TaskState`'s vocabulary
  (`extracted`, `pending_human`, `approved`, `settled`, etc.), and each
  node hands state to the next via LangGraph's own graph edges, re-running
  the `/authorize` check at every step rather than trusting the previous
  node's result. Do not build a separate A2A server, agent card, or
  cross-process handoff — the four agents are nodes in one process, not
  independent A2A peers, and a full A2A implementation would duplicate what
  Cedar + Dogwood already do for inter-agent trust.
- **Capability manifests** — one small JSON file per agent
  (`{"agent": "...", "trustTier": "...", "allowedActions": [...]}`),
  checked in code as a **second, independent** authorization check
  alongside Cedar — a single Cedar misconfiguration must never alone grant
  a lower-tier agent write access. Only the Payment-Execution agent's
  manifest may ever include the ledger-write action.
- **Vendor Governance, real and closed-loop, not client-supplied**: a
  `vendors` table and a `historical_payments` table live in the ledger
  service. Risk-Scoring calls a real `GET /vendors/lookup` (guarded by a
  separate, narrower `VENDOR_LOOKUP_API_KEY` — read-only, distinct from the
  key that can write ledger entries) to get whether this vendor is known,
  its first-seen date, its award count, its average payment amount, and its
  recent amounts — never accept `vendorFirstSeen`/payment-history fields as
  client input; a self-reported, fraud-relevant flag lets anyone bypass the
  first-seen-vendor rule by just asserting it's false. After a payment
  genuinely **settles** (not before, and not if it's blocked),
  Payment-Execution calls `POST /vendors/record-payment` (guarded by the
  same ledger-write key, since it's a real write tied to a real
  settlement) — this upserts `vendors` and inserts a real
  `historical_payments` row, so the vendor's *next* invoice is scored
  against real accumulated history. Risk-Scoring's prompt must weigh
  amount-pattern consistency explicitly: a payment far above a known
  vendor's historical average is a stronger fraud signal than the same
  amount from a brand-new vendor, because there's a real baseline to
  violate.
- **Dual-agent critic verification** — after Approval reaches a confident
  `auto_approve` decision, a second, independent model call — **the other
  provider**, not just a second prompt on the same model — reviews it
  adversarially with the same evidence and can force human escalation on
  disagreement. This is a defense-in-depth layer for whatever slips past
  everything upstream, not the primary catch — design and test it knowing
  it will rarely actually disagree if the upstream checks are doing their
  job, and that's the correct outcome, not a test failure.
- **Confidence-gated execution** — the approval decision itself carries a
  numeric confidence (via Instructor's schema); below a defined threshold
  (e.g. 0.75), human approval is required regardless of what the decision
  says. This gates the *decision's* confidence specifically, not the
  upstream extraction's confidence — keep those as separate fields, they
  measure different things (an agent can be very confident about a
  decision built on admittedly fuzzy underlying facts).
- **Dry-run before commit** — the ledger service computes the resulting
  balances and full validation outcome (balance check, insufficient-funds
  check, account-existence check) **before** the real double-entry write,
  inside a transaction that always rolls back, sharing the exact same
  validation function the real commit path uses — not a second, looser
  check that could silently drift out of sync. Payment-Execution must
  refuse to proceed to settlement if the dry-run reports invalid.
- **Settlement hold window** — after a successful dry-run, hold for a
  defined number of seconds (configurable via env var, default in the
  10-30s range) before the real commit, then **re-check kill-switch state
  fresh** right before that commit — a trip during the hold must block the
  payment even though every agent already agreed to it. This is the last
  checkpoint before money moves; nothing after it re-checks anything.
- **Self-expiring credentials** — SPIRE identities (5.1) and
  Infisical-brokered credentials (5.1) both carry short TTLs regardless of
  task state, so a stuck or compromised agent loses access on its own
  rather than depending on something else to notice and revoke it. Build
  the identity fetch to **fail closed and crash the process** if it can't
  get a valid credential — never silently continue without one.
- **Watchdog heartbeats** — every agent node emits a heartbeat (thread
  ID + agent name + timestamp) on each step, into a real Postgres table.
  A background loop in `custodian-control-plane` flags a stalled agent
  independently of cost/rate/policy signals. **Design the staleness check
  per logical run (thread), not per individual agent name within a run** —
  checking each agent's own last-seen timestamp independently produces
  false positives once a run legitimately moves on to its next agent and
  the previous agent's heartbeat naturally goes quiet; group by thread and
  compare against the most recent heartbeat across the whole run.
- **Auto kill-switch triggers**, tripped by `custodian-control-plane`: a
  canary vendor/account no legitimate flow should ever touch; repeated
  policy denials from the same agent within a rolling window; a missed
  heartbeat (per the correct per-thread logic above). Build **graduated
  scopes** — pause one agent → halt one session/thread → freeze one tool
  fleet-wide → full global stop — each independently settable and
  resettable via a real API, each trip and reset itself written to the
  audit log.

### 5.6 Operations Governance
- **OpenTelemetry**, GenAI semantic conventions
  (`gen_ai.system`, `gen_ai.request.model`, `gen_ai.agent.name`,
  `gen_ai.usage.input_tokens`/`output_tokens`, `gen_ai.response.model`) —
  wrap every real LLM call in a span with these exact attribute names (a
  real open standard, not project-invented naming), reading real token
  usage off the actual provider response, never estimated.
- **Langfuse** (self-hosted) — export spans via OTLP/HTTP directly to it.
  Expect (and document, don't hide) that a self-hosted instance's cost
  calculator may not price your internal model-route names against its
  pricing table even though token counts are captured correctly — that's a
  real, acceptable gap for a local build, not something to silently work
  around.
- **Prometheus + Grafana** — real custom counters (at minimum,
  `policy_decisions_total` labeled by action/decision/principal, from
  5.5's policy service) scraped on a schedule, at least one real
  provisioned Grafana dashboard reading from them. A metric is only worth
  building if you can make its number move by causing a real event and
  watching it increment by exactly that much.
- **Cost governance**: enforced via LiteLLM's per-key budget caps — a
  ceiling before the call goes out, not a number observed after.
- **`custodian-control-plane`** — the kill switch service, independent of
  the agent runtime process itself, so a malfunctioning agent can never be
  the one deciding whether it gets stopped. Every trip and reset is itself
  written to the audit log.
- **Tamper-proof audit logging (`custodian-audit-log`)** — every
  governance-relevant event (extraction, risk score, policy decision,
  human approval/denial, ledger execution, vendor-history update,
  kill-switch trip/reset) is a JSON entry embedding the SHA-256 hash of the
  previous entry (a real hash chain, `prev_hash`/`entry_hash`), written
  first to **MinIO** with **Object Lock in COMPLIANCE mode** (genuine WORM
  storage — not even the root credential can delete or shorten retention
  on a locked version) and mirrored to Postgres for fast queries. A
  `/verify` endpoint does a **two-stage check**: recompute every hash and
  `prev_hash` link from the Postgres mirror, *then* cross-check each
  entry's real MinIO object content byte-for-byte against what the chain
  says it should be — existence of an object at a key is not proof; a
  locked object's *specific version* can never be altered, but a plain
  write can still stack a new version on top of the same key that a naive
  existence check would miss, so the verify step must fetch and compare
  actual content, not just check that a key resolves.
- **Continuous integrity watchdog** — `/verify` alone is only a
  point-in-time check: a tamper reverted before anyone happens to call it
  leaves no trace. Run a background thread in `custodian-audit-log`
  (interval configurable via env var, default ~30s) that calls the same
  real check automatically, and the moment it finds a **new** break, writes
  that finding as its own normal entry into the same hash chain
  (`audit_log_tamper_detected`), with a matching
  `audit_log_tamper_resolved` entry once it clears — routed through the
  exact same append path as every other event, not a separate, weaker one.
  Track "currently broken" state in a plain in-process variable only to
  avoid re-logging every tick; the actual durable memory is the chain
  entries themselves, not that variable. This is what makes even a
  tamper-then-perfectly-revert-before-anyone-checks permanently provable —
  reverting the tampered *data* can't erase the *fact it was caught*
  without also breaking the hash chain, which is exactly what `/verify`
  next detects.

---

## 6. The application services

- **`custodian-backend`** — Python, FastAPI, hosting the LangGraph agent
  graph. Async throughout, Pydantic v2 on every request/response boundary.
  REST + WebSocket API so the frontend can watch a run live, step by step.
  Fetches its own SPIFFE identity at import time (5.1) before the FastAPI
  app object exists.
- **`custodian-console`** — a Next.js dashboard:
  - **Live invoice pipeline view** — watch an invoice flow through each
    agent step in real time, with the policy decision at each point and
    why.
  - **Approval queue** — paused runs awaiting human approval; log in via
    Keycloak to approve/deny.
  - **Audit log viewer** — browse the hash-chained log with a "verify
    chain integrity" button that calls the real `/verify` endpoint live.
  - **Ledger & cost dashboard** — live internal ledger balances/transactions,
    plus current spend vs. budget cap per agent, embedding or linking
    Grafana/Langfuse.
  - **Kill switch button** — manual trip for the control-plane service,
    with confirmation, plus a visible log of automatic trips.
  - **Policy explorer** — the current Cedar/temporal policies in
    human-readable form.
  - **A submit page** supporting both pasted OCR text (fast, skips OCR) and
    a real image upload (goes through the real sandboxed OCR path).
- **`custodian-ledger`** — the real internal ledger microservice from
  Ground Rule 4: double-entry bookkeeping, real balance tracking, real
  validation (5.5's dry-run shares its validation code with the real
  commit), plus the `vendors`/`historical_payments` tables and endpoints
  from 5.5.
- **`custodian-control-plane`** — kill switch + heartbeat watchdog, 5.5/5.6.
- **`custodian-audit-log`** — the hash-chained log + continuous watchdog,
  5.6.
- **`custodian-sandbox-runner`** — accepts an OCR request, launches a
  fresh `custodian-sandbox-ocr` container per call with the Landlock/Docker
  restrictions from 5.5, returns the extracted text.
- **`custodian-data-loader`** — a one-time (and safely re-runnable —
  loading twice must not duplicate rows) seeding tool pulling the real
  SROIE/CORD invoice data and the real USAspending vendor/award slice, then
  running the Great Expectations checkpoint against what it loaded (5.2).

---

## 7. Infra bootstrap scripts required

Build these as plain `#!/bin/sh` scripts under `infra/scripts/` (POSIX, so
Git Bash on Windows works identically to Linux/macOS) — the first-run
sequence in the README (section 8) is built entirely out of calling these
in order:

- **`compose.sh`** — thin wrapper applying all six `-f` compose-file flags.
- **`render-keycloak-realm.sh`** — fills a Keycloak realm template with real
  values from `.env` before Keycloak starts.
- **`register-spire-entries.sh`** — registers the 6 SPIRE entries from 5.1.
- **`setup-spire.sh`** — generates a fresh SPIRE agent join token (single-use
  by design) and writes it to `.env`; must be re-runnable any time the
  agent's persisted identity is lost or expired (a fresh data volume, or an
  SVID that aged past its renewal window with the agent unable to reach the
  server) — this is a real, expected operational scenario, not just a
  first-run step.
- **`bootstrap-infisical.sh`** — creates the vault's instance admin account,
  exchanging its one-shot bootstrap token for a real login session before
  finishing (the bootstrap token itself expires within seconds
  server-side, by design).
- **`provision-infisical-identities.py`** — creates the Infisical project
  and one machine identity per service that needs to broker a secret,
  printing the values that must be pasted into `.env`.
- **`provision-litellm-keys.py`** — creates one scoped virtual key per
  agent with its own model allowlist and budget cap, printing the values
  that must be pasted into `.env`.
- **`register-openmetadata-catalog.py`** — tags the newly-loaded tables as
  sensitive in the OpenMetadata catalog.
- **`validate-cedar-policies.py`** — the real policy validator from 5.4.

`.env.example` must ship with a real, working random value already filled
in for every **local-only** secret (this is a teaching/demo repo — reusing
baked-in local values is fine, nothing here is reachable from outside the
machine), with only two lines requiring a real value from the user
(`OPENAI_API_KEY`, `GROQ_API_KEY`), and every field a bootstrap script fills
in later marked with a clear `# [AUTO-FILLED] by <script>` comment and left
blank. `SECRETS GEN GUIDE.md` documents the exact `openssl`/equivalent
one-liner used to generate each baked-in value, so they're regenerable, not
mysterious.

---

## 8. Known operational pitfalls — design around these from day one

These are real, previously-encountered failure modes. Building around them
up front is cheaper than rediscovering them:

- **Pick host-side ports deliberately, not by habit.** Port 8080 in
  particular is one of the most commonly-already-claimed ports on any real
  dev machine (other local tooling, other projects, IDE proxies) — never
  publish a service on it. This only affects the host-side mapping; a
  service's *internal* container port and its container-to-container URLs
  are unaffected by whatever host port you choose.
- **A stopped/idle Docker Desktop VM on Windows can wedge WSL2's synthetic
  mount tree at the drive-root level**, breaking every bind mount under
  that drive at once (not just one folder), surviving a plain restart or
  even `--force-recreate`. Document the real fix in the README's
  troubleshooting section (`wsl --shutdown`, reopen Docker Desktop, re-run
  `compose.sh up -d`) rather than treating it as unexplained flakiness.
- **After a WSL2 restart, a container can report `healthy` while being
  genuinely unreachable from the host** — its healthcheck runs inside its
  own network namespace and stays green even if Docker Desktop's host-side
  port forwarding didn't come back. `--force-recreate` on the affected
  service (or all of them) rebinds the port; document this too.
- **A Node/Prisma-based service (Langfuse's web/worker here) holds a
  persistent DB connection pool that does not survive Postgres being
  recreated** — it needs an explicit `--force-recreate`, unlike a Python
  service that opens a fresh connection per request and recovers on its
  own.
- **A stale/expired SPIRE agent identity plus an already-consumed join
  token cannot self-heal** — the agent will crash-loop indefinitely on
  `join token does not exist or has already been used` until a human runs
  `setup-spire.sh` again for a fresh token. This is correct, intended
  fail-closed behavior (5.1/5.5's self-expiring-credentials requirement),
  not a bug to route around — document it as the expected recovery
  procedure.
- **When overriding a container's default command via
  `docker compose run <service> <cmd>`, check whether the image sets a
  hardcoded `ENTRYPOINT`** (e.g. `ENTRYPOINT ["python", "main.py"]`) — if
  it does, your override becomes extra arguments appended after that
  entrypoint, not a replacement of it, and silently runs the default flow
  instead of what you intended. Use `--entrypoint` explicitly when you need
  to run something else inside that image.

---

## 9. `README.md` requirements (root, beginner-usable)

Must include, in this order:
1. **Prerequisites** — Docker Desktop version, realistic minimum RAM/CPU
   (this stack is heavy — OpenMetadata, Langfuse, and Keycloak all running
   together — say so plainly, and give the real measured steady-state
   figure alongside the recommended ceiling).
2. **Getting the two API keys** — where to get an OpenAI API key and a Groq
   API key, and exactly which `.env` variables they go in.
3. **First-run sequence** — the exact commands, in order, calling the
   scripts from section 7, explaining what each command actually does and
   what to wait for before moving on (don't just list commands — say which
   ones must fully finish, and how to check, before the next one is safe to
   run).
4. **A complete service table** — every running service, its local URL,
   and the username/password the setup itself creates (Keycloak admin
   console, Grafana, Langfuse, MinIO console, MLflow UI, the Custodian
   Console itself, everything reachable in a browser). Mark these clearly
   as local-development-only credentials.
5. **A "confirm everything is up" step** — a real, runnable command that
   distinguishes a genuinely healthy stack from a partially-started one,
   calling out which one or two services are expected to show `Up` without
   `healthy` (no healthcheck defined) so that's not mistaken for a
   problem — plus a first-run checklist: confirm the Keycloak realm is
   seeded, confirm OpenMetadata has the real catalog entries, confirm the
   Cedar policies validate, confirm LiteLLM can reach both OpenAI and Groq,
   confirm the data loader completed and which real record counts to
   expect.
6. **A troubleshooting section** built directly from section 8's real
   pitfalls, each with the exact symptom (real error text) and the exact
   fix — not generic advice.

---

## 10. `docs/scenarios/*.md` — one file per scenario, every file follows this template

**What this proves** (one or two sentences) · **Background** (the relevant
code path, in enough detail that the steps make sense) · **Steps** (exact
commands, numbered) · **What you'll see** (the real output — if you
genuinely ran it, paste the real result, not an idealized one) · **What
this actually teaches** (the governance principle, including any honest
limitation the test itself revealed).

Cover a genuine success path end to end, and then every governance
capability described in section 5, including the ones that only matter
under attack or failure. At minimum, across the full scenario set: identity
and credential brokering, self-expiring credentials measured live, PII
redaction, the real eval-gate pass and its real failure case, a policy
change accepted and one rejected, a real temporal/rate-limit rule tripped,
prompt injection through a poisoned document, sandbox isolation, cost-cap
enforcement, the kill switch (manual, at least one automatic trigger, and
one tripped specifically during the settlement hold window), audit-log
tamper resistance *and* the continuous-watchdog case specifically (a tamper
reverted before anyone checks, still caught), real object-lock immutability
proven against root credentials, the dual-agent critic and confidence gate
(including honestly documenting real attempts that didn't produce a
disagreement/low-confidence result, if that's what actually happens — that
outcome is itself informative), dry-run-before-commit catching a real bad
transaction, continuous vendor trust scoring shown as a real before/after
on the same vendor, the data-quality gate's own self-test plus a real bad
value already present in the pulled dataset, and both observability
surfaces (tracing and metrics) with a real "make a number move on purpose"
step.

Every layer needs at least one scenario that shows something correctly
**denied or blocked**, not only success paths — a governance control that's
never been seen saying no isn't proven to work. Use real data and real
triggers throughout; if an attempt to provoke a failure doesn't actually
produce one, that's a real, reportable finding — document what you tried
and why it didn't trigger, rather than discarding the attempt or
fabricating a version that "worked." Number the files sequentially. Add a
`docs/scenarios/README.md` indexing every scenario in a table (number,
title, one-line "what it proves," governance layer), plus a suggested
teaching order grouped by layer rather than by number, and a closing note
listing exactly which scenario numbers leave real, permanent state behind
versus which ones fully self-revert.

---

## Build decisions, deviations and honest gaps

Recorded during the build (October 2026). Each item names the real reason.

### Versions chosen (checked at build time)
| Component | Version | Note |
|---|---|---|
| Python base image | 3.14.9-slim | 3.15 had been out three weeks; spaCy/onnx/grpc wheels were not all available for it yet. 3.14 had wheels for every dependency. |
| OpenAI reasoning route | `gpt-5.6-sol` | Newest GPT-5-family flagship listed on developers.openai.com. The GPT-6 family is newer, but the spec asks for GPT-5; change `OPENAI_REASONING_MODEL` to move. |
| Groq routine route | `openai/gpt-oss-120b` | Production model on Groq. |
| Groq guardrail route | `openai/gpt-oss-safeguard-20b` | Listed by Groq as a **preview** model (may be withdrawn at short notice). The gateway falls back to the routine Groq model with the same policy prompt if it disappears. |
| `openai` Python SDK | 3.3.0 (not 3.37.0) | The latest Instructor (1.17.0) pins `jiter<0.15`; every openai release from 3.3.1 on needs `jiter>=0.16`. 3.3.0 is the newest that resolves with the latest Instructor. |
| MinIO | `pgsty/minio:RELEASE.2026-08-04T00-00-00Z` | Upstream MinIO stopped publishing images in late 2025; this is a maintained build of the same AGPL source with versioned tags. |
| Elasticsearch (for OpenMetadata) | 9.3.8 | OpenMetadata 2.0's own compose is tested against 9.3.x; 9.5.x is newer but not what OpenMetadata ships with. |
| ClickHouse (for Langfuse) | 25.12.11.4 | The line Langfuse's reference compose pins; 26.x is newer but untested by Langfuse. |

### Identity
- **Infisical custom project roles are Enterprise-only.** Per-secret narrowing therefore uses one Infisical project per secret scope (`custodian-ledger-write`, `custodian-vendor-lookup`, `custodian-llm-providers`); each machine identity is a read-only viewer of only the projects it needs. Verified live: the vendor-lookup identity gets `403 You are not a member of this project` on the ledger key.
- **The bootstrap token did not expire within seconds on Infisical v0.167.2.** Decoding it showed a 90-day expiry. `bootstrap-infisical.sh` still exchanges it for a Universal Auth credential, proves that with a real login, and then **revokes** the bootstrap token itself, so it is genuinely one-shot regardless of the server's TTL.
- **Infrastructure secrets come from `.env`, application secrets from Infisical.** Postgres/MinIO/Keycloak passwords and Infisical's own encryption key cannot live in Infisical (they are needed to start it), so they are interpolated from the gitignored `.env`. The ledger API key, vendor-lookup key and both provider API keys live only in Infisical: the ledger service and the LiteLLM entrypoint fetch them at startup; the backend fetches the ledger/lookup keys fresh on every call.
- **SPIRE workload attestation uses the docker attestor** (container labels), which needs the agent to run with `pid: host` and the Docker socket. Only `spire-agent` and `custodian-sandbox-runner` hold the Docker socket.
- The backend's SVID gates process start-up and every consequential action (an expired SVID kills the process), but it is **not** used for mTLS between services; service-to-service calls are on the private compose network.
- The four per-agent SPIRE entries are registered but cannot be attested separately (see 5.1). Per-agent separation is enforced by Cedar and the capability manifests.
- `setup-spire.sh` deletes the previous `node/local` alias entry and evicts the previously attested agent before issuing a new join token. Before that fix, every recovery left a stale alias entry and agent record pointing at a consumed token.
- Submitting a run (`POST /runs`, `POST /runs/image`) is not authenticated; only the human decision and kill-switch operations require a Keycloak token. Submission is reachable only from localhost, and every submitted run still passes every policy check.

### Data
- `load_dataset("naver-clova-ix/cord-v2", split="test")` still builds every split, and generating CORD's 800-image train split was killed for memory next to the rest of the stack. The loader reads the needed split's own parquet file instead (`validation` and `test`, 200 receipts). SROIE is loaded in full (626 train + 361 test).
- CORD masks store identity, so CORD receipts have no vendor/date ground truth; they are evaluated on totals only.
- CORD totals are Indonesian rupiah. The ledger has a single currency unit and does **no FX conversion**, so a CORD receipt submitted to the pipeline is treated as that many dollars and escalates as high value. Demos use SROIE receipts and the generated sample invoices.
- Presidio uses the small spaCy model (`en_core_web_sm`) to keep the backend image and memory reasonable; pattern-based recognizers (cards, IBANs, phones, emails) are unaffected, person-name recall is lower than with `en_core_web_lg`.
- Graph checkpoints are durable storage, so they never hold the raw OCR text or image: raw content stays in process memory only and is gone after a restart (a run interrupted before extraction fails cleanly instead). Extracted business fields (vendor, totals) are kept.
- OpenMetadata runs without its Airflow ingestion container; the catalog is populated through the OpenMetadata REST API by `register-openmetadata-catalog.py`, with classifications read from `policies/entities.json` (the same file Cedar reads).
- The data loader writes the opening cash balance directly into the ledger database as a seed entry (balanced by construction, idempotent on its key) rather than through the ledger API.
- The Great Expectations checkpoint reports and logs; it does not stop the load. On the real data it fails with 20 real defects (one 12-digit SROIE key `X510056849111`, 8 receipts with no ground-truth total, 11 totals that do not parse). Those records stay queryable and are excluded from the evaluation set by its own `IS NOT NULL` filter.
- USAspending is live data: a re-run on a later day added one historical payment the earlier run had not seen (1001 rows from 1000 fetched awards). Idempotency is per award key, so nothing is duplicated, but the set can grow.
- Presidio with `en_core_web_sm` makes visible mistakes on invoice text: `MOBILITY` in a vendor name is tagged `PERSON`, and a bank account number is tagged `PHONE_NUMBER` (still removed, under the wrong label). Redaction errs toward over-removal.
- The amount parser originally failed on rupiah totals written `Rp.118.000`, and parsed `Rp. 91,000` as 0.91, a plausible value no expectation flagged. Fixed. The loader now re-derives every parsed total on each run (`reparse_totals`), so parser fixes reach rows loaded earlier. The prompt-gate run recorded in scenario 10 predates the fix, so one CORD receipt in its held-out set was scored against the wrong total.
- The prompt-injection sample originally printed its injected text in light grey; tesseract dropped it, so the guardrail never saw it (scenario 16). The sample now uses darker grey that OCR reads.

### Model
- Only the extraction prompt has labelled ground truth, so only it is gated. The guardrail, risk, approval and critic prompts are registered in MLflow and aliased `production` directly by the eval job, with no accuracy gate.
- The LiteLLM gateway has one cross-route fallback: `custodian-guardrail` falls back to `custodian-routine` (both Groq). There is deliberately no fallback across providers, because the critic's independence depends on the providers staying distinct.
- The Payment-Execution agent makes no LLM calls and therefore has no LiteLLM key.
- MLflow 3.17's server-side job execution spawns extra worker processes and was OOM-killed at 768 MB; it is disabled (`MLFLOW_SERVER_ENABLE_JOB_EXECUTION=false`), and the server runs with one worker.
- **Provider tier limits shaped the evaluation.** Groq's on-demand tier allows 8,000 tokens/minute and 200,000 tokens/day on `gpt-oss-120b`. One 60-receipt gate run (two candidates) uses most of a day's budget, so the gate runs with concurrency 2 and the LLM wrapper honours Groq's `try again in Ns` hint for waits up to 60 s. Longer waits (the daily cap) fail fast instead of blocking a pipeline step.
- **The minimal prompt fails for a real reason.** Without instructions to fill the schema, `gpt-oss-120b` often answers in prose; Groq rejects that with `tool_use_failed: Tool choice is required, but model did not call a tool`. The wrapper retries that error up to three times (Instructor wraps the provider's 400, so it is classified by content, not exception type); what still fails scores zero.
- The OpenAI account used during the build had no credits (`You have no credits remaining`), which blocks the reasoning route and therefore risk scoring, approval and the critic. Scenarios that need those steps are marked as not yet run in `docs/scenarios/README.md`.
- LiteLLM checks a key's budget before each call, so a key can overshoot its budget by one call; `/key/info` spend is written asynchronously and can lag the figure in the refusal message.
- The guardrail's quoted `evidence` is model output and is close to, not always exactly, the offending text (one run quoted "escape" for "escalate").

### Policy
- Dollar thresholds live only in the `.cedar` files and the rate limit only in the `.dw` file; `temporal.py` reads its window and limit from the `.dw` text and refuses to start if the file has any other shape. The decision-confidence threshold exists twice on purpose: the backend gate (`DECISION_CONFIDENCE_MIN`) and Cedar's `decisionConfidenceBp >= 7500` as defense in depth. Keep them equal.
- The `.dw` file follows the syntax of Dogwood's documented examples but was **not machine-validated with the Dogwood CLI** (it needs a Rust toolchain, which the build machine did not have).
- The temporal rule counts allowed approval decisions under a per-vendor Postgres advisory lock, so concurrent approvals cannot all observe "under the limit" (the concurrency trap Dogwood's authors describe for response-counted rules).
- The permissiveness lint used by `validate-cedar-policies.py` also runs on `/reload`, so the live policy service refuses an overly permissive policy set and keeps serving the last good one.
- There is no CI in this project; the validator is run by hand.
- `policy_decisions` stores each decision's per-check verdicts (`checks`: kill_switch / cedar / temporal). The repeated-denial trigger counts only denials where Cedar or the temporal rule refused. Before this, a control-plane outage produced fail-closed denials that, once the control plane was back, tripped the agent that had merely been waiting.

### Agent runtime
- The repeated-denial kill-switch trigger ignores `AutoApproveInvoice` denials: those are the normal "send it to a human" signal (every first-seen vendor produces one), not agent misbehaviour.
- The audit log's write order is WORM object first, then Postgres. If the Postgres insert fails after the object was written, the next append reuses that sequence number and stacks a second version on the key, which `/verify` will report. That is the conservative outcome (a visible finding, not a silent gap).
- The audit-log append endpoint is not authenticated; it is reachable only on the private compose network (the service publishes no host port). Appends can only add entries, never change history.
- **MinIO root could remove the bucket's default object-lock rule** (verified live in scenario 24): existing locked versions survived every attempt, but new objects would have been written unlocked. The audit log now sets COMPLIANCE retention on every object it writes, and `/verify` checks each entry's retention mode, so the guarantee no longer depends on bucket configuration.
- **The integrity watchdog polls every 30 s**, so a Postgres-side edit reverted within one interval is not caught (scenario 23, part B). The WORM copy is never affected; the exposure is privileged write access to `audit_entries`, which this build does not restrict beyond role separation.
- **Audit and decision can disagree in one direction.** policy-service waits 5 s for the audit append. If the append lands after that, the caller gets `deny` ("audit log unavailable; an unaudited allow is not permitted") while the audit chain records the original `allow`. The reverse (an allow returned without a confirmed audit entry) cannot happen. Observed live while MinIO was CPU-starved (15 s per request); `policy_decisions` holds the effective decision.
- A2A: the run state mirrors the A2A `TaskState` vocabulary (`submitted`, `working`, `input-required`, `completed`, `failed`, `rejected`) alongside a pipeline `stage` field (`extracted`, `scored`, `pending_human`, `approved`, `settled`, ...). The SDK itself is not imported: a2a-sdk 1.x is protobuf-based and pulls in the Google API client stack for one enum.

### Operations
- LiteLLM's Prometheus metrics are an Enterprise feature, so the gateway is not scraped; spend per key is read from LiteLLM's `/key/info` and shown in the console.
- Resource reality on the build machine: Docker Desktop had an 8 GB VM shared with another project's containers. With everything running, the VM thrashed (Langfuse never became healthy, Docker CLI calls took minutes). After the other project was removed, the full stack measured about 5.9 GB. See the README's prerequisites for the measured figures and recommended allocation.
- **ClickHouse's self-monitoring is switched off** (`infra/clickhouse/*.xml`): its `trace_log`, `text_log`, `metric_log` and query profilers kept it at about 2.3 cores while idle, which starved MinIO to 15 s per request. With them off it idles at about 4% CPU. Langfuse does not read those tables.
- Langfuse 4.69 runs in v4 "events only" mode: the legacy `/api/public/traces` and `/observations` read endpoints are disabled. Traces are viewed in the Langfuse UI, or queried in ClickHouse (`events_core`).
- FastAPI 0.162 emits OpenTelemetry spans natively for every request and its internal phases. The backend's sampler drops GET requests and `fastapi.*` internals, which were more than 99% of exported spans (health checks and console polling), and keeps POSTs and every agent and LLM span.
- Langfuse needs `HOSTNAME=0.0.0.0` (both web and worker otherwise bind only to the container IP, so a localhost health check never passes) and langfuse-web needs `NODE_OPTIONS=--max-old-space-size=1024`: V8 derived a 560 MB heap from a 1 GB container limit and crashed with `JavaScript heap out of memory` at startup.
- Prometheus counters live in each service process and restart from zero when a container is recreated; the dashboard uses `increase()`/`rate()`, which handle resets.
- Helper scripts beyond those the spec lists, used by the README and the scenarios: `call.sh` (reach unpublished services), `token.sh` (Keycloak operator tokens), `infisical-read.py` (read a secret as a given machine identity), `run-invoice.py` (submit and follow a run), `check-stack.py` (the README's confirm-everything-up check).
- The README's first-run sequence is the order the stack was brought up in during the build; it was not replayed from an empty machine after the final changes.
- Scenarios that need the OpenAI reasoning route (the end-to-end success path, the critic and confidence gate, human approval tiers, kill switch during the settlement hold, missed heartbeat, canary vendor, in-pipeline overdraft and duplicate key, vendor trust before/after) were not run, because the account had no credits; `docs/scenarios/README.md` lists them as not yet run instead of shipping them without real output.
