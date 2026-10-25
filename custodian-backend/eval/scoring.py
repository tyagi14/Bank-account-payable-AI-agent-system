"""Field-level comparison against the datasets' own ground truth."""
import difflib
import re
from datetime import date

VENDOR_MATCH_RATIO = 0.9
DATE_PATTERNS = [
    (r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", "dmy"), (r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})", "ymd"),
    (r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2})\b", "dmy2"), (r"(\d{1,2})\s*([A-Za-z]{3})[A-Za-z]*\s*,?\s*(\d{2,4})", "dMy"),
]
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def parse_amount(raw) -> float | None:
    """Same rules as custodian-data-loader/loader/amounts.py."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    cleaned = re.sub(r"[^0-9.,]", "", str(raw))
    if not cleaned or not re.search(r"\d", cleaned):
        return None
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", cleaned):
        return float(re.sub(r"[.,]", "", cleaned))
    try:
        return float(cleaned.replace(",", ""))
    except ValueError:
        return None


def parse_date(raw: str | None) -> date | None:
    """Day-first, as on the Malaysian SROIE receipts; equal dates in different formats compare equal."""
    if not raw:
        return None
    for pattern, order in DATE_PATTERNS:
        if m := re.search(pattern, raw):
            a, b, c = m.groups()
            try:
                if order == "dmy":
                    return date(int(c), int(b), int(a))
                if order == "ymd":
                    return date(int(a), int(b), int(c))
                if order == "dmy2":
                    return date(2000 + int(c), int(b), int(a))
                return date(int(c) if len(c) == 4 else 2000 + int(c), MONTHS[b.lower()[:3]], int(a))
            except (ValueError, KeyError):
                continue
    return None


def normalize_vendor(name: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", (name or "").upper())).strip()


def score(predicted: dict, expected: dict) -> dict[str, bool]:
    """One boolean per ground-truth field the record actually has."""
    results = {}
    if expected.get("vendor"):
        ratio = difflib.SequenceMatcher(None, normalize_vendor(predicted.get("vendor_name")), normalize_vendor(expected["vendor"])).ratio()
        results["vendor"] = ratio >= VENDOR_MATCH_RATIO
    if expected.get("date"):
        results["date"] = parse_date(expected["date"]) is not None and parse_date(predicted.get("invoice_date")) == parse_date(expected["date"])
    if expected.get("total") is not None:
        got = parse_amount(predicted.get("total_amount"))
        results["total"] = got is not None and abs(got - expected["total"]) < 0.01
    return results
