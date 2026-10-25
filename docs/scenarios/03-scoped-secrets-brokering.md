# 03. Secrets brokering: each machine identity can read only its own secret

**What this proves:** the ledger write key, the vendor-lookup key and the two provider API keys live only in Infisical, and each service's machine identity is refused every secret outside its scope.

## Background
`infra/scripts/provision-infisical-identities.py` creates one Infisical project per secret scope (custom project roles are an Enterprise feature, so projects are the unit of narrowing) and four Universal Auth machine identities, each a read-only viewer of only the projects it needs:

| identity | can read |
|---|---|
| `custodian-payment-execution` | `LEDGER_API_KEY` |
| `custodian-vendor-lookup` | `VENDOR_LOOKUP_API_KEY` |
| `custodian-ledger-service` | both ledger keys (to check what callers present) |
| `custodian-litellm` | `OPENAI_API_KEY`, `GROQ_API_KEY` |

The payment agent fetches the ledger key fresh on every call (`custodian-backend/app/infisical.py`); LiteLLM's entrypoint fetches the provider keys at start-up and never writes them to disk. `.env` holds only each identity's client ID and secret, not the keys themselves. `infra/scripts/infisical-read.py` logs in exactly as a service does and attempts one read, printing the outcome but never the value.

## Steps
```
infra/scripts/infisical-read.py payment-execution LEDGER_API_KEY
infra/scripts/infisical-read.py vendor-lookup LEDGER_API_KEY
infra/scripts/infisical-read.py vendor-lookup VENDOR_LOOKUP_API_KEY
infra/scripts/infisical-read.py litellm LEDGER_API_KEY
infra/scripts/infisical-read.py payment-execution OPENAI_API_KEY
infra/scripts/infisical-read.py litellm GROQ_API_KEY
```

## What you'll see
```
$ infra/scripts/infisical-read.py payment-execution LEDGER_API_KEY
login as custodian-payment-execution: ok, access token expires in 300s
read LEDGER_API_KEY: ok (64 characters)

$ infra/scripts/infisical-read.py vendor-lookup LEDGER_API_KEY
login as custodian-vendor-lookup: ok, access token expires in 300s
read LEDGER_API_KEY: HTTP 403 You are not a member of this project with ID db6e15d1-3b0e-415c-9111-7b2a17d9ae91. Please assign this identity to the project with the appropriate permissions, then try again.

$ infra/scripts/infisical-read.py vendor-lookup VENDOR_LOOKUP_API_KEY
login as custodian-vendor-lookup: ok, access token expires in 300s
read VENDOR_LOOKUP_API_KEY: ok (64 characters)

$ infra/scripts/infisical-read.py litellm LEDGER_API_KEY
login as custodian-litellm: ok, access token expires in 300s
read LEDGER_API_KEY: HTTP 403 You are not a member of this project with ID db6e15d1-3b0e-415c-9111-7b2a17d9ae91. ...

$ infra/scripts/infisical-read.py payment-execution OPENAI_API_KEY
login as custodian-payment-execution: ok, access token expires in 300s
read OPENAI_API_KEY: HTTP 403 You are not a member of this project with ID ad1794bc-40b5-4de6-8d18-84755c93c4ae. ...

$ infra/scripts/infisical-read.py litellm GROQ_API_KEY
login as custodian-litellm: ok, access token expires in 300s
read GROQ_API_KEY: ok (56 characters)
```

## What this actually teaches
Least privilege for secrets is a property of the broker, checked on every read: a compromised vendor-lookup identity (the one with the narrowest job) cannot escalate to moving money, and the payment agent cannot reach the model provider keys. Honest limits: the identities' client secrets sit in the gitignored `.env`, so whoever can read `.env` on this machine can log in as any of them; a production deployment would replace Universal Auth client secrets with a platform identity (Kubernetes or cloud workload identity, or SPIFFE federation). Infrastructure passwords (Postgres, MinIO, Keycloak, Infisical's own encryption key) cannot live in Infisical because they are needed to start it.
