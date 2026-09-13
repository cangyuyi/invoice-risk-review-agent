"""Decode invoice QR payloads locally and publish only redacted evaluation results."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import zxingcpp
from PIL import Image


def parse_invoice_qr(text: str) -> dict[str, str]:
    tokens = text.split(",")
    if len(tokens) != 8 or not re.fullmatch(r"\d{20}", tokens[3]):
        raise ValueError("unsupported invoice QR payload")
    if not re.fullmatch(r"\d+\.\d{2}", tokens[4]) or not re.fullmatch(r"\d{8}", tokens[5]):
        raise ValueError("invalid amount or date in invoice QR payload")
    return {
        "invoice_number": tokens[3],
        "issue_date": datetime.strptime(tokens[5], "%Y%m%d").date().isoformat(),
        "total_amount": f"{Decimal(tokens[4]):.2f}",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--private-output", type=Path, required=True)
    parser.add_argument("--public-output", type=Path, required=True)
    args = parser.parse_args()

    assert parse_invoice_qr("01,10,,12345678901234567890,87.00,20260422,,0000")["issue_date"] == "2026-04-22"
    gold = json.loads(args.gold.read_text(encoding="utf-8-sig"))
    gold_by_file = {row["source_file"]: row for row in gold}
    private_rows, public_rows, hashes = [], [], set()

    for image in sorted(args.images.glob("*.jpg")):
        if image.name not in gold_by_file:
            continue
        file_hash = hashlib.sha256(image.read_bytes()).hexdigest().upper()
        hashes.add(file_hash)
        with Image.open(image) as source:
            codes = zxingcpp.read_barcodes(source)
        valid = []
        for code in codes:
            try:
                valid.append((code.text, parse_invoice_qr(code.text)))
            except ValueError:
                continue
        prediction = valid[0][1] if len(valid) == 1 else {"invoice_number": "", "issue_date": "", "total_amount": ""}
        expected = gold_by_file[image.name]
        private_rows.append({"source_file": image.name, "file_sha256": file_hash, "qr_text": valid[0][0] if len(valid) == 1 else "", "prediction": prediction})
        checks = {field: prediction[field] == expected[field] for field in ("invoice_number", "issue_date", "total_amount")}
        public_rows.append({"alias": expected["alias"], "qr_decoded": len(valid) == 1, **{f"{field}_correct": correct for field, correct in checks.items()}, "fully_correct": all(checks.values()), "action": "manual_review_until_tax_authority_verification"})

    if not public_rows:
        raise SystemExit("no matching JPG samples")
    total = len(public_rows)
    summary = {
        "sample_size": total,
        "unique_image_count": len(hashes),
        "qr_decode_rate": sum(row["qr_decoded"] for row in public_rows) / total,
        **{f"{field}_accuracy": sum(row[f"{field}_correct"] for row in public_rows) / total for field in ("invoice_number", "issue_date", "total_amount")},
        "fully_correct_rate": sum(row["fully_correct"] for row in public_rows) / total,
        "risk_decision_automatic_approval_rate": 0.0,
        "scope": "local QR decoding; field extraction only, not invoice authenticity verification",
    }
    args.private_output.parent.mkdir(parents=True, exist_ok=True)
    args.public_output.parent.mkdir(parents=True, exist_ok=True)
    args.private_output.write_text(json.dumps(private_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    args.public_output.write_text(json.dumps({"summary": summary, "results": public_rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
