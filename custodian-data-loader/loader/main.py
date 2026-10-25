"""One-time, safely re-runnable seeding job: real invoices, real vendors, then the data-quality checkpoint."""
import argparse
import logging
import os
from pathlib import Path

import psycopg
from minio import Minio

from loader.invoices import load_invoices, reparse_totals
from loader.quality import frame, validate
from loader.usaspending import load_vendors, seed_opening_balance

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("loader")


def run_checkpoint(conn: psycopg.Connection) -> None:
    rows = conn.execute("SELECT source, external_key, ocr_text, gt_vendor, gt_total, gt_total_amount::float FROM invoice_inbox").fetchall()
    df = frame([dict(zip(["source", "external_key", "ocr_text", "gt_vendor", "gt_total", "gt_total_amount"], r)) for r in rows])
    success, failures = validate(df)
    log.info("great expectations checkpoint over %d invoice records: %s", len(df), "PASSED" if success else "FAILED")
    for failure in failures:
        log.warning("data quality: %s", failure)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cord-splits", default=os.environ.get("CORD_SPLITS", "validation,test"))
    parser.add_argument("--usaspending-agency", default=os.environ.get("USASPENDING_AGENCY", "Department of Veterans Affairs"))
    parser.add_argument("--usaspending-start", default=os.environ.get("USASPENDING_START", "2025-10-01"))
    parser.add_argument("--usaspending-end", default=os.environ.get("USASPENDING_END", "2026-09-30"))
    parser.add_argument("--usaspending-pages", type=int, default=int(os.environ.get("USASPENDING_PAGES", "10")))
    args = parser.parse_args()

    minio = Minio("minio:9000", os.environ["MINIO_ROOT_USER"], os.environ["MINIO_ROOT_PASSWORD"], secure=False)
    with psycopg.connect(os.environ["CUSTODIAN_DB_URL"]) as conn:
        load_invoices(conn, minio, args.cord_splits.split(","))
    with psycopg.connect(os.environ["LEDGER_DB_URL"]) as conn:
        conn.execute(Path("/srv/ledger-schema.sql").read_text())
        load_vendors(conn, args.usaspending_agency, args.usaspending_start, args.usaspending_end, args.usaspending_pages)
        seed_opening_balance(conn, int(os.environ["OPENING_CASH_CENTS"]))
    with psycopg.connect(os.environ["CUSTODIAN_DB_URL"]) as conn:
        reparse_totals(conn)
        run_checkpoint(conn)


if __name__ == "__main__":
    main()
