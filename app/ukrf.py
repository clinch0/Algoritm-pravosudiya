"""Доступ к демо-базе санкций УК РФ и справочным данным."""
from __future__ import annotations
import json
from typing import Optional

from . import config
from .schemas import Sanction

_cache: dict[tuple, dict] = {}
_history_cache: dict[tuple, dict] = {}
_versions_cache: dict[tuple, dict] = {}


def _load_versions() -> dict:
    path = config.DATA_DIR / "law_versions.json"
    if not path.exists():
        return {"changes": []}
    stat = path.stat()
    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    if key not in _versions_cache:
        _versions_cache.clear()
        _versions_cache[key] = json.loads(path.read_text(encoding="utf-8"))
    return _versions_cache[key]


def _load_history() -> dict:
    path = config.DATA_DIR / "law_history.json"
    if not path.exists():
        return {"articles": {}}
    stat = path.stat()
    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    if key not in _history_cache:
        _history_cache.clear()
        _history_cache[key] = json.loads(path.read_text(encoding="utf-8"))
    return _history_cache[key]


def law_history(article: str | None) -> dict:
    """Известные изменения статьи по данным law_history.json.

    Возвращает {'current_redaction', 'amendments': [{date, changes: [...]}]}
    или {'current_redaction': None, 'amendments': []}, если данных нет.
    История НЕПОЛНАЯ: источник отдаёт только последние правки статьи.
    """
    if not article:
        return {"current_redaction": None, "amendments": []}
    return _load_history().get("articles", {}).get(str(article),
        {"current_redaction": None, "amendments": []})


def sanction_for_date(article: str | None, part: str | None, date_ddmmyyyy: str | None):
    """Санкция по состоянию на дату деяния (частичная реконструкция).

    Возвращает (Sanction, info): текущая санкция «откатывается» известными
    изменениями, произошедшими ПОСЛЕ даты деяния. История частичная —
    результат требует юридической проверки; при отсутствии данных
    возвращается текущая редакция со status=current_edition.
    """
    import copy as _copy
    from datetime import datetime as _datetime
    current_s = get_sanction(article, part)
    if current_s is None:
        return None, {"status": "sanction_missing", "history_partial": True, "applied_changes": []}
    sanction = _copy.deepcopy(current_s)
    info = {"status": "current_edition", "history_partial": True, "applied_changes": []}
    if not date_ddmmyyyy:
        return sanction, info
    try:
        cutoff = _datetime.strptime(date_ddmmyyyy, "%d.%m.%Y")
    except ValueError:
        return sanction, info
    changes = [c for c in _load_versions().get("changes", [])
               if c.get("article") == str(article) and c.get("part") == str(part)]
    later = []
    for c in changes:
        try:
            when = _datetime.strptime(c["changed_after"], "%d.%m.%Y")
        except ValueError:
            continue
        if when > cutoff:
            later.append((when, c))
    later.sort(key=lambda pair: pair[0], reverse=True)
    for _when, c in later:
        limits_before = c.get("limits_before") or {}
        sanction.imprisonment_min_years = limits_before.get("min")
        sanction.imprisonment_max_years = limits_before.get("max")
        info["applied_changes"].append({
            "changed_after": c["changed_after"],
            "limits": {"min": sanction.imprisonment_min_years,
                       "max": sanction.imprisonment_max_years},
        })
    info["status"] = "reconstructed_partial" if later else "current_edition"
    return sanction, info


def amendments_after(article: str | None, date_ddmmyyyy: str | None) -> list[dict]:
    """Известные правки статьи ПОСЛЕ даты (DD.MM.YYYY) — признак риска редакции."""
    if not article or not date_ddmmyyyy:
        return []
    history = law_history(article)
    try:
        from datetime import datetime
        cutoff = datetime.strptime(date_ddmmyyyy, "%d.%m.%Y")
    except ValueError:
        return []
    later = []
    for amendment in history.get("amendments", []):
        try:
            when = datetime.strptime(amendment["date"], "%d.%m.%Y")
        except ValueError:
            continue
        if when > cutoff:
            later.append(amendment)
    return later


def _load() -> dict:
    path = config.UKRF_SANCTIONS_PATH
    if not path.exists():
        return {"articles": []}
    stat = path.stat()
    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    if key not in _cache:
        _cache.clear()
        _cache[key] = json.loads(path.read_text(encoding="utf-8"))
    return _cache[key]


def all_sanctions() -> list[Sanction]:
    return [Sanction(**item) for item in _load()["articles"]]


def get_sanction(article: str | None, part: str | None = None) -> Optional[Sanction]:
    """Точный поиск: пропущенная часть не заменяется частью 1."""
    if not article or not part:
        return None
    article = str(article).strip()
    part = str(part).strip()
    for item in _load()["articles"]:
        if item["article"] == article and item["part"] == part:
            return Sanction(**item)

    return None


def category_from_max(max_years: float, negligent: bool) -> str:
    """Категория преступления по максимальному сроку лишения свободы (ст. 15 УК РФ)."""
    if max_years <= 3:
        return "небольшой тяжести"
    if negligent:
        return "средней тяжести" if max_years <= 10 else "тяжкое"
    if max_years <= 5:
        return "средней тяжести"
    if max_years <= 10:
        return "тяжкое"
    return "особо тяжкое"


RELATED_RULES: dict[str, list[str]] = {
    "105": ["Пленум ВС РФ от 27.01.1999 № 1 «О судебной практике по делам об убийстве (ст. 105 УК РФ)»"],
    "107": ["Пленум ВС РФ от 27.01.1999 № 1 (разъяснения по ст. 107 УК РФ)"],
    "108": ["Пленум ВС РФ от 27.09.2012 № 19 (необходимая оборона)"],
    "109": ["Пленум ВС РФ от 27.01.1999 № 1 (отдельные разъяснения)"],
    "111": ["Пленум ВС РФ от 27.01.1999 № 1 (отдельные разъяснения)",
            "Медицинские критерии — приказ Минздравсоцразвития РФ от 24.04.2008 № 194н"],
    "112": ["Пленум ВС РФ от 27.01.1999 № 1 (отдельные разъяснения)"],
    "117": ["Пленум ВС РФ от 27.01.1999 № 1 (отдельные разъяснения)"],
    "126": ["Пленум ВС РФ от 24.12.2019 № 58 «О судебной практике по делам о похищении человека»"],
    "131": ["Пленум ВС РФ от 04.12.2014 № 16 «О судебной практике по делам о преступлениях против половой неприкосновенности»"],
    "158": ["Пленум ВС РФ от 27.12.2002 № 29 «О судебной практике по делам о краже, грабеже и разбое»"],
    "159": ["Пленум ВС РФ от 30.11.2017 № 48 «О судебной практике по делам о мошенничестве, присвоении и растрате»"],
    "160": ["Пленум ВС РФ от 30.11.2017 № 48 «О судебной практике по делам о мошенничестве, присвоении и растрате»"],
    "161": ["Пленум ВС РФ от 27.12.2002 № 29 «О судебной практике по делам о краже, грабеже и разбое»"],
    "162": ["Пленум ВС РФ от 27.12.2002 № 29 «О судебной практике по делам о краже, грабеже и разбое»"],
    "163": ["Пленум ВС РФ от 17.12.2015 № 56 «О судебной практике по делам о вымогательстве»"],
    "166": ["Пленум ВС РФ от 09.12.2008 № 25 «О судебной практике по делам о преступлениях, связанных с нарушением правил дорожного движения»"],
    "228": ["Пленум ВС РФ от 15.06.2006 № 14 «О судебной практике по делам о преступлениях, связанных с наркотическими средствами»"],
    "228.1": ["Пленум ВС РФ от 15.06.2006 № 14 «О судебной практике по делам о преступлениях, связанных с наркотическими средствами»"],
    "264": ["Пленум ВС РФ от 09.12.2008 № 25 «О судебной практике по делам о преступлениях, связанных с нарушением правил дорожного движения»"],
}

GENERAL_RULES: list[str] = [
    "Постановление Пленума ВС РФ от 22.12.2015 № 58 «О практике назначения судами РФ уголовного наказания»",
]


def legal_reference(article: str | None, part: str | None = None) -> dict:
    """Справка для MCP-инструмента legal_reference."""
    sanction = get_sanction(article, part)
    result: dict = {"article": article, "part": part,
                    "law_version_status": "unverified_for_crime_date"}
    if sanction is None:
        result["found"] = False
        result["message"] = "Статья не найдена в демо-базе санкций."
        return result
    result["found"] = True
    result["sanction"] = {
        "label": sanction.label,
        "category": sanction.category,
        "punishment_types": sanction.punishment_types,
        "imprisonment_min_years": sanction.imprisonment_min_years,
        "imprisonment_max_years": sanction.imprisonment_max_years,
        "fine_min_rub": sanction.fine_min_rub,
        "fine_max_rub": sanction.fine_max_rub,
        "life_or_death": sanction.life_or_death,
    }
    result["related_plenum"] = RELATED_RULES.get(article, [])
    result["general"] = GENERAL_RULES
    history = law_history(article)
    result["law_history"] = {
        "current_redaction": history.get("current_redaction"),
        "partial": True,
        "amendments": [
            {"date": am["date"], "changed_rows": len(am["changes"]),
             "preview": [{"row": c["row"], "was": c["was"][:200], "became": c["became"][:200]}
                         for c in am["changes"][:3]]}
            for am in history.get("amendments", [])
        ],
    }
    return result
