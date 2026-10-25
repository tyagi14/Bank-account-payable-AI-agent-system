# 18. The settlement ledger validates every entry in a dry run before anything is committed

**What this proves:** the internal double-entry ledger rejects unbalanced entries, unknown accounts, zero amounts and overdrafts, and does so in a dry run that leaves balances untouched. Only the ledger write key can even ask.

## Background
`custodian-ledger` is the sandboxed settlement layer: a real double-entry ledger (accounts, journal entries, postings) standing in for the bank rail, the way fintechs test settlement before going live. It is seeded with $500,000.00 of operating cash from the data loader. `apply_entry` (`custodian-ledger/app/ledger.py`) runs every validation inside one transaction, with `SELECT ... FOR UPDATE` on the affected balances, and rolls the transaction back when `commit` is false. So `POST /entries/dry-run` exercises exactly the code that a real `POST /entries` runs. The payment agent dry-runs every payment first and commits only if the dry run is valid (and only after the settlement hold). Write endpoints need `LEDGER_API_KEY` (from Infisical, scenario 03); the vendor-lookup key can only read.

## Steps
```
LEDGER_KEY=$(infra/scripts/infisical-read.py payment-execution LEDGER_API_KEY --show | tail -1)
LOOKUP_KEY=$(infra/scripts/infisical-read.py vendor-lookup VENDOR_LOOKUP_API_KEY --show | tail -1)
curl -s http://127.0.0.1:18010/accounts -H "X-API-Key: $LOOKUP_KEY"
curl -s -X POST http://127.0.0.1:18010/entries/dry-run -H "X-API-Key: $LEDGER_KEY" -H 'Content-Type: application/json' -d '<entry>'
```
with these entries (each `{"idempotency_key":"scenario-16-<name>","description":"...","postings":[...]}`):
1. valid: debit `expense:vendor-payments` 418195, credit `assets:operating-cash` -418195
2. unbalanced: 418195 against -418000
3. unknown account: credit `assets:offshore-cash`
4. overdraft: $612,480.00 (61248000 cents), the amount on sample invoice 07
5. zero amounts
6. the valid entry with the read-only lookup key
7. the valid entry with no key

then list the accounts again.

## What you'll see
```
[{"id":"assets:operating-cash","kind":"asset","balance_cents":50000000},{"id":"equity:opening-balance","kind":"equity","balance_cents":-50000000},{"id":"expense:vendor-payments","kind":"expense","balance_cents":0}]

1 {"valid":true,"committed":false,"entry_id":null,"errors":[],"resulting_balances":{"assets:operating-cash":49581805,"expense:vendor-payments":418195}}
2 {"valid":false,"committed":false,"entry_id":null,"errors":["unbalanced entry: postings sum to 195 cents, expected 0"],...}
3 {"valid":false,"committed":false,"entry_id":null,"errors":["unknown account: assets:offshore-cash"],...}
4 {"valid":false,"committed":false,"entry_id":null,"errors":["insufficient funds: assets:operating-cash would go to -11248000 cents"],"resulting_balances":{"assets:operating-cash":-11248000,"expense:vendor-payments":61248000}}
5 {"valid":false,"committed":false,"entry_id":null,"errors":["zero-amount posting"],...}
6 {"detail":"ledger write key required"}   HTTP 401
7 {"detail":"ledger write key required"}   HTTP 401

[{"id":"assets:operating-cash","kind":"asset","balance_cents":50000000},{"id":"equity:opening-balance","kind":"equity","balance_cents":-50000000},{"id":"expense:vendor-payments","kind":"expense","balance_cents":0}]
```

## What this actually teaches
Validation that only exists in the caller can be skipped by the caller. Here the money-side rules live in the ledger itself, so they hold no matter which agent, prompt or human sends the entry. A dry run that is the real transaction rolled back, rather than a separate "check" function, cannot drift from what a commit would do. Not shown here: duplicate idempotency-key detection only fires once an entry has been committed, so it needs a completed payment. That is part of the end-to-end pipeline scenario, which is still waiting on the reasoning route (see the index).
