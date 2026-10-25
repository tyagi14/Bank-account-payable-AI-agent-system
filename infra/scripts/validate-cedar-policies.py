#!/usr/bin/env python3
"""Validates policies/ before they are loaded: schema validation, a permissiveness lint, the temporal
spec parse, and a multi-case authorization test matrix with expected outcomes.

Run manually (there is no CI in this project): python3 infra/scripts/validate-cedar-policies.py
On the host it re-runs itself inside the policy-service image, so it uses the exact Cedar engine,
entity construction and lint the live Policy Decision Point uses. Exit code 1 on any failure.
"""
import os
import subprocess
import sys
from pathlib import Path

INVOICE = {"type": "Invoice", "id": "matrix"}


def agent(name: str) -> dict:
    return {"type": "Agent", "id": name}


def human(role: str) -> dict:
    return {"type": "Human", "id": f"test-{role}", "role": role}


def auto(amount: int, known: bool = True, risk: int = 1000, confidence: int = 9000) -> dict:
    return {"amountCents": amount, "vendor": "ACME", "vendorKnown": known, "riskScoreBp": risk, "decisionConfidenceBp": confidence}


def human_ctx(amount: int) -> dict:
    return {"amountCents": amount, "vendor": "ACME", "vendorKnown": False}


def pay(amount: int, route: str) -> dict:
    return {"amountCents": amount, "vendor": "ACME", "approvalRoute": route}


# (description, principal, action, resource, context, expected_allow)
MATRIX = [
    ("approval agent auto-approves $1,000 from a known vendor", agent("approval"), "AutoApproveInvoice", INVOICE, auto(100_000), True),
    ("first-seen vendor cannot be auto-approved", agent("approval"), "AutoApproveInvoice", INVOICE, auto(100_000, known=False), False),
    ("$6,000 exceeds the auto-approve limit", agent("approval"), "AutoApproveInvoice", INVOICE, auto(600_000), False),
    ("risk score 0.60 blocks auto-approval", agent("approval"), "AutoApproveInvoice", INVOICE, auto(100_000, risk=6000), False),
    ("decision confidence 0.70 blocks auto-approval", agent("approval"), "AutoApproveInvoice", INVOICE, auto(100_000, confidence=7000), False),
    ("extraction agent cannot approve", agent("extraction"), "AutoApproveInvoice", INVOICE, auto(100_000), False),
    ("payment agent cannot approve", agent("payment-execution"), "AutoApproveInvoice", INVOICE, auto(100_000), False),
    ("AP clerk approves $9,000", human("ap_clerk"), "HumanApproveInvoice", INVOICE, human_ctx(900_000), True),
    ("AP clerk cannot approve $15,000", human("ap_clerk"), "HumanApproveInvoice", INVOICE, human_ctx(1_500_000), False),
    ("controller approves $15,000", human("finance_controller"), "HumanApproveInvoice", INVOICE, human_ctx(1_500_000), True),
    ("controller cannot approve $150,000", human("finance_controller"), "HumanApproveInvoice", INVOICE, human_ctx(15_000_000), False),
    ("CFO approves $2,000,000", human("cfo"), "HumanApproveInvoice", INVOICE, human_ctx(200_000_000), True),
    ("unknown human role approves nothing", human("intern"), "HumanApproveInvoice", INVOICE, human_ctx(1_000), False),
    ("payment agent pays a human-approved $50,000", agent("payment-execution"), "ExecutePayment", INVOICE, pay(5_000_000, "human"), True),
    ("payment agent refuses an auto-approved $50,000", agent("payment-execution"), "ExecutePayment", INVOICE, pay(5_000_000, "auto"), False),
    ("payment agent pays an auto-approved $1,000", agent("payment-execution"), "ExecutePayment", INVOICE, pay(100_000, "auto"), True),
    ("approval agent cannot execute payments", agent("approval"), "ExecutePayment", INVOICE, pay(100_000, "human"), False),
    ("extraction agent runs sandboxed OCR", agent("extraction"), "RunSandboxOCR", {"type": "Tool", "id": "sandbox-ocr"}, {}, True),
    ("risk agent cannot run sandboxed OCR", agent("risk-scoring"), "RunSandboxOCR", {"type": "Tool", "id": "sandbox-ocr"}, {}, False),
    ("risk agent reads RestrictedFinancial payment history", agent("risk-scoring"), "ReadData", {"type": "DataAsset", "id": "historical_payments"}, {}, True),
    ("extraction agent cannot read payment history", agent("extraction"), "ReadData", {"type": "DataAsset", "id": "historical_payments"}, {}, False),
    ("extraction agent reads the public vendor master", agent("extraction"), "ReadData", {"type": "DataAsset", "id": "vendors"}, {}, True),
    ("unknown agent reads nothing", agent("rogue"), "ReadData", {"type": "DataAsset", "id": "vendors"}, {}, False),
    ("extraction agent extracts", agent("extraction"), "ExtractInvoice", INVOICE, {}, True),
    ("payment agent cannot extract", agent("payment-execution"), "ExtractInvoice", INVOICE, {}, False),
    ("risk agent scores risk", agent("risk-scoring"), "ScoreRisk", INVOICE, {}, True),
]


def run_in_container() -> int:
    root = Path(__file__).resolve().parents[2]
    compose = [str(root / "infra/scripts/layer.sh"), "app"]
    subprocess.run([*compose, "build", "policy-service"], check=True, capture_output=True)
    return subprocess.run(["docker", "run", "--rm", "-e", "IN_POLICY_IMAGE=1", "-v", f"{root / 'policies'}:/policies:ro",
                           "-v", f"{Path(__file__).resolve()}:/srv/validate.py:ro", "custodian/policy-service:local",
                           "python", "/srv/validate.py"]).returncode


def validate() -> int:
    import cedarpy
    from app import cedar_engine, temporal
    from app.lint import lint

    policy_dir = Path("/policies")
    text = "\n".join(p.read_text() for p in sorted(policy_dir.glob("*.cedar")))
    failures = 0

    result = cedarpy.validate_policies(text, (policy_dir / "schema.cedarschema.json").read_text())
    print(f"[schema]   {'PASS' if result.validation_passed else 'FAIL'}")
    for err in result.errors:
        print(f"           {err}")
        failures += 1

    problems = lint(text)
    print(f"[lint]     {'PASS' if not problems else 'FAIL'}")
    for problem in problems:
        print(f"           {problem}")
    failures += len(problems)

    try:
        rules = temporal.load_rules(policy_dir / "temporal")
        print(f"[temporal] PASS {[f'{r.rule_id}: {r.limit} per {r.window_hours}h on {list(r.actions)}' for r in rules]}")
    except ValueError as exc:
        print(f"[temporal] FAIL {exc}")
        failures += 1

    if failures:
        print("\nREJECTED: fix the problems above before the matrix can run")
        return 1
    bundle = cedar_engine.load(policy_dir)
    print(f"[matrix]   {len(MATRIX)} cases")
    for description, principal, action, resource, context, expected in MATRIX:
        allowed, reasons, errors = cedar_engine.authorize(bundle, principal, action, resource, context)
        ok = allowed == expected and not errors
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {'allow' if allowed else 'deny ':5} {description}" + ("" if ok else f"  (expected {'allow' if expected else 'deny'}; {reasons} {errors})"))
    print("\nACCEPTED" if not failures else f"\nREJECTED: {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(validate() if os.environ.get("IN_POLICY_IMAGE") else run_in_container())
