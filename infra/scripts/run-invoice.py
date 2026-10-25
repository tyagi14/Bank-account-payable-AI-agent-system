#!/usr/bin/env python3
"""Submit an invoice image to the backend and follow the run until it ends or waits for a human.

Usage: infra/scripts/run-invoice.py <image.png> [--full]
Prints one line per pipeline event (--full prints every event's complete detail as JSON).
Exit code: 0 completed, 3 input-required (approve or reject it in the console or via /decision), 1 otherwise.
"""
import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

BACKEND = "http://127.0.0.1:18000"
WAITING, DONE = {"input-required"}, {"completed", "failed", "rejected", "canceled"}
TIMEOUT_SECONDS = 900


def submit(path: Path) -> str:
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{BACKEND}/runs/image", data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return json.load(urllib.request.urlopen(req, timeout=60))["thread_id"]


def brief(detail: dict) -> str:
    skip = {"llm", "ocr_text", "redacted_text", "text"}
    parts = [f"{k}={json.dumps(v, default=str)}" for k, v in detail.items() if k not in skip]
    if "llm" in detail and isinstance(detail["llm"], dict):
        llm = detail["llm"]
        parts.append(f"llm={llm.get('route')}/{llm.get('provider')} {llm.get('input_tokens')}+{llm.get('output_tokens')} tok")
    line = " ".join(parts)
    return line if len(line) <= 400 else line[:397] + "..."


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--full"]
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    full = "--full" in sys.argv
    thread_id = submit(Path(args[0]))
    print(f"submitted {Path(args[0]).name} -> thread {thread_id}")
    seen, deadline = set(), time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        run = json.load(urllib.request.urlopen(f"{BACKEND}/runs/{thread_id}", timeout=30))
        for event in run["events"]:
            if event["id"] in seen:
                continue
            seen.add(event["id"])
            detail = json.dumps(event["detail"], indent=2, default=str) if full else brief(event["detail"])
            print(f"  {event['ts'][11:19]} {event['agent']:<18} {event['kind']:<20} {detail}")
        if run["task_state"] in WAITING | DONE:
            print(f"task_state={run['task_state']} stage={run['stage']} summary={json.dumps(run['summary'], default=str)}")
            return 0 if run["task_state"] == "completed" else 3 if run["task_state"] in WAITING else 1
        time.sleep(1)
    print(f"still running after {TIMEOUT_SECONDS}s: {BACKEND}/runs/{thread_id}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
