"""Тесты экстрактора параметров (app/extractor.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.extractor import extract

TEXT = """
Приговором Ленинского районного суда от 15.03.2026 по делу № 1-234/2026
гражданин А. признан виновным в совершении преступления, предусмотренного ч. 2 ст. 158 УК РФ.
Судом установлены смягчающие обстоятельства: явка с повинной, активное способствование раскрытию
преступления, добровольное возмещение ущерба, наличие малолетних детей.
Отягчающих обстоятельств не установлено. Ранее не судим.
Назначено наказание в виде лишения свободы сроком на 2 года 6 месяцев условно
с испытательным сроком 3 года.
"""


def test_article_and_part():
    p = extract(TEXT, "C-1")
    assert p.article == "158"
    assert p.part == "2"


def test_punishment():
    p = extract(TEXT, "C-1")
    assert p.punishment_type == "лишение свободы"
    assert p.punishment_years == 2
    assert p.punishment_months == 6
    assert p.probation is True


def test_mitigating():
    p = extract(TEXT, "C-1")
    assert "явка_с_повинной" in p.mitigating
    assert "активное_способствование" in p.mitigating
    assert "возмещение_ущерба" in p.mitigating
    assert "малолетние_дети" in p.mitigating
    assert p.aggravating == []


def test_first_offense_and_gender():
    p = extract(TEXT, "C-1")
    assert p.person.first_offense is True
    assert p.person.gender == "мужской"


def test_release_grounds():
    p = extract("Суд прекратил дело с назначением судебного штрафа в порядке ст. 76.2 УК РФ.", "C-2")
    assert "76.2" in p.release_grounds


def test_fine():
    p = extract("Признан виновным по ч. 1 ст. 158 УК РФ, назначен штраф в размере 30 000 рублей.", "C-3")
    assert p.punishment_type == "штраф"
    assert p.fine_rub == 30000


def test_probation_term():
    text = ("Признан виновным по ч. 2 ст. 158 УК РФ, назначено наказание в виде лишения свободы "
            "сроком на 1 год 6 месяцев, на основании ст. 73 УК РФ считать условным "
            "с испытательным сроком 2 года.")
    p = extract(text, "C-4")
    assert p.probation is True
    assert p.probation_years == 2


def test_probation_term_months():
    p = extract("Лишение свободы сроком на 1 год условно с испытательным сроком на 1 год 6 месяцев.", "C-5")
    assert p.probation is True
    assert p.probation_years == 1
    assert p.probation_months == 6


def test_minor_unknown_by_default():
    p = extract("Признан виновным по ч. 1 ст. 158 УК РФ.", "C-6")
    assert p.person.is_minor is None


def test_word_number_sentence():
    p = extract("Лишение свободы сроком на один год шесть месяцев.", "C-7")
    assert p.punishment_type == "лишение свободы"
    assert p.punishment_years == 1
    assert p.punishment_months == 6


def test_word_number_years_only():
    p = extract("Назначено наказание в виде лишения свободы сроком на два года.", "C-8")
    assert p.punishment_type == "лишение свободы"
    assert p.punishment_years == 2
    assert p.punishment_months is None


def test_word_number_probation_term():
    p = extract("Лишение свободы сроком на один год условно с испытательным сроком один год.", "C-9")
    assert p.probation is True
    assert p.probation_years == 1


def test_works_type_nominative():
    p = extract("Назначено наказание в виде 1 года исправительных работ.", "C-10")
    assert p.punishment_type == "исправительные работы"
    assert p.punishment_years == 1


def test_minor_via_is_yavlyaetsya():
    p = extract("Подсудимый является несовершеннолетним. ч. 2 ст. 158 УК РФ, лишение свободы 2 года.", "C-11")
    assert p.person.is_minor is True
    assert "несовершеннолетний_виновный" in p.mitigating


def test_aggregate_first_article_preferred():
    p = extract("Признан виновным по ч. 2 ст. 158 и ч. 1 ст. 161 УК РФ. Лишение свободы 5 лет.", "C-12")
    assert p.article == "158"
    assert p.part == "2"
    assert "MULTIPLE_ARTICLES" in p.review_flags
    assert "158~2" in p.mentioned_articles
    assert "161~1" in p.mentioned_articles
