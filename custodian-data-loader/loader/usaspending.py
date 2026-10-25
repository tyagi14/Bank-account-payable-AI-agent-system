"""Seeds the vendor master and historical payment ledger from real USAspending.gov contract awards."""
import logging
import re
import time
from datetime import date

import httpx
from psycopg import Connection

log = logging.getLogger("loader.usaspending")

API = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
FIELDS = ["Award ID", "Recipient Name", "Award Amount", "Start Date", "Recipient UEI", "generated_internal_id"]


def normalize_vendor(name: str) -> str:
    # Must match custodian-ledger/app/vendors.py normalize_vendor.
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", name.upper())).strip()


def fetch_awards(agency: str, start: str, end: str, pages: int) -> list[dict]:
    awards = []
    with httpx.Client(timeout=60) as client:
        for page in range(1, pages + 1):
            body = {
                "filters": {
                    "award_type_codes": ["A", "B", "C", "D"],
                    "time_period": [{"start_date": start, "end_date": end}],
                    "agencies": [{"type": "awarding", "tier": "toptier", "name": agency}],
                    "award_amounts": [{"lower_bound": 1000, "upper_bound": 250000}],
                },
                "fields": FIELDS, "limit": 100, "page": page, "sort": "Recipient Name", "order": "asc",
            }
            resp = client.post(API, json=body)
            resp.raise_for_status()
            data = resp.json()
            awards += data["results"]
            if not data["page_metadata"]["hasNext"]:
                break
            time.sleep(0.5)
    return awards


def load_vendors(conn: Connection, agency: str, start: str, end: str, pages: int) -> None:
    awards = fetch_awards(agency, start, end, pages)
    log.info("fetched %d real awards from USAspending (%s, %s..%s)", len(awards), agency, start, end)
    added = 0
    for award in awards:
        name, amount, started = award.get("Recipient Name"), award.get("Award Amount"), award.get("Start Date")
        if not name or not amount or amount <= 0 or not started:
            continue
        normalized, paid_on = normalize_vendor(name), date.fromisoformat(started)
        vendor_id = conn.execute(
            """INSERT INTO vendors (normalized_name, display_name, uei, first_seen, source) VALUES (%s, %s, %s, %s, 'usaspending')
               ON CONFLICT (normalized_name) DO UPDATE SET first_seen = LEAST(vendors.first_seen, EXCLUDED.first_seen)
               RETURNING id""", (normalized, name, award.get("Recipient UEI"), paid_on)).fetchone()[0]
        cur = conn.execute(
            """INSERT INTO historical_payments (vendor_id, external_id, amount_cents, paid_on, source) VALUES (%s, %s, %s, %s, 'usaspending')
               ON CONFLICT (external_id) DO NOTHING""", (vendor_id, award["generated_internal_id"], round(amount * 100), paid_on))
        added += cur.rowcount
    conn.commit()
    vendors, payments = conn.execute("SELECT (SELECT count(*) FROM vendors), (SELECT count(*) FROM historical_payments)").fetchone()
    log.info("vendor master: %d vendors, %d historical payments (%d new this run)", vendors, payments, added)


def seed_opening_balance(conn: Connection, cents: int) -> None:
    """Funds operating cash once. A seed write, balanced by construction; idempotent on its key."""
    row = conn.execute(
        """INSERT INTO journal_entries (id, idempotency_key, description) VALUES (gen_random_uuid(), 'seed:opening-balance', 'Opening cash balance')
           ON CONFLICT (idempotency_key) DO NOTHING RETURNING id""").fetchone()
    if row:
        conn.execute("INSERT INTO postings (entry_id, account_id, amount_cents) VALUES (%s, 'assets:operating-cash', %s), (%s, 'equity:opening-balance', %s)",
                     (row[0], cents, row[0], -cents))
        log.info("seeded opening cash balance of %d cents", cents)
    conn.commit()
