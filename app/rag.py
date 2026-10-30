# -*- coding: utf-8 -*-
"""
Локальный поиск по базе обезличенных приговоров (RAG без сетевых моделей).

Реализован классический BM25 (библиотека rank-bm25, работает офлайн).
Никаких эмбеддингов и сетевых вызовов: данные не покидают машину суда.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from statistics import mean, median, quantiles
from typing import Optional

from rank_bm25 import BM25Plus

from . import config
from .schemas import SimilarCase

# -------------------------------------------------------------- стоп-слова
# Русский стоп-лист (~60 слов): служебные слова, местоимения, предлоги,
# частицы — лексика, не несущая смысла для поиска по текстам приговоров.
_STOP_WORDS = frozenset("""
и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по
только ее мне было от меня еще нет о из ему когда ли если уже или ни быть был
него до вас для мы тебя их чем была сам без под будет кто этот того этого ним
здесь этом один мой тем чтобы нее сейчас были при два об после больше тот
через эти нас про всего них много три эту свою этой перед лучше том такой им
более всегда всю между это просто
""".split())

# Токен: буквы и цифры (кириллица + латиница), нижний регистр.
_TOKEN_RE = re.compile(r"[а-яёa-z0-9]+")

# Лёгкий русский стеммер: частотные окончания, основа не короче 3 символов.
# Применяется одинаково к запросу и корпусу, поэтому «кража»/«кражу»/«кражей»
# сопоставляются. Это эвристика улучшения recall, не лингвистически полный стеммер.
_RU_SUFFIXES = (
    "иями", "ями", "ами", "иях", "ях", "ах", "иям", "ям", "ам",
    "ией", "ию", "ью", "ия", "ья", "ая", "яя", "ое", "ее", "ие", "ые",
    "ого", "его", "ому", "ему", "ую", "юю", "их", "ых", "им", "ым",
    "ом", "ем", "ий", "ый", "ой", "ей",
    "а", "я", "о", "е", "ы", "и", "у", "ю", "ь",
)


def _stem(token: str) -> str:
    if len(token) <= 3:
        return token
    for suffix in _RU_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[:-len(suffix)]
    return token


def _tokenize(text: str) -> list[str]:
    """Токенизация: нижний регистр, ё→е, только буквы/цифры, без стоп-слов, со стеммингом."""
    tokens = _TOKEN_RE.findall((text or "").lower().replace("ё", "е"))
    return [_stem(t) for t in tokens if t not in _STOP_WORDS]


def _summary(text: str, limit: int = 200) -> str:
    """Первые ~200 символов текста приговора (одной строкой)."""
    flat = " ".join((text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[:limit].rstrip() + "…"


class CaseStore:
    """Хранилище и поиск по обезличенным приговорам (SQLite + BM25)."""

    # схема таблицы: одна запись — один приговор из синтетической базы
    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS cases (
        id              TEXT PRIMARY KEY,
        article         TEXT,
        part            TEXT,
        punishment_type TEXT,
        years           REAL,
        months          REAL,
        fine_rub        REAL,
        mitigating      TEXT,   -- JSON-список ключей обстоятельств
        aggravating     TEXT,   -- JSON-список ключей обстоятельств
        text            TEXT
    )
    """

    def __init__(self, db_path: Optional[str] = None):
        # по умолчанию — путь из конфигурации (data/cases.sqlite)
        path = Path(db_path) if db_path else Path(config.CASES_DB_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = path
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(self._SCHEMA)
        self.conn.commit()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self) -> None:
        """Закрывает соединение с БД."""
        self.conn.close()

    def ensure_samples(self) -> int:
        """Загрузить демо-базу приговоров, если файл существует (идемпотентно).

        В тестовых окружениях путь данных может указывать во временный каталог,
        где файла нет — тогда возвращает 0 и поиск работает по пустой базе.
        """
        path = Path(config.SAMPLE_CASES_PATH)
        if not path.exists():
            return 0
        return self.load_cases(str(path))

    # ------------------------------------------------------------ загрузка
    def load_cases(self, json_path: Optional[str] = None) -> int:
        """Загружает приговоры из JSON (по умолчанию config.SAMPLE_CASES_PATH).

        Загрузка идемпотентна: используется INSERT OR REPLACE по ключу id,
        поэтому повторный вызов не создаёт дубликатов.
        Возвращает число записей в файле.
        """
        path = Path(json_path) if json_path else Path(config.SAMPLE_CASES_PATH)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # допускаем как список записей, так и {"cases": [...]}
        cases = data.get("cases") if isinstance(data, dict) else data
        with self.conn:
            for case in cases:
                self.conn.execute(
                    "INSERT OR REPLACE INTO cases "
                    "(id, article, part, punishment_type, years, months, "
                    " fine_rub, mitigating, aggravating, text) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        case["id"],
                        str(case.get("article") or ""),
                        str(case.get("part") or ""),
                        case.get("punishment_type") or "",
                        case.get("years"),
                        case.get("months"),
                        case.get("fine_rub"),
                        json.dumps(case.get("mitigating") or [], ensure_ascii=False),
                        json.dumps(case.get("aggravating") or [], ensure_ascii=False),
                        case.get("text") or "",
                    ),
                )
        return len(cases)

    # -------------------------------------------------------------- поиск
    def _fetch_rows(self, article: Optional[str] = None,
                    punishment_type: Optional[str] = None, part: Optional[str] = None) -> list[sqlite3.Row]:
        """Выбирает записи с учётом необязательных фильтров."""
        sql = "SELECT * FROM cases WHERE 1=1"
        params: list[str] = []
        if article is not None:
            sql += " AND article = ?"
            params.append(str(article))
        if part is not None:
            sql += " AND part = ?"
            params.append(str(part))
        if punishment_type is not None:
            sql += " AND punishment_type = ?"
            params.append(str(punishment_type))
        return self.conn.execute(sql, params).fetchall()

    def search(self, query: str, article: Optional[str] = None,
               punishment_type: Optional[str] = None,
               top_k: int = 5, part: Optional[str] = None) -> list[SimilarCase]:
        """Поиск похожих приговоров по тексту запроса (BM25).

        score — нормированная релевантность: bm25 / max_bm25 (в диапазоне
        [0, 1]); документы с нулевым пересечением с запросом не возвращаются.
        """
        if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 50:
            raise ValueError("top_k должен быть от 1 до 50")
        rows = self._fetch_rows(article, punishment_type, part)
        if not rows:
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        # собираем корпус токенизированных текстов (пустые пропускаем)
        corpus: list[list[str]] = []
        valid_rows: list[sqlite3.Row] = []
        for row in rows:
            tokens = _tokenize(row["text"])
            if tokens:
                corpus.append(tokens)
                valid_rows.append(row)
        if not corpus:
            return []

        bm25 = BM25Plus(corpus)
        raw_scores = bm25.get_scores(query_tokens)
        max_score = float(max(raw_scores)) if len(raw_scores) else 0.0

        ranked: list[tuple[float, sqlite3.Row]] = []
        for row, raw, tokens in zip(valid_rows, raw_scores, corpus):
            if not set(query_tokens).intersection(tokens):
                continue
            score = float(raw)
            if score > 0:
                ranked.append((score / max_score if max_score > 0 else 0.0, row))
        ranked.sort(key=lambda item: item[0], reverse=True)

        results: list[SimilarCase] = []
        for score, row in ranked[:top_k]:
            results.append(SimilarCase(
                id=row["id"],
                article=row["article"] or "",
                part=row["part"] or "",
                punishment_type=row["punishment_type"] or "",
                years=row["years"],
                months=row["months"],
                fine_rub=row["fine_rub"],
                score=round(float(score), 4),
                summary=_summary(row["text"]),
            ))
        return results

    # ----------------------------------------------------------- статистика
    def stats(self, article: Optional[str] = None, part: Optional[str] = None,
              punishment_type: str = "лишение свободы") -> dict:
        """Статистика назначенных наказаний по колонке years.

        Месяцы переводятся в годы (months / 12). Возвращает:
        {"count", "mean_years", "median_years", "min_years", "max_years",
         "p25", "p75"}; если подходящих записей нет — {"count": 0}.
        """
        sql = "SELECT years, months FROM cases WHERE punishment_type = ?"
        params: list[str] = [str(punishment_type)]
        if article is not None:
            sql += " AND article = ?"
            params.append(str(article))
        if part is not None:
            sql += " AND part = ?"
            params.append(str(part))

        values: list[float] = []
        for row in self.conn.execute(sql, params).fetchall():
            y, m = row["years"], row["months"]
            if y is None and m is None:
                continue
            values.append((y or 0.0) + (m or 0.0) / 12.0)

        if not values:
            return {"count": 0}

        values.sort()
        # квантили 25/75 (для одного значения — само значение)
        if len(values) >= 2:
            q25, _, q75 = quantiles(values, n=4, method="inclusive")
        else:
            q25 = q75 = values[0]

        return {
            "count": len(values),
            "mean_years": round(mean(values), 2),
            "median_years": round(median(values), 2),
            "min_years": round(min(values), 2),
            "max_years": round(max(values), 2),
            "p25": round(q25, 2),
            "p75": round(q75, 2),
        }


__all__ = ["CaseStore", "_tokenize"]
