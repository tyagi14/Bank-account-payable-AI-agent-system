"""Vendor master + payment history: the server-side source of truth Risk-Scoring reads."""
import re
from datetime import date

from psycopg import AsyncConnection
from pydantic import BaseModel, Field

RECENT_LIMIT = 10


def normalize_vendor(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", name.upper())).strip()


class VendorProfile(BaseModel):
    query: str
    normalized_name: str
    known: bool
    display_name: str | None = None
    first_seen: date | None = None
    award_count: int = 0
    average_amount_cents: int | None = None
    recent_amounts_cents: list[int] = []


class PaymentRecord(BaseModel):
    vendor_name: str = Field(min_length=1, max_length=300)
    amount_cents: int = Field(gt=0)
    external_id: str = Field(min_length=1, max_length=200)
    paid_on: date


async def lookup(conn: AsyncConnection, name: str) -> VendorProfile:
    normalized = normalize_vendor(name)
    async with conn.cursor() as cur:
        await cur.execute("SELECT id, display_name, first_seen FROM vendors WHERE normalized_name = %s", (normalized,))
        row = await cur.fetchone()
        if row is None:
            return VendorProfile(query=name, normalized_name=normalized, known=False)
        vendor_id, display_name, first_seen = row
        await cur.execute("SELECT count(*), avg(amount_cents)::bigint FROM historical_payments WHERE vendor_id = %s", (vendor_id,))
        count, average = await cur.fetchone()
        await cur.execute("SELECT amount_cents FROM historical_payments WHERE vendor_id = %s ORDER BY paid_on DESC, id DESC LIMIT %s",
                          (vendor_id, RECENT_LIMIT))
        recent = [r[0] for r in await cur.fetchall()]
    return VendorProfile(query=name, normalized_name=normalized, known=True, display_name=display_name, first_seen=first_seen,
                         award_count=count, average_amount_cents=average, recent_amounts_cents=recent)


async def record_payment(conn: AsyncConnection, record: PaymentRecord) -> VendorProfile:
    normalized = normalize_vendor(record.vendor_name)
    async with conn.transaction(), conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO vendors (normalized_name, display_name, first_seen, source) VALUES (%s, %s, %s, 'ledger')
               ON CONFLICT (normalized_name) DO UPDATE SET normalized_name = EXCLUDED.normalized_name RETURNING id""",
            (normalized, record.vendor_name.strip(), record.paid_on))
        vendor_id = (await cur.fetchone())[0]
        await cur.execute(
            """INSERT INTO historical_payments (vendor_id, external_id, amount_cents, paid_on, source) VALUES (%s, %s, %s, %s, 'ledger')
               ON CONFLICT (external_id) DO NOTHING""",
            (vendor_id, record.external_id, record.amount_cents, record.paid_on))
    return await lookup(conn, record.vendor_name)
