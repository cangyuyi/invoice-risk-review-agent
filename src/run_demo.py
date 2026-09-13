"""Run the local invoice image-to-risk-decision demo without publishing raw fields."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import zxingcpp
from PIL import Image

from audit import audit, load_json
from qr_baseline import parse_invoice_qr


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--private-output", type=Path, required=True)
    parser.add_argument("--public-output", type=Path, required=True)
    args = parser.parse_args()

    images = {path.name: path for path in args.images.glob("*.jpg")}
    incoming, extraction = [], []
    for template in load_json(args.metadata):
        image = images.get(template["source_file"])
        if not image:
            raise SystemExit(f"missing image for {template['record_id']}")
        with Image.open(image) as source:
            codes = zxingcpp.read_barcodes(source)
        valid = []
        for code in codes:
            try:
                valid.append((code.text, parse_invoice_qr(code.text)))
            except ValueError:
                continue
        fields = valid[0][1] if len(valid) == 1 else {"invoice_number": "", "issue_date": "", "total_amount": ""}
        file_hash = hashlib.sha256(image.read_bytes()).hexdigest().upper()
        incoming.append({**template, **fields, "file_sha256": file_hash, "data_origin": "private_image_qr_plus_synthetic_demo_metadata"})
        extraction.append({"record_id": template["record_id"], "source_file": image.name, "qr_text": valid[0][0] if len(valid) == 1 else "", "fields": fields})

    report = audit(incoming, load_json(args.ledger))
    for result in report["results"]:
        if result["action"] == "auto_pass":
            result.update(risk_level="medium", decision="unverified_invoice_status", action="manual_review")
            result["rule_ids"].append("R40")
            result["evidence"].append("QR fields decoded; tax validity, red-letter and void status not verified")
    report["summary"] = {
        "total": len(report["results"]),
        "high_risk": sum(row["risk_level"] == "high" for row in report["results"]),
        "manual_review": sum(row["action"] != "auto_pass" for row in report["results"]),
        "auto_pass": sum(row["action"] == "auto_pass" for row in report["results"]),
    }
    assert report["summary"]["total"] == len(incoming)

    private = {"extraction": extraction, "audit": report}
    public = {
        "summary": report["summary"],
        "results": [{key: value for key, value in row.items() if key != "invoice_number"} for row in report["results"]],
        "scope": "private invoice images + QR fields + synthetic demo metadata and ledger; no tax-authority verification",
    }
    args.private_output.parent.mkdir(parents=True, exist_ok=True)
    args.public_output.parent.mkdir(parents=True, exist_ok=True)
    args.private_output.write_text(json.dumps(private, ensure_ascii=False, indent=2), encoding="utf-8")
    args.public_output.write_text(json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
