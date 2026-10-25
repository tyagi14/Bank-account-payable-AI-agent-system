"""Sandboxed OCR: reads an image on stdin, applies a Landlock ruleset to itself, runs tesseract, prints JSON.

Docker already gives this container no network, a read-only root, no capabilities and a non-root
user. Landlock is a second, kernel-enforced layer inside it: after apply(), this process and its
children can touch only the paths below, even ones the container filesystem would otherwise expose.
"""
import json
import subprocess
import sys
import time

import nono_py

SCRATCH = "/scratch"
INPUT = f"{SCRATCH}/input"
MAX_BYTES = 10 * 1024 * 1024
READ_ONLY = ["/usr/bin/tesseract", "/usr/lib", "/usr/share/tesseract-ocr", "/etc/ld.so.cache"]
PROBES = ["/etc/passwd", "/etc/hostname", "/opt/ocr/entry.py", "/usr/local/lib"]


def apply_landlock() -> None:
    caps = nono_py.CapabilitySet()
    caps.allow_path(SCRATCH, nono_py.AccessMode.READ_WRITE)
    for path in READ_ONLY:
        if path.startswith("/usr/bin/") or path.startswith("/etc/"):
            caps.allow_file(path, nono_py.AccessMode.READ)
        else:
            caps.allow_path(path, nono_py.AccessMode.READ)
    caps.block_network()
    nono_py.apply_landlock(caps)


def probe() -> dict:
    """Paths Docker leaves readable in this container that Landlock must now refuse."""
    results = {}
    for path in PROBES:
        try:
            with open(path, "rb") as fh:
                fh.read(1)
            results[path] = "READABLE"
        except PermissionError:
            results[path] = "denied"
        except IsADirectoryError:
            try:
                import os
                os.listdir(path)
                results[path] = "READABLE"
            except PermissionError:
                results[path] = "denied"
    return results


def main() -> int:
    data = sys.stdin.buffer.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        print(json.dumps({"error": "image larger than 10MB"}))
        return 2
    if not (data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff")):
        print(json.dumps({"error": "only PNG or JPEG images are accepted"}))
        return 2
    with open(INPUT, "wb") as fh:
        fh.write(data)

    apply_landlock()
    probes = probe() if "--probe" in sys.argv else None
    started = time.monotonic()
    proc = subprocess.run(["/usr/bin/tesseract", INPUT, "stdout", "--psm", "4"], capture_output=True, text=True, timeout=45)
    result = {"text": proc.stdout, "tesseract_exit": proc.returncode, "ocr_ms": int((time.monotonic() - started) * 1000),
              "landlock": nono_py.support_info().__repr__()}
    if proc.returncode != 0:
        result["stderr"] = proc.stderr[-500:]
    if probes is not None:
        result["probes"] = probes
    print(json.dumps(result))
    return 0 if proc.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
