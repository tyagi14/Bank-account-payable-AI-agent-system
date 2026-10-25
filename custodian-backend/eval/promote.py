"""The Model Governance promotion gate: a real, computed evaluation against held-out ground truth.

Every extraction prompt candidate is registered as a new MLflow prompt version, run on the held-out
SROIE/CORD test split through the gateway, and scored field by field against the datasets' own
annotations with a DeepEval metric. Only a version whose accuracy meets EVAL_ACCURACY_THRESHOLD
can receive the `production` alias; a failing version stays registered, tagged, and unpromoted.

The other agents' prompts have no labelled ground truth to gate on, so they are registered and
aliased directly (that gap is documented in INSTRUCTIONS.md).
"""
import asyncio
import json
import os
import sys

os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "30")
os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "2")
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

import mlflow  # noqa: E402
import psycopg  # noqa: E402
from deepeval import evaluate  # noqa: E402
from deepeval.evaluate.configs import AsyncConfig, DisplayConfig  # noqa: E402
from deepeval.metrics import BaseMetric  # noqa: E402
from deepeval.test_case import LLMTestCase  # noqa: E402

from app import llm  # noqa: E402
from app.schemas import InvoiceFields  # noqa: E402
from eval.scoring import parse_amount, score  # noqa: E402

PROMPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "prompt_texts")
EXTRACTION = "custodian-extraction"
CANDIDATES = [("minimal", "extraction_minimal.txt"), ("structured", "extraction_structured.txt")]
UNGATED = {"custodian-guardrail-policy": "guardrail_policy.txt", "custodian-risk": "risk.txt",
           "custodian-approval": "approval.txt", "custodian-critic": "critic.txt"}
THRESHOLD = float(os.environ.get("EVAL_ACCURACY_THRESHOLD", "0.80"))
SAMPLE_SROIE = int(os.environ.get("EVAL_SAMPLE_SROIE", "40"))
SAMPLE_CORD = int(os.environ.get("EVAL_SAMPLE_CORD", "20"))
CONCURRENCY = 2  # Groq on-demand tier allows ~8k tokens/min on the routine model


class FieldAccuracy(BaseMetric):
    """Fraction of a receipt's ground-truth fields (vendor, date, total) the prompt extracted correctly."""

    def __init__(self, threshold: float = 1.0):
        self.threshold = threshold
        self.async_mode = False

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        results = score(json.loads(test_case.actual_output), json.loads(test_case.expected_output))
        self.score = sum(results.values()) / len(results)
        self.reason = ", ".join(f"{k}={'ok' if v else 'wrong'}" for k, v in results.items())
        self.success = self.score >= self.threshold
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return bool(self.success)

    @property
    def __name__(self):
        return "FieldAccuracy"


def held_out() -> list[dict]:
    with psycopg.connect(os.environ["CUSTODIAN_DB_URL"]) as conn:
        rows = conn.execute(
            """(SELECT external_key, ocr_text, gt_vendor, gt_date, gt_total FROM invoice_inbox
                WHERE source = 'sroie' AND split = 'test' AND gt_vendor IS NOT NULL AND gt_date IS NOT NULL AND gt_total IS NOT NULL
                ORDER BY external_key LIMIT %s)
               UNION ALL
               (SELECT external_key, ocr_text, NULL, NULL, gt_total FROM invoice_inbox
                WHERE source = 'cord' AND split = 'test' AND gt_total IS NOT NULL ORDER BY external_key LIMIT %s)""",
            (SAMPLE_SROIE, SAMPLE_CORD)).fetchall()
    return [{"key": r[0], "text": r[1], "expected": {"vendor": r[2], "date": r[3], "total": parse_amount(r[4])}} for r in rows]


async def extract_all(prompt: str, records: list[dict]) -> tuple[list[dict], dict]:
    gate = asyncio.Semaphore(CONCURRENCY)
    usage = {"input_tokens": 0, "output_tokens": 0, "errors": 0}

    async def one(record: dict) -> dict:
        async with gate:
            try:
                fields, meta = await llm.structured(base_url=os.environ["LITELLM_URL"], key=os.environ["LITELLM_KEY"], agent="prompt-eval",
                                                    route="custodian-routine", response_model=InvoiceFields, system=prompt, user=record["text"])
                usage["input_tokens"] += meta["input_tokens"]
                usage["output_tokens"] += meta["output_tokens"]
                return fields.model_dump()
            except Exception as exc:  # a failed extraction scores zero; it is not skipped
                usage["errors"] += 1
                print(f"  extraction error on {record['key']}: {exc.__class__.__name__}: {str(exc)[:200]}", flush=True)
                return {}

    return await asyncio.gather(*(one(r) for r in records)), usage


def evaluate_candidate(label: str, filename: str, records: list[dict]) -> dict:
    text = open(f"{PROMPT_DIR}/{filename}").read()
    version = mlflow.genai.register_prompt(name=EXTRACTION, template=text, commit_message=f"candidate: {label}",
                                           tags={"candidate": label, "source_file": filename})
    print(f"\nregistered {EXTRACTION} v{version.version} ({label}); extracting {len(records)} held-out receipts...", flush=True)
    predictions, usage = asyncio.run(extract_all(text, records))
    cases = [LLMTestCase(name=r["key"], input=r["key"], actual_output=json.dumps(p), expected_output=json.dumps(r["expected"]))
             for r, p in zip(records, predictions)]
    result = evaluate(test_cases=cases, metrics=[FieldAccuracy()], async_config=AsyncConfig(run_async=False),
                      display_config=DisplayConfig(print_results=False, show_indicator=False))
    scores = [t.metrics_data[0].score for t in result.test_results]
    accuracy = sum(scores) / len(scores)
    per_field = {}
    for r, p in zip(records, predictions):
        for field, ok in score(p, r["expected"]).items():
            per_field.setdefault(field, []).append(ok)
    field_acc = {f: round(sum(v) / len(v), 3) for f, v in per_field.items()}
    passed = accuracy >= THRESHOLD
    for key, value in {"eval_accuracy": f"{accuracy:.4f}", "eval_threshold": str(THRESHOLD), "eval_passed": str(passed),
                       "eval_records": str(len(records)), "eval_field_accuracy": json.dumps(field_acc)}.items():
        mlflow.genai.set_prompt_version_tag(EXTRACTION, version.version, key, value)
    with mlflow.start_run(run_name=f"{EXTRACTION}-v{version.version}-{label}"):
        mlflow.log_params({"prompt_version": version.version, "candidate": label, "threshold": THRESHOLD, "records": len(records)})
        mlflow.log_metrics({"accuracy": accuracy, **{f"accuracy_{f}": v for f, v in field_acc.items()},
                            "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"], "errors": usage["errors"]})
    print(f"  v{version.version} {label}: accuracy {accuracy:.3f} (threshold {THRESHOLD}) per-field {field_acc} "
          f"errors {usage['errors']} -> {'PASS' if passed else 'FAIL'}", flush=True)
    return {"label": label, "version": version.version, "accuracy": accuracy, "passed": passed}


def register_ungated() -> None:
    for name, filename in UNGATED.items():
        text = open(f"{PROMPT_DIR}/{filename}").read()
        try:
            current = mlflow.genai.load_prompt(f"prompts:/{name}@production")
            if current.template == text:
                continue
        except Exception:
            pass
        version = mlflow.genai.register_prompt(name=name, template=text, commit_message="sync from source", tags={"gated": "false"})
        mlflow.genai.set_prompt_alias(name, alias="production", version=version.version)
        print(f"registered {name} v{version.version} -> production (no ground-truth gate available)")


def main() -> int:
    mlflow.set_experiment("custodian-prompt-eval")
    register_ungated()
    records = held_out()
    if not records:
        print("no held-out records - run the data loader first")
        return 1
    print(f"held-out set: {len(records)} receipts from the SROIE/CORD test splits")
    results = [evaluate_candidate(label, filename, records) for label, filename in CANDIDATES]
    passing = [r for r in results if r["passed"]]
    for r in results:
        if not r["passed"]:
            print(f"BLOCKED: v{r['version']} ({r['label']}) scored {r['accuracy']:.3f} < {THRESHOLD}; not promoted")
    if not passing:
        print("no candidate passed the gate; production alias unchanged")
        return 1
    best = max(passing, key=lambda r: r["accuracy"])
    mlflow.genai.set_prompt_alias(EXTRACTION, alias="production", version=best["version"])
    print(f"PROMOTED: {EXTRACTION} v{best['version']} ({best['label']}) -> production (accuracy {best['accuracy']:.3f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
