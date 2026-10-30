"""Тесты официальной статистики Судебного департамента при ВС РФ."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import official_stats


def test_get_158_2():
    d = official_stats.get("158", "2")
    assert d is not None
    assert d["всего_осуждено"] > 30000
    assert d["лишение_свободы"] > 0
    assert d["условно_лс"] > 0


def test_shares_sum_sane():
    sh = official_stats.shares("158", "2")
    assert sh["лишение_свободы"] > 20
    assert sh["условно_лс"] > 10
    total = sum(sh.values())
    assert 40 < total < 100  # доли только по основным видам наказаний


def test_get_105_1_mostly_prison():
    d = official_stats.get("105", "1")
    assert d["лишение_свободы"] / d["всего_осуждено"] > 0.9  # по убийству — практически всегда ЛС


def test_summary_text_russian():
    t = official_stats.summary_text("158", "2")
    assert "Судебного департамента" in t
    assert "158" in t
    assert "%" in t


def test_years_available():
    years = official_stats.years_available()
    assert "2024" in years
    assert "2023" in years
