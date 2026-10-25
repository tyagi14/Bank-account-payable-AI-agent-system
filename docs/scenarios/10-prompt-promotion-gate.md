# 10. The prompt promotion gate: one version passes, one is blocked, both on real ground truth

**What this proves:** an extraction prompt reaches production only if it beats an accuracy threshold on held-out, human-labelled receipts, and a version that does not is refused promotion.

## Background
Prompts live in the MLflow prompt registry. The backend loads each one at start-up from `prompts:/<name>@production`, falling back to the copy bundled in the image if MLflow is unreachable, and reports which it used on `/health`. The promotion job (`custodian-backend/eval/promote.py`, image `custodian/prompt-eval:local`):

1. Registers each candidate extraction prompt as a new version: `extraction_minimal.txt` ("Read this receipt and return the vendor, the date and the total amount.") and `extraction_structured.txt` (field-by-field instructions and normalisation rules).
2. Runs it through the gateway with the `prompt-eval` key against 60 held-out receipts: 40 SROIE test receipts with vendor/date/total ground truth and 20 CORD test receipts with totals only.
3. Scores each receipt with a DeepEval `BaseMetric` (`FieldAccuracy`: the fraction of ground-truth fields extracted correctly; a failed extraction scores zero, it is not skipped).
4. Tags the version with its accuracy, logs an MLflow run, and moves the `production` alias only to a passing version (threshold `EVAL_ACCURACY_THRESHOLD=0.80`).

## Steps
1. `infra/scripts/compose.sh --profile jobs run --rm --build prompt-eval`
2. `curl -s http://127.0.0.1:18000/health` after restarting the backend (`infra/scripts/compose.sh up -d --wait custodian-backend`)
3. Open MLflow at http://localhost:15000 (experiment `custodian-prompt-eval`, prompt `custodian-extraction`) to see both versions with their tags.

## What you'll see
Step 1 (trimmed to the gate's own lines):
```
held-out set: 60 receipts from the SROIE/CORD test splits
registered custodian-extraction v4 (minimal); extracting 60 held-out receipts...
  v4 minimal: accuracy 0.339 (threshold 0.8) per-field {'vendor': 0.275, 'date': 0.325, 'total': 0.35} errors 35 -> FAIL
registered custodian-extraction v5 (structured); extracting 60 held-out receipts...
  v5 structured: accuracy 0.883 (threshold 0.8) per-field {'vendor': 0.8, 'date': 0.925, 'total': 0.9} errors 2 -> PASS
BLOCKED: v4 (minimal) scored 0.339 < 0.8; not promoted
PROMOTED: custodian-extraction v5 (structured) -> production (accuracy 0.883)
```
The 35 errors on the minimal prompt are Groq refusing its output, for example:
```
"Tool choice is required, but model did not call a tool","type":"invalid_request_error","code":"tool_use_failed",
"failed_generation":"**Vendor:** PETRON BKT LANJAN SB  \n**Date:** 01/02/2018  \n**Total Amount:** 4.90 RM"
```
Step 2:
```
extraction -> mlflow:custodian-extraction@production (v5)
guardrail -> mlflow:custodian-guardrail-policy@production (v1)
risk -> mlflow:custodian-risk@production (v1)
approval -> mlflow:custodian-approval@production (v1)
critic -> mlflow:custodian-critic@production (v1)
```

## How it got here (three real runs)
1. **First run:** both prompts were measured mostly on rate limits. Groq's on-demand tier allows 8,000 tokens a minute on `gpt-oss-120b`, the job ran 4 calls at a time, and 24 of the structured prompt's 60 extractions failed with 429s (0.550, FAIL). A few more failed with LiteLLM 503s (`key lookup did not answer within 10s`) while the Docker VM was CPU-starved. A gate that fails on throttling measures the provider, not the prompt. The fix was to run 2 calls at a time and have the LLM wrapper wait out Groq's `try again in Ns` hint.
2. **Second run (above):** the structured prompt passed cleanly. The minimal prompt still failed, and its failure is a real property of the prompt. Without instructions to fill the schema, `gpt-oss-120b` often answers in prose, which the provider rejects. On the 25 receipts where it did return the schema, its fields were about as accurate as the structured prompt's (0.339 x 60 / 25 = about 0.81). The prompt fails because it is unreliable at producing the structure, not because it reads receipts badly. The run also exposed a bug in this project: the wrapper's retry for `tool_use_failed` never fired, because Instructor wraps the provider's 400 in its own exception type. Errors are now classified by content.
3. **Third run (with that retry fixed):** it ran into Groq's daily cap (200,000 tokens a day on the routine model, `TPD`), which the first two runs had nearly used up, and was stopped. It produced no verdict, and the `production` alias stayed on v5. The wrapper now fails immediately on waits longer than 60 s instead of blocking.

## What this actually teaches
A promotion gate is a measurement, and it is only as honest as what it measures:
- **Throttling:** the first run measured rate limits, not prompts.
- **Ground truth:** one CORD receipt in this set (`cord-test-0017`) had a wrong ground-truth total (0.91 instead of 91,000) until scenario 05's parser fix.
- **Sample size:** with 60 receipts, one receipt is worth about 1.7 points of accuracy.

What the gate does guarantee is the part that matters operationally: the version serving production is one that cleared the threshold on labelled data, the blocked version stays registered but unreachable, and the backend reports exactly which version it loaded. Honest limits: only the extraction prompt has labelled ground truth, so the guardrail, risk, approval and critic prompts are registered and aliased with no accuracy gate. And on Groq's free tier, the gate can run about once a day.
