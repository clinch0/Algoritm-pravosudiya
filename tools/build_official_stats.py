# -*- coding: utf-8 -*-
"""Пересборка data/official_stats.json из XLS-первоисточников Судебного департамента.

Запуск: python tools/build_official_stats.py [2023 2024 ...]
Вход:  data/K7-svod_vse_sudy-<год>.xls (форма № 10.3, лист «Раздел 1»)
Выход: data/official_stats.json (если файл существует — годы дополняются/обновляются)

Колонки листа «Раздел 1» (индекс: значение):
  0 статья («158 ч. 2»), 2 всего осуждено, 3 пожизненное ЛС, 4 лишение свободы,
  5 условное осуждение к ЛС, 6 содержание в дисциплинарной воинской части,
  7 арест, 8 ограничение свободы, 9 ограничение по военной службе,
  10 исправительные работы, 11 обязательные работы, 12 принудительные работы,
  13 лишение права занимать должности, 14 штраф.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import xlrd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DATA = Path(__file__).resolve().parent.parent / "data"

COLUMNS = {
    "всего_осуждено": 2,
    "пожизненное_лс": 3,
    "лишение_свободы": 4,
    "условно_лс": 5,
    "арест": 7,
    "ограничение_свободы": 8,
    "исправительные_работы": 10,
    "обязательные_работы": 11,
    "принудительные_работы": 12,
    "штраф": 14,
}


def parse_year(year: str) -> dict:
    path = DATA / f"K7-svod_vse_sudy-{year}.xls"
    wb = xlrd.open_workbook(str(path))
    sh = wb.sheet_by_name("Раздел 1")
    year_data: dict = {}
    for r in range(sh.nrows):
        label = str(sh.cell_value(r, 0)).strip().replace("\n", " ")
        m = re.match(r"^(\d{1,3}(?:\.\d{1,2})?)\s*ч\.?\s*(\d{1,2})", label)
        if not m:
            continue
        def num(c: int) -> float:
            v = sh.cell_value(r, c)
            return float(v) if isinstance(v, (int, float)) else 0.0
        year_data[f"{m.group(1)}~{m.group(2)}"] = {
            name: num(col) for name, col in COLUMNS.items()
        }
    if not year_data:
        raise ValueError("Не распознано ни одной строки; выходной файл не изменён")
    return year_data


def main() -> int:
    years = sys.argv[1:] or ["2023", "2024"]
    out_path = DATA / "official_stats.json"
    result = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {
        "_source": ("Судебный департамент при Верховном Суде РФ, сводные отчёты по всем судам, "
                    "форма № 10.3 «Отчёт о числе осуждённых по всем составам преступлений УК РФ»"),
        "_note": ("Официальные открытые данные cdep.ru. Значения — число осуждённых лиц "
                  "по вступившим в законную силу приговорам за соответствующий год."),
        "years": {},
    }
    for year in years:
        result["years"][year] = parse_year(year)
        print(f"{year}: {len(result['years'][year])} записей")
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print("saved", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
