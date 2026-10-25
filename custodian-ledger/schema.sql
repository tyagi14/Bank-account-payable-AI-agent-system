-- Internal double-entry ledger. Debits are positive amounts, credits negative; every entry sums to zero.
CREATE TABLE IF NOT EXISTS accounts (
    id text PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('asset', 'liability', 'equity', 'expense', 'revenue')),
    allow_negative boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS journal_entries (
    id uuid PRIMARY KEY,
    idempotency_key text NOT NULL UNIQUE,
    description text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS postings (
    id bigserial PRIMARY KEY,
    entry_id uuid NOT NULL REFERENCES journal_entries (id),
    account_id text NOT NULL REFERENCES accounts (id),
    amount_cents bigint NOT NULL CHECK (amount_cents <> 0)
);
CREATE INDEX IF NOT EXISTS postings_account_idx ON postings (account_id);

CREATE TABLE IF NOT EXISTS vendors (
    id bigserial PRIMARY KEY,
    normalized_name text NOT NULL UNIQUE,
    display_name text NOT NULL,
    uei text,
    first_seen date NOT NULL,
    source text NOT NULL CHECK (source IN ('usaspending', 'ledger'))
);

CREATE TABLE IF NOT EXISTS historical_payments (
    id bigserial PRIMARY KEY,
    vendor_id bigint NOT NULL REFERENCES vendors (id),
    external_id text NOT NULL UNIQUE,
    amount_cents bigint NOT NULL CHECK (amount_cents > 0),
    paid_on date NOT NULL,
    source text NOT NULL CHECK (source IN ('usaspending', 'ledger'))
);
CREATE INDEX IF NOT EXISTS historical_payments_vendor_idx ON historical_payments (vendor_id, paid_on DESC);

INSERT INTO accounts (id, kind, allow_negative) VALUES
    ('assets:operating-cash', 'asset', false),
    ('equity:opening-balance', 'equity', true),
    ('expense:vendor-payments', 'expense', false)
ON CONFLICT (id) DO NOTHING;
