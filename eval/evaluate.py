"""Build and run the 36-record structured-decision golden set."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from audit import audit  # noqa: E402


def invoice(record_id: str, number: str, issue_date: object, seller_id: str, amount: object, file_hash: str = "") -> dict:
    return {
        "record_id": record_id,
        "invoice_code": "",
        "invoice_number": number,
        "issue_date": issue_date,
        "seller_name": f"演示销售方-{seller_id}",
        "seller_tax_id": seller_id,
        "total_amount": amount,
        "file_sha256": file_hash,
        "data_origin": "synthetic_golden_set",
    }


def group(group_id: str, category: str, incoming: list[dict], ledger: list[dict], decision: str | dict) -> dict:
    expected = {item["record_id"]: decision for item in incoming} if isinstance(decision, str) else decision
    return {"group_id": group_id, "category": category, "incoming": incoming, "ledger": ledger, "expected": expected}


def build_golden_set() -> dict:
    groups = []

    normal = [invoice(f"N{i:02}", f"DEMO-N-{i:02}", f"2026-06-{i:02}", f"SELLER-N-{i:02}", 20 + i) for i in range(1, 9)]
    groups.append(group("G-NORMAL", "normal_unique", normal, [], "clear"))

    batch = [
        invoice("B01", "DEMO-B-01", "2026-06-10", "SELLER-B-01", 100, "A" * 64),
        invoice("B02", "DEMO-B-01", "2026-06-10", "SELLER-B-01", 100, "A" * 64),
        invoice("B03", "DEMO-B-02", "2026-06-11", "SELLER-B-02", 110, "B" * 64),
        invoice("B04", "DEMO-B-02", "2026-06-11", "SELLER-B-02", 110, "C" * 64),
        invoice("B05", "DEMO-B-03", "2026-06-12", "SELLER-B-03", 120, "D" * 64),
        invoice("B06", "DEMO-B-04", "2026-06-12", "SELLER-B-03", 120, "D" * 64),
    ]
    groups.append(group("G-BATCH", "batch_duplicate", batch, [], "confirmed_duplicate"))

    history_incoming = [invoice(f"H{i:02}", f"DEMO-H-{i:02}", f"2026-06-{10+i:02}", f"SELLER-H-{i:02}", 200 + i) for i in range(1, 7)]
    history_ledger = [dict(item, record_id=f"LEDGER-H-{i:02}", reimbursement_status="paid") for i, item in enumerate(history_incoming, 1)]
    groups.append(group("G-HISTORY", "history_exact_duplicate", history_incoming, history_ledger, "confirmed_duplicate"))

    suspicious_incoming = [invoice(f"S{i:02}", f"DEMO-S-NEW-{i:02}", f"2026-07-{10+i:02}", f"SELLER-S-{i:02}", 300 + i) for i in range(1, 7)]
    suspicious_ledger = [
        dict(item, record_id=f"LEDGER-S-{i:02}", invoice_number=f"DEMO-S-OLD-{i:02}", issue_date=f"2026-07-{9+i:02}", reimbursement_status="paid")
        for i, item in enumerate(suspicious_incoming, 1)
    ]
    groups.append(group("G-SUSPECT", "suspected_duplicate", suspicious_incoming, suspicious_ledger, "suspected_duplicate"))

    invalid = [
        invoice("I01", "", "2026-07-20", "SELLER-I-01", 10),
        invoice("I02", "DEMO-I-02", "2026-99-20", "SELLER-I-02", 20),
        invoice("I03", "DEMO-I-03", "not-a-date", "SELLER-I-03", 30),
        invoice("I04", "DEMO-I-04", "2026-07-21", "SELLER-I-04", "not-money"),
        invoice("I05", "DEMO-I-05", "2026-07-22", "SELLER-I-05", None),
        invoice("I06", "DEMO-I-06", None, "SELLER-I-06", 60),
    ]
    groups.append(
        group(
            "G-INVALID",
            "invalid_or_missing_fields",
            invalid,
            [],
            {"I01": "missing_key_field", "I02": "invalid_input", "I03": "invalid_input", "I04": "invalid_input", "I05": "invalid_input", "I06": "invalid_input"},
        )
    )

    edge = [
        invoice("E01", "   ", "2026-07-23", "SELLER-E-01", 70),
        invoice("E02", "DEMO-E-02", "2026-07-24", "SELLER-E-02", "80.00"),
        invoice("E03", " demo-e-03 ", "2026-07-25", "SELLER-E-03", 90),
        invoice("E04", "DEMO-E-04", "2026-07-26", "SELLER-E-04", 9999999.99),
    ]
    groups.append(group("G-EDGE", "normalization_edges", edge, [], {"E01": "missing_key_field", "E02": "clear", "E03": "clear", "E04": "clear"}))

    dataset = {
        "version": "v1.0",
        "scope": "structured duplicate-decision layer; excludes OCR and tax-platform verification",
        "data_origin": "fully synthetic",
        "groups": groups,
    }
    assert sum(len(item["incoming"]) for item in groups) == 36
    return dataset


def evaluate(dataset: dict) -> dict:
    rows = []
    for item in dataset["groups"]:
        actual = audit(item["incoming"], item["ledger"])
        for result in actual["results"]:
            expected = item["expected"][result["record_id"]]
            rows.append(
                {
                    "group_id": item["group_id"],
                    "category": item["category"],
                    "record_id": result["record_id"],
                    "expected": expected,
                    "actual": result["decision"],
                    "passed": result["decision"] == expected,
                    "rule_ids": result["rule_ids"],
                }
            )

    category_counts = Counter(row["category"] for row in rows)
    category_passes = Counter(row["category"] for row in rows if row["passed"])
    passed = sum(row["passed"] for row in rows)
    return {
        "version": dataset["version"],
        "summary": {
            "total": len(rows),
            "passed": passed,
            "failed": len(rows) - passed,
            "decision_accuracy": passed / len(rows),
        },
        "by_category": {
            category: {"total": total, "passed": category_passes[category], "accuracy": category_passes[category] / total}
            for category, total in sorted(category_counts.items())
        },
        "results": rows,
    }


def main() -> None:
    dataset = build_golden_set()
    report = evaluate(dataset)
    golden_path = Path(__file__).with_name("golden_set.json")
    result_path = Path(__file__).with_name("results_v1.json")
    golden_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
    result_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    assert report["summary"] == {"total": 36, "passed": 36, "failed": 0, "decision_accuracy": 1.0}
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
