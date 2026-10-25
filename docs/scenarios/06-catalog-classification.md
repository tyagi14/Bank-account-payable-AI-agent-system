# 06. One classification, two enforcers: the data catalog and the policy engine agree

**What this proves:** every table the agents touch is registered in OpenMetadata with a sensitivity tag, and those tags are the same classifications Cedar uses to decide which agent may read which data.

## Background
`policies/entities.json` is the single source of truth for data classification: each data asset has a classification (`public` 0, `internal` 1, `RestrictedFinancial` 2), and each agent a clearance. `policies/data-access.cedar` permits `ReadData` only when the agent's clearance is at least the asset's level. `infra/scripts/register-openmetadata-catalog.py` reads the same file and registers each table, with its real column list pulled from Postgres, under the classification `CustodianSensitivity` in OpenMetadata (through the REST API; there is no Airflow ingestion container).

## Steps
1. `python3 infra/scripts/register-openmetadata-catalog.py` (idempotent)
2. Print what the policy engine sees: each data asset's classification and each agent's clearance from `policies/entities.json`
3. Open http://localhost:18585 (admin@open-metadata.org / admin), Explore, filter by the tag `CustodianSensitivity.RestrictedFinancial`
4. Watch the policy side enforce it (taken from scenario 13): the extraction agent (clearance 1) asking to read `historical_payments` (level 2)

## What you'll see
Step 1:
```
registered custodian-postgres.custodian.public.invoice_inbox -> CustodianSensitivity.internal
registered custodian-postgres.ledger.public.vendors -> CustodianSensitivity.public
registered custodian-postgres.ledger.public.historical_payments -> CustodianSensitivity.RestrictedFinancial
registered custodian-postgres.ledger.public.journal_entries -> CustodianSensitivity.RestrictedFinancial
registered custodian-postgres.ledger.public.postings -> CustodianSensitivity.RestrictedFinancial
```
Step 2:
```
asset  invoice_inbox          internal             (level 1)
asset  vendors                public               (level 0)
asset  historical_payments    RestrictedFinancial  (level 2)
asset  journal_entries        RestrictedFinancial  (level 2)
asset  postings               RestrictedFinancial  (level 2)
agent  extraction             clearance 1
agent  risk-scoring           clearance 2
agent  approval               clearance 1
agent  payment-execution      clearance 2
```
The catalog, queried back through its API:
```
custodian-postgres.custodian.public.invoice_inbox    CustodianSensitivity.internal              12 columns
custodian-postgres.ledger.public.historical_payments CustodianSensitivity.RestrictedFinancial   6 columns
custodian-postgres.ledger.public.journal_entries     CustodianSensitivity.RestrictedFinancial   5 columns
custodian-postgres.ledger.public.postings            CustodianSensitivity.RestrictedFinancial   4 columns
custodian-postgres.ledger.public.vendors             CustodianSensitivity.public                6 columns
```
Step 4: `deny ['cedar: no permit policy matched (default deny)']`, while the risk-scoring agent (clearance 2) is allowed the same read.

## What this actually teaches
Data classification is only governance if something enforces it. Here the label a data steward sees in the catalog and the attribute the policy engine evaluates come from the same file, so they cannot drift apart silently. Honest limits: the catalog is a mirror, not the authority. Re-tagging a table in the OpenMetadata UI changes nothing in Cedar until `entities.json` is changed. And the first registration attempt during this run timed out on login after 30 s while the data loader was busy (the client timeout is now 120 s). The catalog is a heavy service (about 1.9 GB with Elasticsearch) for what it contributes here.
