"""Single local pipeline for HTTP and MCP; no external model calls."""
from __future__ import annotations
import copy
import hashlib
import uuid
from . import config


def run(text: str) -> dict:
    from . import anonymizer, checker, extractor, ukrf, official_stats, conclusion
    from .rag import CaseStore
    from .schemas import to_dict
    masked = anonymizer.mask_text(text)
    case_id = "VO-" + uuid.uuid4().hex[:12].upper()
    params = extractor.extract(masked, case_id)
    # The date is a necessary local legal fact, not a licence for external export.
    params.crime_date = extractor.extract_crime_date(text)
    params.rule_context = checker.rule_context(params)
    return _run_parameters(params, masked, "local_demo")


def _run_parameters(params, masked: str, mode: str) -> dict:
    from . import checker, ukrf, official_stats, conclusion
    from .rag import CaseStore
    from .schemas import to_dict
    case_id = params.case_id
    sanction_for_check = ukrf.get_sanction(params.article, params.part)
    edition_sanction = {"status": "current_edition", "history_partial": True, "applied_changes": []}
    if params.crime_date:
        try:
            sanction_for_check, edition_sanction = ukrf.sanction_for_date(
                params.article, params.part, params.crime_date)
        except Exception:
            sanction_for_check = ukrf.get_sanction(params.article, params.part)
    check = checker.check(params, sanction_for_check)
    exact_qualification = bool(params.article and params.part)
    with CaseStore() as store:
        store.ensure_samples()
        similar = store.search(masked, article=params.article, part=params.part,
                               punishment_type=params.punishment_type, top_k=5) if exact_qualification else []
        stats = store.stats(article=params.article, part=params.part,
                            punishment_type=params.punishment_type or "лишение свободы") if exact_qualification else {"count":0}
    stats.update(source_kind="synthetic", source_label="Синтетические учебные примеры; не судебная практика",
                 cohort={"article": params.article, "part": params.part, "punishment_type": params.punishment_type},
                 limitation="В демо нет надёжного разделения реального/условного исполнения и полного контроля обстоятельств.")
    official = official_stats.get(params.article, params.part) if exact_qualification else None
    stats["official"] = {"year": official_stats.years_available()[-1] if official_stats.years_available() else None,
                         "data": official, "shares": official_stats.shares(params.article, params.part) if official else {},
                         "source_label": "Судебный департамент, форма № 10.3; унаследованный снимок 2023–2024",
                         "limitation": "Агрегат по статье не доказывает сходство дел или законность срока."}
    # Применимая редакция: частичная история правок статьи против даты деяния
    history = ukrf.law_history(params.article)
    later = ukrf.amendments_after(params.article, params.crime_date) if params.crime_date else []
    if params.crime_date and history.get("current_redaction") is not None:
        edition_status = ("edition_changed_after_crime_date" if later
                          else "no_known_amendments_after_crime_date")
    else:
        edition_status = "unverified_for_crime_date"
    stats["edition"] = {
        "crime_date": params.crime_date,
        "current_redaction": history.get("current_redaction"),
        "history_partial": True,
        "known_amendments_after_crime_date": [{"date": a["date"], "changed_rows": len(a["changes"])} for a in later],
        "status": edition_status,
        "sanction_reconstruction": edition_sanction,
        "limitation": "Источник отдаёт только последние правки статьи; полная история редакций с 1996 года не собрана.",
    }
    result = {"case_id":case_id, "masked_text":masked, "parameters":to_dict(params), "check":to_dict(check),
              "similar":[to_dict(x) for x in similar], "stats":stats,
              "conclusion":to_dict(conclusion.build(params, check, similar, stats)),
              "privacy":{"mode":mode, "external_model_calls":False,
                         "masking_guarantee":False, "history_contains_full_text":False,
                         "warning":"Эвристическое маскирование не гарантирует обезличивание. Демонстрация предназначена для синтетических данных."},
              "provenance":{"pipeline_version":"2.2-release-review", "law_version_status":edition_status,
                            "law_history_partial":True,
                            "sanctions_sha256":hashlib.sha256(config.UKRF_SANCTIONS_PATH.read_bytes()).hexdigest() if config.UKRF_SANCTIONS_PATH.exists() else None}}
    if mode == "parameter_recheck":
        result["privacy"]["warning"] = "Ручные параметры и контекст не проверены по документу; результат не сохраняется в истории."
        result["provenance"]["mode"] = "recheck"
    return result


def run_parameters(params) -> dict:
    """Пересчёт по явно заданным параметрам без документа и анонимизации.

    Используется веб-эндпоинтом /api/recheck: человек уточнил факты вручную,
    система пересчитывает проверку и статистику. Текст документа отсутствует,
    поэтому privacy-гарантии по masked_text выполняются по построению.
    """
    from .checker import CONTEXT_KEYS
    params = copy.deepcopy(params)
    params.masked_text = ""
    params.review_flags = list(dict.fromkeys([*params.review_flags, "TEXT_DEPENDENT_RULES_NOT_RECHECKED"]))
    if any(not isinstance(params.rule_context.get(key), bool) for key in CONTEXT_KEYS):
        params.review_flags = list(dict.fromkeys([*params.review_flags, "PARAMETER_CONTEXT_INCOMPLETE"]))
    return _run_parameters(params, "", "parameter_recheck")


def minimized(payload: dict) -> dict:
    """Structured handoff without source text, search snippets, dates or filename."""
    result = copy.deepcopy(payload)
    result["masked_text"] = ""
    parameters = result.get("parameters", {})
    parameters["masked_text"] = ""
    parameters["evidence"] = {}
    parameters["crime_date"] = None
    for location in (result.get("similar", []), result.get("conclusion", {}).get("similar", [])):
        for item in location:
            item["summary"] = ""
    # Дата деяния — факт дела: в минимизированной истории её быть не должно.
    # stats дублируется внутри conclusion — чистим обе копии.
    for stats_copy in (result.get("stats"), (result.get("conclusion") or {}).get("stats")):
        edition = (stats_copy or {}).get("edition")
        if isinstance(edition, dict):
            edition["crime_date"] = None
    concl = result.get("conclusion") or {}
    deeper = concl.get("deeper_analysis") or []
    concl["deeper_analysis"] = [
        s for s in deeper
        if not (isinstance(s, str) and s.startswith("Дата преступления:"))
    ]
    result.setdefault("privacy", {})["projection"] = "minimal_structured_report"
    return result
