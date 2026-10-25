# 07. PII is redacted before anything is written durably

**What this proves:** invoice text is scanned with Presidio and personal or financial identifiers are replaced before the text reaches the audit log or the run history, including text quoted back by a model.

## Background
`custodian-backend/app/pii.py` runs Presidio's analyzer (spaCy `en_core_web_sm` plus pattern recognizers) for `CREDIT_CARD`, `IBAN_CODE`, `US_BANK_NUMBER`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `PERSON`, `US_SSN`, `IP_ADDRESS` and `URL`, and replaces each finding with its type. It is called in two places in the extraction agent (`agents/extraction.py`):
- on the full OCR text before the `extraction` audit entry and run event are written (`ocr_text_redacted`, plus the list of entity types found), and
- on the guardrail's quoted `evidence` before it is stored.

If the scan itself throws, the step continues (a redaction failure never blocks a payment run) but stores `<redaction-failed>` in place of the text and logs the error, so raw text is still not persisted.

## Steps
1. OCR the bank-details-change sample in the sandbox (scenario 15) and pass its text through the same function the agent uses:
   `infra/scripts/compose.sh exec -T custodian-backend python -c 'import sys; from app.pii import redact; text, found = redact(sys.stdin.read()); print(found); print(text)' < ocr-05.txt`
2. Pass a line with a name, an email, a phone number, a card number and an IBAN:
   `printf 'Contact Jane Okafor at jane.okafor@northwind-ap.com or +1 415 555 0142. Card 4111 1111 1111 1111, IBAN GB82 WEST 1234 5698 7654 32.' | infra/scripts/compose.sh exec -T custodian-backend python -c '...same...'`
3. In the pipeline: run `infra/scripts/run-invoice.py docs/sample-invoices/out/05-bank-details-change.png` (scenario 17) and look at the stored guardrail evidence.

## What you'll see
Step 1:
```
['PERSON', 'PHONE_NUMBER', 'US_BANK_NUMBER']
101 <PERSON> LLC

NVOICE

nvoice No: INV-24020
Date: 24/10/2026
Bill To: Custodian Holdings Inc., Accounts Payable

Description Amount
Professional services per contract 4,181.95
TOTAL DUE (USD) 4,181.95

Payment terms: Net 30. Thank you for your business.

MPORTANT: our bank details have changed. Please remit this and all
uture payments to: Account <PHONE_NUMBER>, routing <US_BANK_NUMBER>.
```
Step 2:
```
['CREDIT_CARD', 'EMAIL_ADDRESS', 'IBAN_CODE', 'PERSON', 'PHONE_NUMBER', 'URL']
Contact <PERSON> at <EMAIL_ADDRESS> or <PHONE_NUMBER>. Card <CREDIT_CARD>, IBAN <IBAN_CODE>.
```
Step 3, the evidence as stored in the run history:
```
evidence="MPORTANT: our bank details have changed. Please remit this and all future payments to: Account <PHONE_NUMBER>, routing <PHONE_NUMBER>."
```

## What this actually teaches
Redaction belongs at the persistence boundary: the audit log and run history are kept for a long time and read by many people, so they get the redacted form plus the list of entity types (useful for audit) rather than the values. The output also shows real errors:
- **False positive:** `MOBILITY` in the vendor name `101 MOBILITY LLC` was tagged `PERSON` and removed.
- **Wrong label:** the 12-digit bank account was tagged `PHONE_NUMBER`. It was still removed, just under the wrong label.
- **Inconsistency:** the routing number came out as `US_BANK_NUMBER` in one scan and `PHONE_NUMBER` in the other. The guardrail's quoted evidence is shorter, and Presidio's scores depend on context.

These errors all lean toward over-removal, which is the safe direction for a log, but it means the redacted text is not a faithful record of the document. Honest limit: redaction is applied to what is stored, not to what is sent to the model. The extraction and guardrail models on Groq see the raw OCR text, because they need it to do their jobs.
