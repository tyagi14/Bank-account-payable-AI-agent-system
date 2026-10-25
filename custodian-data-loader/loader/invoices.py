"""Loads the real SROIE and CORD receipts (images + ground-truth fields) into the invoice inbox."""
import io
import json
import logging

from datasets import Image, load_dataset
from minio import Minio
from psycopg import Connection

from loader.amounts import parse_amount

log = logging.getLogger("loader.invoices")

SCHEMA = """
CREATE TABLE IF NOT EXISTS invoice_inbox (
    id bigserial PRIMARY KEY,
    source text NOT NULL,
    split text NOT NULL,
    external_key text NOT NULL,
    image_object text NOT NULL,
    ocr_text text,
    gt_vendor text,
    gt_date text,
    gt_address text,
    gt_total text,
    gt_total_amount numeric,
    loaded_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source, external_key)
);
"""
INSERT = """
INSERT INTO invoice_inbox (source, split, external_key, image_object, ocr_text, gt_vendor, gt_date, gt_address, gt_total, gt_total_amount)
VALUES (%(source)s, %(split)s, %(external_key)s, %(image_object)s, %(ocr_text)s, %(gt_vendor)s, %(gt_date)s, %(gt_address)s, %(gt_total)s, %(gt_total_amount)s)
ON CONFLICT (source, external_key) DO NOTHING
"""


def _store_image(minio: Minio, key: str, image) -> str:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="PNG")
    size = buf.tell()
    buf.seek(0)
    minio.put_object("invoice-inbox", key, buf, size, content_type="image/png")
    return key


def _sroie_rows(split: str):
    for row in load_dataset("jsdnrs/ICDAR2019-SROIE", split=split):
        entities = row["entities"]
        yield row["image"], {
            "source": "sroie", "split": split, "external_key": row["key"],
            "ocr_text": "\n".join(row["words"]),
            "gt_vendor": entities.get("company") or None, "gt_date": entities.get("date") or None,
            "gt_address": entities.get("address") or None, "gt_total": entities.get("total") or None,
        }


def _cord_text(valid_lines: list[dict]) -> str:
    """Rebuilds receipt lines from CORD's word annotations: words grouped by row_id, rows ordered top to bottom."""
    rows: dict[int, list[tuple[int, int, str]]] = {}
    for line in valid_lines:
        for word in line["words"]:
            rows.setdefault(word["row_id"], []).append((word["quad"]["y1"], word["quad"]["x1"], word["text"]))
    ordered = sorted(rows.values(), key=lambda words: min(w[0] for w in words))
    return "\n".join(" ".join(w[2] for w in sorted(words, key=lambda w: w[1])) for words in ordered)


def _cord_rows(split: str):
    # Point at the split's own parquet file: asking load_dataset for one split still builds all of them,
    # and generating CORD's 800-image train split does not fit next to the rest of the stack.
    files = f"hf://datasets/naver-clova-ix/cord-v2/data/{split}-*.parquet"
    rows = load_dataset("parquet", data_files={split: files}, split=split).cast_column("image", Image())
    for idx, row in enumerate(rows):
        gt = json.loads(row["ground_truth"])
        total = (gt["gt_parse"].get("total") or {}).get("total_price")
        if isinstance(total, list):  # a handful of receipts annotate several totals
            total = total[0]
        yield row["image"], {
            "source": "cord", "split": split, "external_key": f"cord-{split}-{idx:04d}",
            "ocr_text": _cord_text(gt.get("valid_line", [])),
            # CORD masks store identity, so it has no vendor/date/address ground truth.
            "gt_vendor": None, "gt_date": None, "gt_address": None, "gt_total": total,
        }


def load_invoices(conn: Connection, minio: Minio, cord_splits: list[str]) -> None:
    conn.execute(SCHEMA)
    sources = [("sroie", s, _sroie_rows(s)) for s in ("train", "test")] + [("cord", s, _cord_rows(s)) for s in cord_splits]
    for source, split, rows in sources:
        existing = {r[0] for r in conn.execute("SELECT external_key FROM invoice_inbox WHERE source = %s AND split = %s", (source, split))}
        added = 0
        for image, record in rows:
            if record["external_key"] in existing:
                continue
            record["image_object"] = _store_image(minio, f"{source}/{record['external_key']}.png", image)
            record["gt_total_amount"] = parse_amount(record["gt_total"])
            conn.execute(INSERT, record)
            added += 1
        conn.commit()
        log.info("%s/%s: %d new records (%d already present)", source, split, added, len(existing))


def reparse_totals(conn: Connection) -> None:
    """Re-derives every parsed total from its raw ground-truth string, so parser fixes reach rows loaded earlier."""
    rows = conn.execute("SELECT source, external_key, gt_total, gt_total_amount::float FROM invoice_inbox").fetchall()
    changed = [(parse_amount(raw), source, key) for source, key, raw, current in rows if parse_amount(raw) != current]
    with conn.transaction():
        for amount, source, key in changed:
            conn.execute("UPDATE invoice_inbox SET gt_total_amount = %s WHERE source = %s AND external_key = %s", (amount, source, key))
    log.info("re-parsed ground-truth totals: %d of %d changed", len(changed), len(rows))
