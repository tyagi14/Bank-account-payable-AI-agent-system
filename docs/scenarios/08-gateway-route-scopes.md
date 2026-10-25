# 08. The model gateway: every agent has its own key, and a key reaches only its own models

**What this proves:** agents never hold provider API keys or name provider models; each one calls LiteLLM with its own virtual key, and the gateway refuses any model route outside that key's list.

## Background
LiteLLM exposes three routes (`infra/litellm/config.template.yaml`): `custodian-reasoning` (OpenAI `gpt-5.6-sol`), `custodian-routine` (Groq `openai/gpt-oss-120b`) and `custodian-guardrail` (Groq `openai/gpt-oss-safeguard-20b`). The provider keys are fetched from Infisical at start-up (scenario 03). `infra/scripts/provision-litellm-keys.py` creates one virtual key per agent:

| key alias | routes | daily budget |
|---|---|---|
| `agent-extraction` | routine, guardrail | $2.00 |
| `agent-risk-scoring` | reasoning | $3.00 |
| `agent-approval` | routine, reasoning | $3.00 |
| `prompt-eval` | routine | $5.00 |

The payment agent makes no LLM calls and has no key. `custodian-backend/app/llm.py` sends every call with the calling agent's key and only ever names a route.

## Steps
With the keys from `.env` loaded (`set -a; . ./.env; set +a`), send `Reply with the single word OK.` to:
1. `custodian-routine` with `$LITELLM_KEY_EXTRACTION`
2. `custodian-guardrail` with `$LITELLM_KEY_EXTRACTION`
3. `custodian-reasoning` with `$LITELLM_KEY_RISK`
4. `custodian-reasoning` with `$LITELLM_KEY_EXTRACTION`, a route that key is not allowed to use

```
curl -s http://127.0.0.1:14000/v1/chat/completions -H "Authorization: Bearer $LITELLM_KEY_EXTRACTION" \
  -H 'Content-Type: application/json' \
  -d '{"model":"custodian-routine","messages":[{"role":"user","content":"Reply with the single word OK."}]}'
```

## What you'll see
```
routine:   custodian-routine -> OK | tokens 114
guardrail: custodian-guardrail -> OK | tokens 110
reasoning: ERROR {"message": "litellm.RateLimitError: RateLimitError: OpenAIException - You have no credits remaining. Add credits to continue using the API at https://platform.openai.com/settings/organization/billing/.
LiteLLM: model group 'custodian-reasoning' failed with the error above and no fallback model g...
denied:    ERROR {"message": "The requested model 'custodian-reasoning' is not available for this API key, or the model name is invalid. Check the models available to you and try again.", "type": "key_model_access_denied", "param": "model", "code": "403"}
```

## What this actually teaches
The gateway is where the model inventory, credentials and permissions live, so an agent's reach is set in one place and cannot be widened from agent code: the extraction agent's key was refused the reasoning model with a 403 before any provider was contacted. Step 3 is a real outcome of this build, not a configuration error. The OpenAI account behind the reasoning route had no credits, and the gateway reported it clearly. By design it did **not** fall back to Groq: the critic in the approval step depends on the reasoning route and the routine route being different providers, so a silent cross-provider fallback would quietly remove that independence. Every scenario that needs the reasoning route is blocked until that account is funded (see `docs/scenarios/README.md`).
