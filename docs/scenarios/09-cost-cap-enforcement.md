# 09. Cost caps are enforced by the gateway, not by the agent

**What this proves:** once a virtual key's spend passes its budget, the gateway refuses further calls on that key, whatever the calling code does.

## Background
Each agent's key carries `max_budget` and `budget_duration: 1d` (scenario 08). LiteLLM prices every call from its model price map, adds the cost to the key's spend in its Postgres database, and checks spend against the budget before forwarding the next request. To see the refusal without spending real money, this scenario creates a throwaway key with a budget of $0.0001, which is about two short calls on the routine model, and deletes it at the end.

## Steps
1. Create the key (master key from `.env`):
   `curl -s http://127.0.0.1:14000/key/generate -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H 'Content-Type: application/json' -d '{"key_alias":"scenario-budget","models":["custodian-routine"],"max_budget":0.0001,"budget_duration":"1d"}'`
2. Call `custodian-routine` three times with that key, asking it to "Summarise double-entry bookkeeping in two sentences."
3. Read the key's recorded spend: `curl -s "http://127.0.0.1:14000/key/info?key=$KEY" -H "Authorization: Bearer $LITELLM_MASTER_KEY"`
4. Delete it: `curl -s http://127.0.0.1:14000/key/delete -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H 'Content-Type: application/json' -d '{"key_aliases":["scenario-budget"]}'`

## What you'll see
```
=== call 1
ok, tokens 187
=== call 2
ok, tokens 176
=== call 3
REFUSED 422 Budget has been exceeded! Key=scenario-budget (sk-...J5-w) Current cost: 0.0001448999999999988, Max budget: 0.0001
=== spend recorded by the gateway
spend 7.575e-05 max_budget 0.0001
=== clean up
{"deleted_keys":["scenario-budget"]}
```

## What this actually teaches
A cost cap only counts if the agent cannot get around it, and here the agent never sees a provider key, so the gateway is the only path to the model. Two honest details show up in the real numbers:
- **The cap can overshoot by one call.** The budget is checked before a call, and that call's cost is known only afterwards. Call 2 started at $0.0000758 (under the cap) and finished at $0.000145 (over it). Only call 3 was refused.
- **`/key/info` lags.** Spend is written asynchronously, so it still showed $0.0000758 after the refusal message reported $0.000145.

A real cap should therefore be set below the true limit by at least one maximum-size call. The agents' real daily budgets ($2 to $5) are set with that in mind.
