"""Официальная статистика Судебного департамента при Верховном Суде РФ.

Источник: открытые сводные данные cdep.ru, форма № 10.3 «Отчёт о числе осуждённых
по всем составам преступлений УК РФ» (файлы: data/K7-svod_vse_sudy-<год>.xls,
преобразованы в data/official_stats.json).
"""
from __future__ import annotations
import json
from typing import Optional

from . import config

_cache: dict = {}  # ключ — путь к файлу данных (тесты могут перенаправлять DATA_DIR)

PUNISHMENT_LABELS = {
    "лишение_свободы": "реальное лишение свободы",
    "условно_лс": "условное осуждение к лишению свободы",
    "обязательные_работы": "обязательные работы",
    "исправительные_работы": "исправительные работы",
    "принудительные_работы": "принудительные работы",
    "ограничение_свободы": "ограничение свободы",
    "штраф": "штраф",
    "арест": "арест",
    "пожизненное_лс": "пожизненное лишение свободы",
}

# порядок вывода в справке — по частоте применения на практике
_DISPLAY_ORDER = ["лишение_свободы", "условно_лс", "обязательные_работы",
                  "исправительные_работы", "штраф", "принудительные_работы",
                  "ограничение_свободы", "арест", "пожизненное_лс"]


def _load() -> dict:
    path = config.DATA_DIR / "official_stats.json"
    if str(path) not in _cache:
        if path.exists():
            with open(path, encoding="utf-8") as f:
                _cache[str(path)] = json.load(f)
        else:
            # тестовое окружение с перенаправленным DATA_DIR: статистики нет
            _cache[str(path)] = {"years": {}}
    return _cache[str(path)]


def years_available() -> list[str]:
    return sorted(_load()["years"].keys())


def get(article: str | None, part: str | None = None, year: str | None = None) -> dict | None:
    """Данные формы 10.3 по статье (и части) за год; по умолчанию — последний доступный."""
    if not article:
        return None
    data = _load()
    years = years_available()
    if not years:
        return None
    year = year or years[-1]
    key = f"{article}~{part or '1'}"
    return data["years"].get(str(year), {}).get(key)


def shares(article: str | None, part: str | None = None, year: str | None = None) -> dict:
    """Доли видов наказаний (%) от числа осуждённых."""
    d = get(article, part, year)
    if not d:
        return {}
    total = d.get("всего_осуждено") or 0
    if not total:
        return {}
    return {k: round((d.get(k) or 0) / total * 100, 1) for k in _DISPLAY_ORDER if (d.get(k) or 0) > 0}


def summary_text(article: str | None, part: str | None = None, year: str | None = None) -> str:
    """Русская фраза для статистической справки заключения."""
    d = get(article, part, year)
    if not d:
        return "Официальная статистика по данной статье недоступна."
    year = year or years_available()[-1]
    total = int(d.get("всего_осуждено") or 0)
    sh = shares(article, part, year)
    parts = [f"{PUNISHMENT_LABELS[k]} — {v}%" for k, v in list(sh.items())[:6]]
    return (f"Официальные данные Судебного департамента при ВС РФ (форма № 10.3, {year} г.): "
            f"по {'ч. ' + str(part or '1') + ' ' if part else ''}ст. {article} УК РФ осуждено "
            f"{total:,} лиц; структура наказаний: {', '.join(parts)}.".replace(",", " "))
