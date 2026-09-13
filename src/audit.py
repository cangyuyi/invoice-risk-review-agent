"""Deterministic invoice duplicate-risk checker.

The LLM/OCR layer should only produce structured fields. This module owns the
financial decision rules so every result is reproducible and explainable.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path


def normalize_text(value: object) -> str:
    return "".join(str(value or "").upper().split())


def invoice_key(item: dict) -> str:
    number = normalize_text(item.get("invoice_number"))
    code = normalize_text(item.get("invoice_code"))
    return f"{code}:{number}" if number else ""


def money(value: object) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValueError(f"invalid amount: {value!r}") from None


def days_between(left: object, right: object) -> int:
    return abs((date.fromisoformat(str(left)) - date.fromisoformat(str(right))).days)


def audit(incoming: list[dict], ledger: list[dict]) -> dict:
    batch_keys = Counter(invoice_key(item) for item in incoming if invoice_key(item))
    batch_hashes = Counter(normalize_text(item.get("file_sha256")) for item in incoming if item.get("file_sha256"))
    ledger_by_key = {invoice_key(item): item for item in ledger if invoice_key(item)}
    results = []

    for item in incoming:
        result = {
            "record_id": item.get("record_id", ""),
            "invoice_number": item.get("invoice_number", ""),
            "risk_level": "low",
            "decision": "clear",
            "action": "auto_pass",
            "rule_ids": [],
            "evidence": [],
        }
        key = invoice_key(item)
        file_hash = normalize_text(item.get("file_sha256"))

        try:
            total_amount = money(item.get("total_amount"))
            date.fromisoformat(str(item.get("issue_date")))
        except (ValueError, TypeError) as exc:
            result.update(risk_level="medium", decision="invalid_input", action="manual_review")
            result["rule_ids"].append("R00")
            result["evidence"].append(str(exc))
            results.append(result)
            continue

        if not key:
            result.update(risk_level="medium", decision="missing_key_field", action="manual_review")
            result["rule_ids"].append("R01")
            result["evidence"].append("invoice_number is missing")

        if file_hash and batch_hashes[file_hash] > 1:
            result.update(risk_level="high", decision="confirmed_duplicate", action="hold_for_manual_review")
            result["rule_ids"].append("R10")
            result["evidence"].append(f"same file hash appears {batch_hashes[file_hash]} times in this batch")

        if key and batch_keys[key] > 1:
            result.update(risk_level="high", decision="confirmed_duplicate", action="hold_for_manual_review")
            result["rule_ids"].append("R11")
            result["evidence"].append(f"same invoice ID appears {batch_keys[key]} times in this batch")

        if key and key in ledger_by_key:
            match = ledger_by_key[key]
            result.update(risk_level="high", decision="confirmed_duplicate", action="hold_for_manual_review")
            result["rule_ids"].append("R20")
            result["evidence"].append(f"matches historical record {match['record_id']}")

        if result["risk_level"] != "high":
            seller_tax_id = normalize_text(item.get("seller_tax_id"))
            for historical in ledger:
                if (
                    seller_tax_id
                    and seller_tax_id == normalize_text(historical.get("seller_tax_id"))
                    and total_amount == money(historical.get("total_amount"))
                    and days_between(item.get("issue_date"), historical.get("issue_date")) <= 3
                    and key != invoice_key(historical)
                ):
                    result.update(risk_level="medium", decision="suspected_duplicate", action="manual_review")
                    result["rule_ids"].append("R30")
                    result["evidence"].append(
                        f"same seller and amount within 3 days of historical record {historical['record_id']}"
                    )
                    break

        results.append(result)

    return {
        "summary": {
            "total": len(results),
            "high_risk": sum(item["risk_level"] == "high" for item in results),
            "manual_review": sum(item["action"] != "auto_pass" for item in results),
            "auto_pass": sum(item["action"] == "auto_pass" for item in results),
        },
        "results": results,
    }


def load_json(path: Path) -> list[dict]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"{path} must contain a JSON array")
    return value


def self_test(project_root: Path) -> None:
    report = audit(
        load_json(project_root / "data" / "incoming_invoices.json"),
        load_json(project_root / "data" / "historical_ledger.json"),
    )
    by_id = {item["record_id"]: item for item in report["results"]}
    assert by_id["IN-001"]["decision"] == "confirmed_duplicate"
    assert by_id["IN-002"]["decision"] == "confirmed_duplicate"
    assert "R20" in by_id["IN-003"]["rule_ids"]
    assert by_id["IN-005"]["decision"] == "suspected_duplicate"
    assert by_id["IN-004"]["decision"] == "clear"
    assert report["summary"] == {"total": 5, "high_risk": 3, "manual_review": 4, "auto_pass": 1}
    print("self-test passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--incoming", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]

    if args.self_test:
        self_test(project_root)
        return
    if not all((args.incoming, args.ledger, args.output)):
        parser.error("--incoming, --ledger and --output are required")

    report = audit(load_json(args.incoming), load_json(args.ledger))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
