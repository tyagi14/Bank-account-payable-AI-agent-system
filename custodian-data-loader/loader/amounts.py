import re


def parse_amount(raw: str | None) -> float | None:
    """Parses receipt totals like '193.00', 'RM 9.50', '60.000' / 'Rp.118.000' (dot thousands) or '1,346,000'."""
    if not raw:
        return None
    cleaned = re.sub(r"[^0-9.,]", "", raw).strip(".,")  # 'Rp.118.000' -> '118.000'
    if not cleaned or not re.search(r"\d", cleaned):
        return None
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", cleaned):
        return float(re.sub(r"[.,]", "", cleaned))
    cleaned = cleaned.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None
