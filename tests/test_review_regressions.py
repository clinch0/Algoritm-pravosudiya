"""Counterexamples found during the 28.10.2026 review. No network access."""
import json
import math
from pathlib import Path
import pytest
from app import config, ukrf
from app.anonymizer import mask_text
from app.checker import check
from app.extractor import extract, extract_crime_date
from app.schemas import CaseParameters, PersonInfo, Sanction
from app.rag import CaseStore
from app.pipeline import minimized


def p(**kwargs):
    return CaseParameters(case_id="REGRESSION", article="158", part="2",
                          punishment_type="лишение свободы", **kwargs)


def test_unknown_part_is_not_replaced():
    assert ukrf.get_sanction("158", "99") is None


def test_cache_tracks_data_path(tmp_path, monkeypatch):
    assert ukrf.get_sanction("158", "2") is not None
    monkeypatch.setattr(config, "UKRF_SANCTIONS_PATH", tmp_path / "missing.json")
    assert ukrf.get_sanction("158", "2") is None


def test_missing_sanction_abstains():
    r = check(p(punishment_years=2), None)
    assert r.ok is None and r.status == "incomplete"


def test_missing_term_abstains():
    r = check(p(), ukrf.get_sanction("158", "2"))
    assert r.ok is None and r.status == "incomplete"


@pytest.mark.parametrize("value", [-1, float('nan'), float('inf'), True])
def test_invalid_numbers_abstain(value):
    r = check(p(punishment_years=value), ukrf.get_sanction("158", "2"))
    assert r.ok is None and r.status == "incomplete"


def test_reverse_article_order():
    result = extract("ст. 158 ч. 2 УК РФ, лишение свободы сроком 2 года", "T")
    assert (result.article, result.part) == ("158", "2")


def test_general_part_not_qualification():
    result = extract("ч. 3 ст. 30 УК РФ, ч. 2 ст. 158 УК РФ", "T")
    assert result.article == "158" and result.stage == "покушение"


@pytest.mark.parametrize("text", ["рецидив отсутствует", "рецидив не установлен", "не усматривается рецидив"])
def test_negated_recidivism(text):
    result = extract("ч. 2 ст. 158 УК РФ. " + text, "T")
    assert "рецидив" not in result.aggravating
    assert result.person.recidivism is None


def test_negated_compensation():
    assert "возмещение_ущерба" not in extract("Подсудимый не возместил ущерб.", "T").mitigating


def test_minor_victim_not_minor_defendant():
    assert not extract("Подсудимый осужден. Несовершеннолетний потерпевший допрошен.", "T").person.is_minor


def test_intoxication_not_automatically_aggravating():
    result = extract("Подсудимый находился в состоянии алкогольного опьянения.", "T")
    assert "опьянение" not in result.aggravating
    assert "AGGRAVATING_REQUIRES_CONFIRMATION" in result.review_flags


def test_operative_part_wins():
    result = extract("Прокурор просил лишения свободы сроком 6 лет. ПРИГОВОРИЛ: назначить лишение свободы сроком 2 года.", "T")
    assert result.punishment_years == 2


def test_crime_date_not_birth_date():
    assert extract_crime_date("01.01.1990 года рождения. Преступление совершено 12.03.2024.") == "12.03.2024"
    assert extract_crime_date("Приговор 12.03.2024. 01.01.1990 года рождения") is None
    assert extract_crime_date("Преступление совершено 31.02.2024.") is None


@pytest.mark.parametrize("text", ["Иванов Петр Сергеевич признан виновным.", "А.А. Иванов признан виновным.", "Иванов А. А. признан виновным."])
def test_name_at_start_and_initials(text):
    assert "Иванов" not in mask_text(text)


def test_agreement_requires_conditions():
    result = check(p(punishment_years=4, aggravating=["рецидив"], masked_text="Заключено досудебное соглашение."), ukrf.get_sanction("158", "2"))
    assert "cap_62_2" not in result.limits
    assert result.status == "incomplete"


def test_negated_64_does_not_allow_below_minimum():
    result = check(CaseParameters(case_id="T", article="105", part="1", punishment_type="лишение свободы", punishment_years=4, masked_text="Оснований для применения ст. 64 УК РФ не установлено."), ukrf.get_sanction("105", "1"))
    assert any(v.code == "BELOW_MIN" for v in result.violations)


def test_attempt_with_life_sanction_has_finite_cap():
    params = CaseParameters(case_id="T", article="105", part="2", punishment_type="лишение свободы", punishment_years=16, stage="покушение")
    r = check(params, ukrf.get_sanction("105", "2"))
    assert r.limits["effective_max"] == 15
    assert any(v.code == "CAP_66_ATT" for v in r.violations)


def test_special_cap_below_minimum_no_64_required():
    sanction = Sanction(article="999", part="1", label="искусственный тест арифметики", category="тяжкое", punishment_types=["лишение свободы"], imprisonment_min_years=10, imprisonment_max_years=15)
    params = CaseParameters(case_id="T", article="999", part="1", punishment_type="лишение свободы", punishment_years=7, stage="приготовление")
    r = check(params, sanction)
    assert not any(v.code == "BELOW_MIN" for v in r.violations)
    assert any(v.code == "BELOW_MIN_SPECIAL_CAP" for v in r.violations)


def test_recidivism_base_uses_stage():
    r = check(p(punishment_years=1.4, stage="покушение", person=PersonInfo(recidivism="простой")), ukrf.get_sanction("158", "2"))
    assert r.limits["recidivism_min_1_3_max"] == pytest.approx(1.25)


def test_aggregate_abstains():
    params = extract("ч. 2 ст. 158 УК РФ. По совокупности приговоров назначить лишение свободы сроком 6 лет.", "T")
    r = check(params, ukrf.get_sanction(params.article, params.part))
    assert r.status == "incomplete" and not r.violations


def test_trace_reproduces_exact_limit():
    r = check(p(punishment_years=2, mitigating=["явка_с_повинной"], masked_text="Дело рассмотрено в особом порядке."), ukrf.get_sanction("158", "2"))
    assert r.trace[-1]["cap_years"] == pytest.approx(20/9)
    assert r.trace[-1]["base_years"] * r.trace[-1]["factor"] == r.limits["effective_max"]


def test_retrieval_one_document_and_part_filter(tmp_path):
    data=[{"id":"A", "article":"158", "part":"2", "punishment_type":"лишение свободы", "years":1, "text":"тайное хищение имущества"},
          {"id":"B", "article":"158", "part":"3", "punishment_type":"лишение свободы", "years":3, "text":"хищение"}]
    fixture=tmp_path/'cases.json'; fixture.write_text(json.dumps(data), encoding='utf-8')
    with CaseStore(str(tmp_path/'cases.sqlite')) as store:
        store.load_cases(str(fixture))
        assert [x.id for x in store.search("хищение", article="158", part="2")] == ["A"]
        assert not store.search("космонавт", article="158", part="2")
        with pytest.raises(ValueError): store.search("хищение", top_k=-1)


def test_minimal_projection_copies_and_redacts():
    original={"masked_text":"leak", "parameters":{"masked_text":"leak","evidence":{"quote":"leak"},"crime_date":"12.03.2024"},"similar":[{"summary":"leak"}],"conclusion":{"similar":[{"summary":"leak"}]}}
    result=minimized(original)
    assert "leak" not in json.dumps(result)
    assert original["masked_text"] == "leak"


def test_mcp_denies_other_files(tmp_path):
    from mcp_server.server import analyze_document
    path=tmp_path/'private.txt'; path.write_text("не читать", encoding='utf-8')
    assert "error" in analyze_document(str(path))


def test_mcp_builtin_projection():
    from mcp_server.server import analyze_document
    result=analyze_document(str(config.BASE_DIR/'samples'/'приговор_пример_ok.docx'))
    assert "error" not in result
    assert result["masked_text"] == "" and not result["parameters"]["evidence"]
    assert "official" in result["stats"]
