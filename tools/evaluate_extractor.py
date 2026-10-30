# -*- coding: utf-8 -*-
"""Измерение качества правила-ориентированного экстрактора на размеченном корпусе.

Запуск: python tools/evaluate_extractor.py
Выводит точность по полям и пишет docs/verification/extractor_metrics.json.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app.extractor import extract  # noqa: E402

FIELDS = ["article", "part", "punishment_type", "punishment_years", "punishment_months",
          "fine_rub", "probation", "probation_years", "probation_months", "stage",
          "recidivism", "is_minor", "mitigating", "aggravating", "release_grounds"]


def value_of(p, field):
    if field == "recidivism":
        return p.person.recidivism
    if field == "is_minor":
        return p.person.is_minor
    return getattr(p, field, None)


def equal(a, b):
    if isinstance(a, list) and isinstance(b, list):
        return sorted(a) == sorted(b)
    return a == b


def evaluate(data: dict) -> dict:
    rows = []
    field_stats = {f: {"ok": 0, "total": 0} for f in FIELDS}
    for case in data["cases"]:
        p = extract(case["text"], case["id"])
        expected = case["expected"]
        unknown = set(expected) - set(FIELDS)
        if unknown or not expected:
            raise ValueError(f"{case['id']}: unknown or empty expected fields: {sorted(unknown)}")
        row = {"id": case["id"], "failures": []}
        for field in FIELDS:
            if field not in expected:
                continue
            field_stats[field]["total"] += 1
            got = value_of(p, field)
            if equal(got, expected[field]):
                field_stats[field]["ok"] += 1
            else:
                row["failures"].append({"field": field, "expected": expected[field], "got": got})
        if row["failures"]:
            rows.append(row)
    report = {
        "cases": len(data["cases"]),
        "dataset_kind": "synthetic_development_set_not_independent_validation",
        "field_counts": field_stats,
        "field_accuracy": {f: round(s["ok"] / s["total"], 3) if s["total"] else None
                           for f, s in field_stats.items()},
        "failed_cases": rows,
    }
    return report


def main() -> int:
    data = json.loads((BASE / "data" / "labeled_cases.json").read_text(encoding="utf-8"))
    report = evaluate(data)
    field_stats = report["field_counts"]
    rows = report["failed_cases"]
    (BASE / "docs" / "verification").mkdir(parents=True, exist_ok=True)
    (BASE / "docs" / "verification" / "extractor_metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Точность по полям:")
    for f, acc in report["field_accuracy"].items():
        if acc is not None:
            print(f"  {f}: {acc * 100:.0f}% ({field_stats[f]['ok']}/{field_stats[f]['total']})")
    print(f"Кейсов с ошибками: {len(rows)} из {len(data['cases'])}")
    for row in rows:
        print("  " + row["id"] + ": " + "; ".join(
            f"{f['field']}={f['got']!r} (ожидалось {f['expected']!r})" for f in row["failures"]))
    return 1 if rows else 0


if __name__ == "__main__":
    raise SystemExit(main())
