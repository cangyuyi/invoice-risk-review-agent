"""Local, privacy-preserving OCR baseline for the five invoice images."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from decimal import Decimal
from pathlib import Path


def extract_invoice_number(text: str) -> str:
    candidates = []
    for raw in re.findall(r"(?<![A-Z0-9])\d[\d\s]{15,24}\d(?![A-Z0-9])", text.upper()):
        value = re.sub(r"\D", "", raw)
        if 17 <= len(value) <= 22:
            candidates.append(value)
    return max(candidates, key=len, default="")


def extract_date(text: str) -> str:
    for year, month, day in re.findall(r"(20\d{2})\s*年?\s*(0?[1-9]|1[0-2])\s*月?\s*([0-3]?\d)\s*日?", text):
        if 1 <= int(day) <= 31:
            return f"{year}-{int(month):02d}-{int(day):02d}"
    return ""


def extract_total(text: str) -> str:
    values = []
    for whole, cents in re.findall(r"¥\s*(\d{1,8})\s*[.,]\s*(\d{1,2})", text):
        values.append(Decimal(f"{whole}.{cents.ljust(2, '0')}"))
    return f"{max(values):.2f}" if values else ""


def run_tesseract(tesseract: Path, image: Path, tessdata: Path, psm: int) -> str:
    result = subprocess.run(
        [str(tesseract), str(image), "stdout", "-l", "chi_sim+eng", "--tessdata-dir", str(tessdata), "--psm", str(psm)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout


def process(image: Path, tesseract: Path, tessdata: Path) -> tuple[dict, dict[str, str]]:
    texts = {str(psm): run_tesseract(tesseract, image, tessdata, psm) for psm in (6, 11)}
    numbers = {mode: extract_invoice_number(text) for mode, text in texts.items()}
    dates = {mode: extract_date(text) for mode, text in texts.items()}
    totals = {mode: extract_total(text) for mode, text in texts.items()}
    number = numbers["6"] or numbers["11"]
    issue_date = dates["6"] or dates["11"]
    total = max((Decimal(value) for value in totals.values() if value), default=None)
    structured = {
        "file_sha256": hashlib.sha256(image.read_bytes()).hexdigest().upper(),
        "invoice_number": number,
        "issue_date": issue_date,
        "total_amount": f"{total:.2f}" if total is not None else "",
        "number_modes_agree": bool(numbers["6"] and numbers["6"] == numbers["11"]),
        "date_modes_agree": bool(dates["6"] and dates["6"] == dates["11"]),
        "total_modes_agree": bool(totals["6"] and totals["6"] == totals["11"]),
        "confidence": "medium" if numbers["6"] and numbers["6"] == numbers["11"] else "low",
        "action": "manual_review",
    }
    return structured, texts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--tessdata", type=Path, required=True)
    parser.add_argument("--tesseract", type=Path, default=Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"))
    parser.add_argument("--private-output", type=Path, required=True)
    parser.add_argument("--public-output", type=Path, required=True)
    args = parser.parse_args()

    assert extract_invoice_number("发票号码: 12345678901234567890") == "12345678901234567890"
    assert extract_date("开票日期: 2026年05月16日") == "2026-05-16"
    assert extract_total("价税合计 (小写) ¥88. 20") == "88.20"
    if not args.tesseract.exists() or not (args.tessdata / "chi_sim.traineddata").exists() or not (args.tessdata / "eng.traineddata").exists():
        raise SystemExit("missing Tesseract or chi_sim/eng traineddata")

    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    gold_by_file = {item["source_file"]: item for item in gold}
    private_rows = []
    public_rows = []
    raw_dir = args.private_output.parent / "ocr_raw_private"
    raw_dir.mkdir(parents=True, exist_ok=True)

    for image in sorted(args.images.glob("*.jpg")):
        if image.name not in gold_by_file:
            continue
        prediction, texts = process(image, args.tesseract, args.tessdata)
        expected = gold_by_file[image.name]
        private_rows.append({"source_file": image.name, "expected": expected, "prediction": prediction})
        for mode, text in texts.items():
            (raw_dir / f"{expected['alias']}_psm{mode}.txt").write_text(text, encoding="utf-8")
        public_rows.append(
            {
                "alias": expected["alias"],
                "invoice_number_correct": prediction["invoice_number"] == expected["invoice_number"],
                "issue_date_correct": prediction["issue_date"] == expected["issue_date"],
                "total_amount_correct": prediction["total_amount"] == expected["total_amount"],
                "predicted_number_length": len(prediction["invoice_number"]),
                "number_modes_agree": prediction["number_modes_agree"],
                "confidence": prediction["confidence"],
                "action": prediction["action"],
            }
        )

    args.private_output.parent.mkdir(parents=True, exist_ok=True)
    args.public_output.parent.mkdir(parents=True, exist_ok=True)
    args.private_output.write_text(json.dumps(private_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "sample_size": len(public_rows),
        "invoice_number_accuracy": sum(row["invoice_number_correct"] for row in public_rows) / len(public_rows),
        "issue_date_accuracy": sum(row["issue_date_correct"] for row in public_rows) / len(public_rows),
        "total_amount_accuracy": sum(row["total_amount_correct"] for row in public_rows) / len(public_rows),
        "automatic_approval_rate": 0.0,
        "scope": "local Tesseract baseline on five user-provided test images; raw values remain private",
    }
    args.public_output.write_text(json.dumps({"summary": summary, "results": public_rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
