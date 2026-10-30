"""Тесты проверки наказания (app/checker.py)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.checker import check
from app.schemas import CaseParameters, PersonInfo
from app.ukrf import get_sanction


def params_of(**kw):
    p = CaseParameters(case_id="TEST-1", masked_text=kw.pop("text", ""))
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def test_out_of_range_max():
    s = get_sanction("158", "2")  # до 5 лет
    p = params_of(article="158", part="2", punishment_type="лишение свободы", punishment_years=6)
    r = check(p, s)
    assert not r.ok
    assert any(v.code == "OUT_OF_RANGE_MAX" for v in r.violations)


def test_62_part1_cap():
    s = get_sanction("158", "2")  # max 5 → 2/3 = 3.33
    p = params_of(article="158", part="2", punishment_type="лишение свободы", punishment_years=3,
                  mitigating=["явка_с_повинной"])
    r = check(p, s)
    assert r.ok
    p2 = params_of(article="158", part="2", punishment_type="лишение свободы", punishment_years=4,
                   mitigating=["явка_с_повинной"])
    r2 = check(p2, s)
    assert not r2.ok
    assert any(v.code == "CAP_62_1" for v in r2.violations)


def test_recidivism_min_third():
    s = get_sanction("158", "2")  # 1/3 * 5 = 1.67
    p = params_of(article="158", part="2", punishment_type="лишение свободы", punishment_years=0.5,
                  person=PersonInfo(recidivism="простой"))
    r = check(p, s)
    assert not r.ok
    assert any(v.code == "RECIDIVISM_MIN" for v in r.violations)


def test_recidivism_with_mitigating_is_info():
    s = get_sanction("158", "2")
    p = params_of(article="158", part="2", punishment_type="лишение свободы", punishment_years=0.5,
                  person=PersonInfo(recidivism="простой"), mitigating=["признание_вины"])
    r = check(p, s)
    assert any(v.code == "RECIDIVISM_MIN_MITIGATING" for v in r.violations)


def test_probation_dangerous_recidivism():
    s = get_sanction("158", "2")
    p = params_of(article="158", part="2", punishment_type="лишение свободы", punishment_years=2,
                  probation=True, person=PersonInfo(recidivism="опасный"))
    r = check(p, s)
    assert not r.ok
    assert any(v.code == "PROBATION_RECIDIVISM" for v in r.violations)


def test_minor_max_10():
    s = get_sanction("158", "4")  # до 10
    p = params_of(article="158", part="4", punishment_type="лишение свободы", punishment_years=12,
                  person=PersonInfo(is_minor=True))
    r = check(p, s)
    assert not r.ok
    assert any(v.code == "MINOR_MAX_10" for v in r.violations)


def test_below_min_needs_64():
    s = get_sanction("105", "1")  # 6–15
    p = params_of(article="105", part="1", punishment_type="лишение свободы", punishment_years=4)
    r = check(p, s)
    assert not r.ok
    assert any(v.code == "BELOW_MIN" for v in r.violations)
    p2 = params_of(article="105", part="1", punishment_type="лишение свободы", punishment_years=4,
                   text="наказание назначено с применением ст. 64 УК РФ, ниже низшего предела")
    r2 = check(p2, s)
    assert any(v.code == "BELOW_MIN_64" for v in r2.violations)


def test_66_attempt_cap():
    s = get_sanction("105", "1")  # 6–15; 3/4 * 15 = 11.25
    p = params_of(article="105", part="1", punishment_type="лишение свободы", punishment_years=12,
                  stage="покушение")
    r = check(p, s)
    assert not r.ok
    assert any(v.code == "CAP_66_ATT" for v in r.violations)


def test_fine_limits():
    s = get_sanction("158", "1")  # 5–80 тыс.
    p = params_of(article="158", part="1", person=PersonInfo(is_minor=False), punishment_type="штраф", fine_rub=100000)
    r = check(p, s)
    assert not r.ok
    assert any(v.code == "FINE_MAX" for v in r.violations)
    p2 = params_of(article="158", part="1", person=PersonInfo(is_minor=False), punishment_type="штраф", fine_rub=40000)
    assert check(p2, s).ok


def test_56_general_max_20():
    s = get_sanction("105", "2")  # 8–20 + пожизненное
    p = params_of(article="105", part="2", punishment_type="лишение свободы", punishment_years=21)
    r = check(p, s)
    assert any(v.code in ("GENERAL_MAX_20", "OUT_OF_RANGE_MAX") for v in r.violations)


def test_62_5_special_order_cap():
    # Особый порядок (гл. 40 УПК): потолок 2/3 от 5 = 3.33 (ч. 5 ст. 62 УК РФ)
    s = get_sanction("158", "2")
    p = params_of(article="158", part="2", punishment_type="лишение свободы", punishment_years=4,
                  text="дело рассмотрено в особом порядке (глава 40 УПК РФ)")
    r = check(p, s)
    assert not r.ok
    assert any(v.code == "CAP_62_5" for v in r.violations)
    assert r.limits["cap_62_5"] == pytest.approx(10 / 3, abs=1e-6)


def test_62_1_plus_62_5_sequential():
    # п. «и» ч. 1 ст. 61 + особый порядок: 2/3 от 2/3 = 4/9 от 5 = 2.222
    s = get_sanction("158", "2")
    p = params_of(article="158", part="2", punishment_type="лишение свободы", punishment_years=2.3,
                  mitigating=["явка_с_повинной"],
                  text="дело рассмотрено в особом порядке (глава 40 УПК РФ)")
    r = check(p, s)
    assert not r.ok
    assert any(v.code == "CAP_62_5" for v in r.violations)
    assert r.limits["effective_max"] == pytest.approx(5 * 4 / 9, abs=1e-6)


def test_62_1_plus_62_5_within_limit():
    s = get_sanction("158", "2")
    p = params_of(article="158", part="2", punishment_type="лишение свободы", punishment_years=1.5,
                  mitigating=["явка_с_повинной"],
                  text="дело рассмотрено в особом порядке (глава 40 УПК РФ)")
    r = check(p, s)
    assert r.ok


def test_226_9_reduced_inquiry_half():
    s = get_sanction("158", "2")
    p = params_of(article="158", part="2", punishment_type="лишение свободы", punishment_years=3,
                  text="дознание в сокращенной форме (ст. 226.9 УПК РФ)")
    r = check(p, s)
    assert not r.ok
    assert any(v.code == "CAP_62_5_226_9" for v in r.violations)
    assert r.limits["cap_62_5_226_9"] == pytest.approx(2.5, abs=1e-6)


def test_probation_over_8_years():
    s = get_sanction("105", "1")  # 6–15
    p = params_of(article="105", part="1", punishment_type="лишение свободы", punishment_years=9,
                  probation=True)
    r = check(p, s)
    assert not r.ok
    assert any(v.code == "PROBATION_OVER_8" for v in r.violations)


def test_probation_term_above_max_for_long_sentence():
    # ЛС свыше 1 года → испытательный срок не более 5 лет (ч. 3 ст. 73 УК РФ)
    s = get_sanction("158", "2")
    p = params_of(article="158", part="2", punishment_type="лишение свободы", punishment_years=2,
                  probation=True, probation_years=6)
    r = check(p, s)
    assert not r.ok
    assert any(v.code == "PROBATION_TERM_ABOVE_MAX" for v in r.violations)


def test_probation_term_below_min():
    s = get_sanction("158", "2")
    p = params_of(article="158", part="2", punishment_type="лишение свободы", punishment_years=3,
                  probation=True, probation_months=3)
    r = check(p, s)
    assert not r.ok
    assert any(v.code == "PROBATION_TERM_BELOW_MIN" for v in r.violations)


def test_probation_term_cap_3_years_for_short_sentence():
    # ЛС до 1 года включительно → испытательный срок не более 3 лет (ч. 3 ст. 73 УК РФ)
    s = get_sanction("158", "2")
    p = params_of(article="158", part="2", punishment_type="лишение свободы", punishment_years=1,
                  probation=True, probation_years=4)
    r = check(p, s)
    assert not r.ok
    assert any(v.code == "PROBATION_TERM_ABOVE_MAX" for v in r.violations)


def test_probation_term_ok():
    s = get_sanction("158", "2")
    p = params_of(article="158", part="2", punishment_type="лишение свободы", punishment_years=1.5,
                  probation=True, probation_years=2)
    r = check(p, s)
    assert not any(v.code.startswith("PROBATION_TERM") for v in r.violations)


def test_minor_unknown_does_not_flag_article_88():
    # is_minor=None (не установлено) не должен включать предупреждение о ст. 88
    s = get_sanction("158", "2")
    p = params_of(article="158", part="2", punishment_type="лишение свободы", punishment_years=2)
    r = check(p, s)
    assert not any("Статья 88 реализована частично" in w for w in r.warnings)


def test_aggregate_cap_1_5():
    # совокупность 158 ч.2 (макс 5) + 161 ч.1 (макс 4): потолок 1.5 × 5 = 7.5
    s = get_sanction("158", "2")
    p = params_of(article="158", part="2", punishment_type="лишение свободы", punishment_years=9,
                  review_flags=["AGGREGATE_SENTENCE"], mentioned_articles=["158~2", "161~1"],
                  text="по совокупности преступлений")
    r = check(p, s)
    assert any(v.code == "AGGREGATE_OVER_1_5" for v in r.violations)
    p2 = params_of(article="158", part="2", punishment_type="лишение свободы", punishment_years=6,
                   review_flags=["AGGREGATE_SENTENCE"], mentioned_articles=["158~2", "161~1"],
                  text="по совокупности преступлений")
    r2 = check(p2, s)
    assert not any(v.code == "AGGREGATE_OVER_1_5" for v in r2.violations)
    assert r2.ok is None  # неполный расчёт совокупности остаётся incomplete


def test_aggregate_no_single_sanction_comparison():
    # 6 лет по совокупности не сравниваются с санкцией одного эпизода (5 лет)
    s = get_sanction("158", "2")
    p = params_of(article="158", part="2", punishment_type="лишение свободы", punishment_years=6,
                  review_flags=["AGGREGATE_SENTENCE"], mentioned_articles=["158~2", "161~1"],
                  text="по совокупности преступлений")
    r = check(p, s)
    assert not any(v.code == "OUT_OF_RANGE_MAX" for v in r.violations)


def test_minor_half_min_88_6_1():
    # несовершеннолетний, тяжкое преступление (131 ч.2, мин 4): нижний предел 2 года
    s = get_sanction("131", "2")
    p = params_of(article="131", part="2", punishment_type="лишение свободы", punishment_years=1,
                  person=PersonInfo(is_minor=True))
    r = check(p, s)
    assert any(v.code == "MINOR_BELOW_HALF_MIN" for v in r.violations)
    p2 = params_of(article="131", part="2", punishment_type="лишение свободы", punishment_years=3,
                   person=PersonInfo(is_minor=True))
    assert not any(v.code == "MINOR_BELOW_HALF_MIN" for v in check(p2, s).violations)


def test_fine_below_general_min_46():
    s = get_sanction("158", "1")
    p = params_of(article="158", part="1", person=PersonInfo(is_minor=False), punishment_type="штраф", fine_rub=1000)
    r = check(p, s)
    assert any(v.code == "FINE_BELOW_GENERAL_MIN" for v in r.violations)


def test_probation_forbidden_article_a1():
    # ст. 205.2 нет в базе — запрет должен сработать и без санкции
    p = params_of(article="205.2", part="1", punishment_type="лишение свободы", punishment_years=3,
                  probation=True)
    r = check(p, None)
    assert any(v.code == "PROBATION_FORBIDDEN_ARTICLE" for v in r.violations)


def test_probation_sex_minor_a():
    s = get_sanction("131", "2")
    p = params_of(article="131", part="2", punishment_type="лишение свободы", punishment_years=4,
                  probation=True, text="совершено в отношении лица, не достигшего четырнадцатилетнего возраста")
    r = check(p, s)
    assert any(v.code == "PROBATION_SEX_MINOR" for v in r.violations)


def test_probation_during_probation_b():
    s = get_sanction("105", "1")  # особо тяжкое
    p = params_of(article="105", part="1", punishment_type="лишение свободы", punishment_years=7,
                  probation=True, text="совершил преступление в период испытательного срока")
    r = check(p, s)
    assert any(v.code == "PROBATION_DURING_PROBATION" for v in r.violations)
