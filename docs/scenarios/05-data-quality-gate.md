# 05. The data-quality gate: its own self-test, and real defects in the real datasets

**What this proves:** the Great Expectations checkpoint demonstrably separates good records from bad ones, and on the real SROIE/CORD data it finds real defects, including one it could not have found on its own.

## Background
`custodian-data-loader` pulls SROIE (987 receipts) and CORD (validation + test, 200 receipts) from Hugging Face and 1000 real Department of Veterans Affairs awards from USAspending, then runs the checkpoint in `loader/quality.py` over every record in `invoice_inbox`:

- `external_key` not null and matching `^(?:X\d{11}|cord-(?:train|validation|test)-\d{4})$`
- `ocr_text`, `gt_total`, `gt_total_amount` not null; `gt_total_amount` between 0.01 and 50,000,000 (CORD totals are rupiah)
- `gt_vendor` not null for SROIE

`gt_total_amount` is derived from the raw ground-truth string by `loader/amounts.py`. The checkpoint reports and logs; it does not stop the load, and the evaluation set (scenario 10) filters out rows with missing ground truth itself. `python -m loader.quality --self-test` runs the same suite against one well-formed and one malformed record.

## Steps
1. Self-test: `infra/scripts/layer.sh data run --rm --no-deps --entrypoint python custodian-data-loader -m loader.quality --self-test`
2. Run the loader against the real data: `infra/scripts/layer.sh data run --rm custodian-data-loader`
3. Look at what the checkpoint flagged:
   `infra/scripts/compose.sh exec -T postgres psql -U postgres -d custodian -c "SELECT external_key, gt_vendor, gt_total FROM invoice_inbox WHERE external_key = 'X510056849111'"`

## What you'll see
Step 1:
```
well-formed record passes: True []
malformed record fails:    True
  - expect_column_values_to_match_regex on external_key: 1 unexpected, e.g. ['not-a-key']
  - expect_column_values_to_not_be_null on ocr_text: 1 unexpected, e.g. [None]
  - expect_column_values_to_not_be_null on gt_total_amount: 1 unexpected, e.g. [nan]
  - expect_column_values_to_not_be_null on gt_vendor: 1 unexpected, e.g. [None]
```
Step 2 (second run on the same day, so nothing new is inserted):
```
INFO loader.invoices sroie/train: 0 new records (626 already present)
INFO loader.invoices sroie/test: 0 new records (361 already present)
INFO loader.invoices cord/validation: 0 new records (100 already present)
INFO loader.invoices cord/test: 0 new records (100 already present)
INFO loader.usaspending fetched 1000 real awards from USAspending (Department of Veterans Affairs, 2025-10-01..2026-09-30)
INFO loader.usaspending vendor master: 115 vendors, 1001 historical payments (0 new this run)
INFO loader.invoices re-parsed ground-truth totals: 4 of 1187 changed
INFO loader great expectations checkpoint over 1187 invoice records: FAILED
WARNING loader data quality: expect_column_values_to_match_regex on external_key: 1 unexpected, e.g. ['X510056849111']
WARNING loader data quality: expect_column_values_to_not_be_null on gt_total: 8 unexpected, e.g. [nan, nan, nan, nan, nan]
WARNING loader data quality: expect_column_values_to_not_be_null on gt_total_amount: 8 unexpected, e.g. [nan, nan, nan, nan, nan]
```
Step 3: a real SROIE receipt whose key has twelve digits instead of eleven:
```
 external_key  |              gt_vendor              | gt_total
---------------+-------------------------------------+----------
 X510056849111 | WESTERN EASTERN STATIONERY SDN. BHD | RM7.42
```

## Three findings from running it for real
1. **The datasets have real defects.** One malformed SROIE key, and eight receipts (seven CORD, one SROIE) with no ground-truth total at all.
2. **The first version of the checkpoint flagged 11 missing parsed totals, not 8.** Three of them were valid rupiah amounts (`Rp.118.000`, `Rp. 35.000`, `Rp. 39.000`) that the amount parser could not read because of the leading `Rp.`. That was a bug in this project, which the gate surfaced. Fixing the parser re-derived those values on the next run.
3. **The fix also corrected a value the gate had passed.** `cord-test-0017`'s total `Rp. 91,000` had been stored as `0.91`. That is a valid-looking amount inside the allowed range, so no expectation flagged it. It was found only by diffing the old and new parsers over every row. That receipt is in the held-out evaluation set, so the evaluation in scenario 10 (run before the fix) scored one CORD total against a wrong answer.

## What this actually teaches
A data-quality gate catches the defect classes it was written for: missing values, malformed keys, out-of-range numbers. It cannot catch a plausible wrong value, and the 0.91 case shows exactly that. The self-test shows the gate can say no. The real run shows the data is not clean even in well-known public datasets. Re-deriving values when the parser changes, rather than trusting what was loaded earlier, is what fixed the silent error. Honest limit: the gate reports rather than blocks, so a bad record stays in `invoice_inbox`. Only consumers that filter on the flagged columns (as the evaluation does) are protected.
