"""Тесты частичной истории редакций статей (data/law_history.json)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import pipeline, ukrf


def test_law_history_present():
    h = ukrf.law_history("264")
    assert h.get("current_redaction")
    assert isinstance(h.get("amendments"), list)


def test_amendments_after_2020_for_264():
    later = ukrf.amendments_after("264", "01.01.2020")
    dates = [a["date"] for a in later]
    assert "09.08.2022" in dates          # 264 изменялась 09.08.2022
    assert not any(d <= "01.01.2020" for d in dates)


def test_no_amendments_after_2024_for_264():
    assert ukrf.amendments_after("264", "01.01.2024") == []


def test_amendments_after_requires_valid_date():
    assert ukrf.amendments_after("264", "не дата") == []
    assert ukrf.amendments_after(None, "01.01.2020") == []


def test_pipeline_edition_risk_flag():
    text = ("Дата совершения преступления: 01.01.2020. "
            "Признан виновным по ч. 2 ст. 264 УК РФ. "
            "Назначено наказание в виде лишения свободы сроком на 4 года.")
    payload = pipeline.run(text)
    ed = payload["stats"]["edition"]
    assert ed["crime_date"] == "01.01.2020"
    assert ed["status"] == "edition_changed_after_crime_date"
    assert any(a["date"] == "09.08.2022" for a in ed["known_amendments_after_crime_date"])
    assert any("изменялась после этой даты" in s for s in payload["conclusion"]["deeper_analysis"])
    assert payload["provenance"]["law_version_status"] == "edition_changed_after_crime_date"


def test_pipeline_no_known_amendments_after():
    text = ("Дата совершения преступления: 01.01.2025. "
            "Признан виновным по ч. 2 ст. 264 УК РФ. "
            "Назначено наказание в виде лишения свободы сроком на 4 года.")
    payload = pipeline.run(text)
    assert payload["stats"]["edition"]["status"] == "no_known_amendments_after_crime_date"


def test_pipeline_without_crime_date():
    text = "Признан виновным по ч. 2 ст. 264 УК РФ. Лишение свободы сроком на 4 года."
    payload = pipeline.run(text)
    assert payload["stats"]["edition"]["status"] == "unverified_for_crime_date"


def test_sanction_for_date_before_2019_264_4():
    # до 09.07.2019 ч. 4 ст. 264: лишение свободы от 2 до 7 лет
    s, info = ukrf.sanction_for_date("264", "4", "01.01.2018")
    assert s is not None
    assert s.imprisonment_min_years == 2
    assert s.imprisonment_max_years == 7
    assert info["status"] == "reconstructed_partial"


def test_sanction_for_date_after_2019_264_4():
    # после 09.07.2019 — текущая редакция: 5–12 лет
    s, info = ukrf.sanction_for_date("264", "4", "01.01.2020")
    assert s.imprisonment_min_years == 5
    assert s.imprisonment_max_years == 12
    assert info["status"] == "current_edition"


def test_sanction_for_date_no_history_158():
    # у 158 известных изменений санкции нет — текущая редакция
    s, info = ukrf.sanction_for_date("158", "2", "01.01.2010")
    assert s.imprisonment_max_years == 5
    assert info["status"] == "current_edition"


def test_sanction_for_date_invalid_date():
    s, info = ukrf.sanction_for_date("264", "4", "не дата")
    assert s.imprisonment_max_years == 12
    assert info["status"] == "current_edition"


def test_pipeline_checks_against_edition_sanction():
    # 10 лет по ч. 4 ст. 264 при дате деяния 01.01.2018: максимум тогда 7 лет
    text = ("Дата совершения преступления: 01.01.2018. "
            "Признан виновным по ч. 4 ст. 264 УК РФ. "
            "Назначено наказание в виде лишения свободы сроком на 10 лет.")
    payload = pipeline.run(text)
    codes = {v["code"] for v in payload["check"]["violations"]}
    assert "OUT_OF_RANGE_MAX" in codes
    rec = payload["stats"]["edition"]["sanction_reconstruction"]
    assert rec["status"] == "reconstructed_partial"
    assert any("реконструированной редакции" in s for s in payload["conclusion"]["deeper_analysis"])


def test_pipeline_current_edition_for_recent_date():
    # тот же срок, но деяние 01.01.2020: действует 5–12, превышения нет
    text = ("Дата совершения преступления: 01.01.2020. "
            "Признан виновным по ч. 4 ст. 264 УК РФ. "
            "Назначено наказание в виде лишения свободы сроком на 10 лет.")
    payload = pipeline.run(text)
    codes = {v["code"] for v in payload["check"]["violations"]}
    assert "OUT_OF_RANGE_MAX" not in codes
