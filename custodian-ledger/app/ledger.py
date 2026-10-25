"""Double-entry posting logic. Dry-run and commit both go through apply_entry, so they cannot drift."""
import uuid

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field


class Posting(BaseModel):
    account_id: str
    amount_cents: int  # debit > 0, credit < 0


class EntryRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=200)
    description: str = Field(min_length=1, max_length=500)
    postings: list[Posting]
    metadata: dict = Field(default_factory=dict)


class EntryResult(BaseModel):
    valid: bool
    committed: bool
    entry_id: str | None = None
    errors: list[str]
    resulting_balances: dict[str, int]


async def _validate(conn: AsyncConnection, entry: EntryRequest) -> tuple[list[str], dict[str, int]]:
    errors: list[str] = []
    if len(entry.postings) < 2:
        errors.append("an entry needs at least two postings")
    if any(p.amount_cents == 0 for p in entry.postings):
        errors.append("zero-amount posting")
    if (total := sum(p.amount_cents for p in entry.postings)) != 0:
        errors.append(f"unbalanced entry: postings sum to {total} cents, expected 0")

    async with conn.cursor() as cur:
        await cur.execute("SELECT 1 FROM journal_entries WHERE idempotency_key = %s", (entry.idempotency_key,))
        if await cur.fetchone():
            errors.append(f"duplicate idempotency key: {entry.idempotency_key}")

        account_ids = sorted({p.account_id for p in entry.postings})
        # Row locks serialize concurrent writers on the same accounts for the rest of the transaction.
        await cur.execute("SELECT id, allow_negative FROM accounts WHERE id = ANY(%s) ORDER BY id FOR UPDATE", (account_ids,))
        accounts = {row[0]: row[1] for row in await cur.fetchall()}
        errors += [f"unknown account: {a}" for a in account_ids if a not in accounts]

        await cur.execute("SELECT account_id, COALESCE(SUM(amount_cents), 0) FROM postings WHERE account_id = ANY(%s) GROUP BY account_id",
                          (list(accounts),))
        balances = {a: 0 for a in accounts} | {row[0]: int(row[1]) for row in await cur.fetchall()}

    for p in entry.postings:
        if p.account_id in balances:
            balances[p.account_id] += p.amount_cents
    for account, allow_negative in accounts.items():
        if not allow_negative and balances[account] < 0:
            errors.append(f"insufficient funds: {account} would go to {balances[account]} cents")
    return errors, balances


async def apply_entry(conn: AsyncConnection, entry: EntryRequest, commit: bool) -> EntryResult:
    """Validates and writes the entry inside one transaction; rolls back unless commit and valid."""
    async with conn.transaction(force_rollback=not commit):
        errors, balances = await _validate(conn, entry)
        if errors:
            return EntryResult(valid=False, committed=False, errors=errors, resulting_balances=balances)
        entry_id = uuid.uuid4()
        async with conn.cursor() as cur:
            await cur.execute("INSERT INTO journal_entries (id, idempotency_key, description, metadata) VALUES (%s, %s, %s, %s)",
                              (entry_id, entry.idempotency_key, entry.description, Jsonb(entry.metadata)))
            await cur.executemany("INSERT INTO postings (entry_id, account_id, amount_cents) VALUES (%s, %s, %s)",
                                  [(entry_id, p.account_id, p.amount_cents) for p in entry.postings])
        return EntryResult(valid=True, committed=commit, entry_id=str(entry_id) if commit else None, errors=[], resulting_balances=balances)
