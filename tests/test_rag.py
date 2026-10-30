# -*- coding: utf-8 -*-
"""Тесты локального RAG-поиска (app/rag.py)."""
import sqlite3

import pytest

from app.rag import CaseStore


def _make_store(tmp_path):
    """Создаёт хранилище во временном каталоге и загружает синтетику."""
    db = tmp_path / "cases.sqlite"
    store = CaseStore(db_path=str(db))
    loaded = store.load_cases()
    return store, loaded, db


def test_load_cases_idempotent(tmp_path):
    # загрузка БД: 30 записей, повторная загрузка не плодит дубликаты
    store, loaded, db = _make_store(tmp_path)
    assert loaded == 30
    assert store.load_cases() == 30
    with sqlite3.connect(str(db)) as conn:
        count = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    assert count == 30


def test_search_theft_group_finds_158_2(tmp_path):
    # запрос «кража группой лиц» должен найти 158 ч. 2 первым результатом
    store, _, _ = _make_store(tmp_path)
    results = store.search("кража группой лиц", top_k=5)
    assert results, "поиск должен вернуть результаты"
    assert results[0].article == "158"
    assert results[0].part == "2"
    assert results[0].score > 0
    # score нормирован в диапазоне [0, 1]
    assert all(0.0 <= r.score <= 1.0 for r in results)
    # у результата есть краткое описание
    assert results[0].summary


def test_search_filter_by_article(tmp_path):
    # фильтр по статье: все результаты — ст. 228
    store, _, _ = _make_store(tmp_path)
    results = store.search("приобрёл наркотических средств", article="228", top_k=5)
    assert results
    assert all(r.article == "228" for r in results)


def test_search_filter_by_punishment(tmp_path):
    # фильтр по виду наказания: слово «хищение» есть и в штрафных делах
    # (158 ч. 1), поэтому фильтр должен реально отсекать их из выдачи
    store, _, _ = _make_store(tmp_path)
    results = store.search("хищение", punishment_type="лишение свободы", top_k=10)
    assert results
    assert all(r.punishment_type == "лишение свободы" for r in results)


def test_stats_158_2(tmp_path):
    # статистика: три приговора по 158 ч. 2 — 2.0, 1+6/12=1.5 и 2.5 года
    store, _, _ = _make_store(tmp_path)
    stats = store.stats(article="158", part="2", punishment_type="лишение свободы")
    assert stats["count"] == 3
    assert stats["mean_years"] == pytest.approx(2.0)
    assert stats["median_years"] == pytest.approx(2.0)
    assert stats["min_years"] == pytest.approx(1.5)
    assert stats["max_years"] == pytest.approx(2.5)
    assert stats["p25"] <= stats["p75"]
    assert stats["min_years"] <= stats["p25"] <= stats["p75"] <= stats["max_years"]


def test_stats_empty(tmp_path):
    # нет данных — возвращается {"count": 0}
    store, _, _ = _make_store(tmp_path)
    assert store.stats(article="999") == {"count": 0}


def test_stemming_matches_word_forms(tmp_path):
    # «кражу» (винительный падеж) должен находить дела с «кража»/«кражей»/«кражу»
    store, _, _ = _make_store(tmp_path)
    results = store.search("кражу", top_k=5)
    assert results, "стемминг должен связать словоформы"
    assert all(r.article == "158" for r in results)


def test_stemming_query_and_corpus_consistent(tmp_path):
    store, _, _ = _make_store(tmp_path)
    nom = store.search("кража", top_k=5)
    acc = store.search("кражу", top_k=5)
    assert nom and acc
    # один и тот же набор кандидатов на разных словоформах
    assert {r.id for r in nom} == {r.id for r in acc}


def test_yo_normalization(tmp_path):
    # «приобрёл» и «приобрел» должны сопоставляться (ё → е)
    store, _, _ = _make_store(tmp_path)
    with store.conn:
        store.conn.execute("DELETE FROM cases")
        store.conn.execute(
            "INSERT INTO cases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("Y-1", "228", "1", "лишение свободы", 1.0, None, None, "[]", "[]", "приобрёл наркотическое средство"),
        )
        store.conn.execute(
            "INSERT INTO cases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("Y-2", "228", "1", "лишение свободы", 2.0, None, None, "[]", "[]", "приобрел наркотическое средство"),
        )
    results = store.search("приобрел", top_k=5)
    assert {r.id for r in results} == {"Y-1", "Y-2"}


def test_stats_converts_months_to_years(tmp_path):
    # месяцы переводятся в годы: 1 год 6 месяцев -> 1.5
    store, _, _ = _make_store(tmp_path)
    with store.conn:
        store.conn.execute("DELETE FROM cases")
        store.conn.execute(
            "INSERT INTO cases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("T-1", "158", "1", "лишение свободы", 1.0, 6.0, None, "[]", "[]", "тест"),
        )
    stats = store.stats(article="158", part="1", punishment_type="лишение свободы")
    assert stats["count"] == 1
    assert stats["mean_years"] == pytest.approx(1.5)
    assert stats["min_years"] == pytest.approx(1.5)
    assert stats["max_years"] == pytest.approx(1.5)
