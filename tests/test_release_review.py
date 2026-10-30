"""Regressions found after the DeepSeek handoff; isolated API data."""
import copy
import json
import shutil
from pathlib import Path
import pytest
from app import checker, config, pipeline, ukrf
from app.schemas import CaseParameters, PersonInfo
from tools.evaluate_extractor import evaluate
from tests.test_api import client, _auth, _login


def params(**kwargs):
    defaults = dict(case_id="REG", article="158", part="2", punishment_type="лишение свободы", punishment_years=3)
    defaults.update(kwargs)
    return CaseParameters(**defaults)


def codes(result):
    return {v.code for v in result.violations if v.level == "ошибка"}


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
@pytest.mark.parametrize("field", ["probation_years", "probation_months"])
def test_probation_rejects_invalid_values(field, value):
    p = params(**{field: value})
    r = checker.check(p, ukrf.get_sanction("158", "2"))
    assert r.ok is None and r.status == "incomplete"
    assert any("INVALID_PARAMETER" in w for w in r.warnings)


def test_minor_fine_does_not_use_adult_limits():
    p = params(punishment_type="штраф", fine_rub=2000, person=PersonInfo(is_minor=True))
    r = checker.check(p, ukrf.get_sanction("158", "2"))
    assert not codes(r)
    assert r.status == "incomplete"


def test_unknown_age_does_not_prove_adult_fine_violation():
    r = checker.check(params(punishment_type="штраф", fine_rub=2000), ukrf.get_sanction("158", "2"))
    assert not codes(r) and r.ok is None


def test_article_64_does_not_erase_adult_general_minimum():
    p = params(punishment_type="штраф", fine_rub=2000, person=PersonInfo(is_minor=False), masked_text="Применена ст. 64 УК РФ")
    assert "FINE_BELOW_GENERAL_MIN" in codes(checker.check(p, ukrf.get_sanction("158", "2")))


@pytest.mark.parametrize("text,episodes", [
    ("По совокупности приговоров ст. 70 УК РФ", ["158~2", "161~1"]),
    ("По совокупности преступлений", ["158~2", "999~1"]),
    ("По совокупности преступлений", ["158~2", "105~?"]),
    ("По совокупности преступлений", ["158~2"]),
    ("", ["158~2", "161~1"]),
])
def test_unknown_aggregate_never_uses_known_subset_as_legal_cap(text, episodes):
    p = params(punishment_years=9, masked_text=text, review_flags=["AGGREGATE_SENTENCE"], mentioned_articles=episodes)
    r = checker.check(p, ukrf.get_sanction("158", "2"))
    assert "AGGREGATE_OVER_1_5" not in codes(r)
    assert "aggregate_1_5_max" not in r.limits
    assert r.ok is None


def test_aggregate_56_exceptions_not_declared_impossible():
    p = params(punishment_years=32, masked_text="совокупности приговоров", review_flags=["AGGREGATE_SENTENCE"])
    r = checker.check(p, ukrf.get_sanction("158", "2"))
    assert not codes(r) and r.ok is None


def test_reached_14_does_not_mean_younger_than_14():
    p = params(article="131", part="2", punishment_years=4, probation=True,
               masked_text="Потерпевшая достигла четырнадцатилетнего возраста")
    assert "PROBATION_SEX_MINOR" not in codes(checker.check(p, ukrf.get_sanction("131", "2")))


def test_part_specific_probation_ban():
    assert "PROBATION_FORBIDDEN_ARTICLE" not in codes(checker.check(params(article="281.3", part="1", probation=True), None))
    r = checker.check(params(article="281.3", part="2", probation=True), None)
    assert "PROBATION_FORBIDDEN_ARTICLE" in codes(r) and r.ok is False and r.status == "issues"


def test_probation_without_main_term_does_not_choose_three_year_max():
    p = params(punishment_years=None, probation=True, probation_years=4)
    r = checker.check(p, ukrf.get_sanction("158", "2"))
    assert "PROBATION_TERM_ABOVE_MAX" not in codes(r)
    assert r.ok is None


def test_previous_udo_mention_is_not_proof_of_new_offence_during_udo():
    p = params(article="105", part="1", punishment_years=7, probation=True, probation_years=3,
               masked_text="В прошлом применялось условно-досрочное освобождение.")
    r = checker.check(p, ukrf.get_sanction("105", "1"))
    assert "PROBATION_DURING_PROBATION" not in codes(r)
    assert r.ok is None


def test_metric_rejects_silent_unknown_field():
    with pytest.raises(ValueError, match="unknown"):
        evaluate({"cases": [{"id":"BAD", "text":"", "expected":{"years":99}}]})


def test_metric_actually_measures_sentence_and_exposes_denominator():
    report = evaluate({"cases": [{"id":"BAD", "text":"Лишение свободы сроком 2 года.", "expected":{"punishment_years":99}}]})
    assert report["field_counts"]["punishment_years"] == {"ok":0,"total":1}
    assert report["failed_cases"][0]["failures"][0]["field"] == "punishment_years"
    assert report["field_accuracy"]["probation_months"] is None


def test_api_recheck_preserves_context_and_date(client):
    for name in ("law_history.json", "law_versions.json"):
        shutil.copy2(config.BASE_DIR / "data" / name, config.DATA_DIR / name)
    headers = _auth(_login(client))
    p = params(masked_text="Дело рассмотрено в особом порядке.", mitigating=["явка_с_повинной"])
    context = checker.rule_context(p)
    r = client.post("/api/recheck", headers=headers, json={
        "article":"158", "part":"2", "punishment_type":"лишение свободы", "punishment_years":3,
        "mitigating":["явка_с_повинной"], "rule_context":context})
    assert r.status_code == 200
    assert "CAP_62_5" in {v["code"] for v in r.json()["check"]["violations"]}
    r = client.post("/api/recheck", headers=headers, json={
        "article":"264", "part":"4", "punishment_type":"лишение свободы", "punishment_years":10,
        "crime_date":"01.01.2018", "rule_context":context})
    assert r.status_code == 200
    assert r.json()["check"]["limits"]["sanction_max_years"] == 7
    assert r.json()["stats"]["edition"]["crime_date"] == "01.01.2018"


@pytest.mark.parametrize("extra", [{"probation_months":-1}, {"crime_date":"31.02.2024"}])
def test_api_rejects_invalid_recheck(client, extra):
    response = client.post("/api/recheck", headers=_auth(_login(client)), json={
        "article":"158", "part":"2", "punishment_type":"лишение свободы", **extra})
    assert response.status_code in (400, 422)


def test_missing_history_is_not_reported_as_known_unchanged(client):
    payload = pipeline.run("Дата совершения преступления: 01.01.2025. Признан виновным по ч. 1 ст. 999 УК РФ. Лишение свободы сроком 2 года.")
    assert payload["stats"]["edition"]["status"] == "unverified_for_crime_date"
