"""Great Expectations checkpoint over the structural shape of every loaded invoice record.

A visibility control for the batch load, not a live gate: failures are printed for a human to
review and never block loading. Run `python -m loader.quality --self-test` to prove the gate is real.
"""
import argparse
import logging
import sys

import great_expectations as gx
import pandas as pd

log = logging.getLogger("loader.quality")

KEY_PATTERN = r"^(?:X\d{11}|cord-(?:train|validation|test)-\d{4})$"
MIN_TOTAL, MAX_TOTAL = 0.01, 50_000_000  # CORD totals are Indonesian rupiah, so the ceiling is high


def build_checkpoint() -> gx.Checkpoint:
    context = gx.get_context(mode="ephemeral")
    batch = context.data_sources.add_pandas("invoices").add_dataframe_asset("invoice_inbox").add_batch_definition_whole_dataframe("all")
    suite = context.suites.add(gx.ExpectationSuite(name="invoice_inbox_shape"))
    for expectation in (
        gx.expectations.ExpectColumnValuesToNotBeNull(column="external_key"),
        gx.expectations.ExpectColumnValuesToMatchRegex(column="external_key", regex=KEY_PATTERN),
        gx.expectations.ExpectColumnValuesToNotBeNull(column="ocr_text"),
        gx.expectations.ExpectColumnValuesToNotBeNull(column="gt_total"),
        gx.expectations.ExpectColumnValuesToNotBeNull(column="gt_total_amount"),
        gx.expectations.ExpectColumnValuesToBeBetween(column="gt_total_amount", min_value=MIN_TOTAL, max_value=MAX_TOTAL),
        gx.expectations.ExpectColumnValuesToNotBeNull(column="gt_vendor", row_condition='source=="sroie"', condition_parser="pandas"),
    ):
        suite.add_expectation(expectation)
    definition = context.validation_definitions.add(gx.ValidationDefinition(name="invoice_inbox", data=batch, suite=suite))
    return context.checkpoints.add(gx.Checkpoint(name="invoice_inbox_checkpoint", validation_definitions=[definition]))


def validate(df: pd.DataFrame) -> tuple[bool, list[str]]:
    result = build_checkpoint().run(batch_parameters={"dataframe": df})
    failures = []
    for run in result.run_results.values():
        for r in run.results:
            if not r.success:
                cfg = r.expectation_config
                res = r.result
                sample = res.get("partial_unexpected_list", [])[:5]
                failures.append(f"{cfg.type} on {cfg.kwargs.get('column')}: {res.get('unexpected_count')} unexpected, e.g. {sample}")
    return result.success, failures


def frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["source", "external_key", "ocr_text", "gt_vendor", "gt_total", "gt_total_amount"]).astype(
        {"gt_total_amount": "float64"})


def self_test() -> int:
    good = {"source": "sroie", "external_key": "X00016469670", "ocr_text": "OJC MARKETING SDN BHD\nTOTAL 193.00",
            "gt_vendor": "OJC MARKETING SDN BHD", "gt_total": "193.00", "gt_total_amount": 193.0}
    bad = {"source": "sroie", "external_key": "not-a-key", "ocr_text": None, "gt_vendor": None, "gt_total": "n/a", "gt_total_amount": None}
    ok_good, failures_good = validate(frame([good]))
    ok_bad, failures_bad = validate(frame([bad]))
    print(f"well-formed record passes: {ok_good} {failures_good}")
    print(f"malformed record fails:    {not ok_bad}")
    for failure in failures_bad:
        print(f"  - {failure}")
    return 0 if ok_good and not ok_bad else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    sys.exit(self_test() if parser.parse_args().self_test else 0)
