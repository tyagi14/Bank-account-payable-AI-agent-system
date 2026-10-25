# 25. Observability: move a governance metric on purpose, and trace an agent's model calls

**What this proves:** governance decisions show up in Prometheus and the provisioned Grafana dashboard within one scrape, and every LLM call an agent makes is exported as an OpenTelemetry GenAI span to Langfuse, with the agent, route and token usage.

## Background
- **Metrics:**
  - The policy service exports `policy_decisions_total{action, decision, principal}`.
  - The audit log exports `audit_entries_appended_total` and `audit_chain_intact`.
  - The control plane, ledger and sandbox runner export their own counters.
  - Prometheus scrapes all five every 10 s (`infra/prometheus/prometheus.yml`). Grafana has the dashboard "Custodian Governance" provisioned from `infra/grafana/dashboards/custodian-governance.json`, with eight panels.
- **Traces:** `custodian-backend/app/llm.py` wraps every model call in a span named `chat <route>` with `gen_ai.operation.name`, `gen_ai.system` (openai or groq), `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.agent.name`, `gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens`. `app/telemetry.py` exports spans over OTLP/HTTP to Langfuse's `/api/public/otel/v1/traces`.

## Steps
1. Read the counter for denied `ReadData` requests:
   `curl -s http://127.0.0.1:19090/api/v1/query --data-urlencode 'query=sum(policy_decisions_total{action="ReadData",decision="deny"}) or vector(0)'`
2. Make three requests that will be denied (the approval agent reading `journal_entries`, which is above its clearance):
   `infra/scripts/call.sh policy-service POST /authorize '{"principal":{"type":"Agent","id":"approval"},"action":"ReadData","resource":{"type":"DataAsset","id":"journal_entries"},"context":{}}'`
3. Wait one scrape interval and read the counter again. Watch the "Denials by principal" panel at http://localhost:13002.
4. Check the scrape targets: `curl -s http://127.0.0.1:19090/api/v1/targets`
5. Run an invoice (scenario 16), then find its model call in Langfuse at http://localhost:13001, or directly in Langfuse's ClickHouse store:
   `docker exec custodian-clickhouse-1 clickhouse-client -q "SELECT start_time, name, provided_model_name, usage_details, arrayFilter(x -> x.1 LIKE '%agent%', arrayZip(metadata_names, metadata_values)) FROM events_core WHERE name LIKE 'chat %' ORDER BY start_time DESC LIMIT 5"`

## What you'll see
Steps 1 to 3:
```
before: 0
  "decision": "deny",
  "decision": "deny",
  "decision": "deny",
after one scrape interval: 3
```
Step 4:
```
audit-log                    up
control-plane                up
ledger                       up
policy-service               up
sandbox-runner               up
```
`audit_chain_intact` reads `1`. The dashboard's panels are: Policy decisions (total, by action/decision), Policy decisions per minute, Denials by principal, Kill-switch trips by trigger, Audit chain intact, Audit entries appended by type, Ledger entry attempts, Sandboxed OCR runs.

Step 5:
```
2026-10-24 18:52:34.156000  chat custodian-guardrail  custodian-guardrail  {'input':680,'output':226,'total':906}  [('attributes.gen_ai.agent.name','extraction')]
2026-10-24 18:52:43.186000  chat custodian-guardrail  custodian-guardrail  {'input':679,'output':202,'total':881}  [('attributes.gen_ai.agent.name','extraction')]
```
Langfuse recognises these as `GENERATION` observations and prices them from the token counts.

## Three things the real run turned up
1. **The traces were 99% noise.** FastAPI 0.162 emits OpenTelemetry spans natively once a tracer provider exists: one per request plus three internal spans per request. Before filtering, the store held 4,913 events, of which 4 were LLM calls; 762 were Docker health checks and 463 the console polling a run. The backend now samples out GET requests and `fastapi.*` internal spans (`DropNoise` in `app/telemetry.py`). That first needed a fix of its own: the route name is only set after routing, so filtering on span names like `GET /health` silently matched nothing, and the filter had to use the request method present when the span starts.
2. **Langfuse 4.69 runs in "events only" mode.** Its legacy read API (`/api/public/traces`, `/observations`) answers `This endpoint is not available on deployments running in Langfuse v4 events_only mode`, so traces are read in the UI or in ClickHouse, as above.
3. **Counters reset with the process.** Rebuilding the policy service during this session reset `policy_decisions_total` to zero. The dashboard uses `increase()` and `rate()`, which handle resets, but raw counter values are not a durable history. `policy_decisions` in Postgres and the audit chain are.

## What this actually teaches
Metrics answer "how often, and is that changing?"; traces answer "what exactly happened on this run?". You need both, and both have to be checked for signal. A tracing pipeline that exports everything by default can bury the 4 spans that matter under 4,909 that do not. Honest limits:
- **The gateway is not scraped.** LiteLLM's Prometheus metrics are an Enterprise feature, so per-key spend is read from `/key/info` (scenario 09) and shown in the console.
- **Agent traces are short so far.** Only extraction and guardrail calls have produced traces, because the reasoning route is unavailable (scenario 08).
