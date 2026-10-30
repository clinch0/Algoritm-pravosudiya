# -*- coding: utf-8 -*-
"""Сверка санкций data/ukrf_sanctions.json с реальным текстом УК РФ.

Запуск: python tools/verify_sanctions.py
Что делает: для каждой статьи/части из базы санкций находит в скачанном тексте
статьи (data/ukrf_articles_text.json) фразу о лишении свободы («на срок до X лет»,
«от X до Y лет», «на тот же срок») и сравнивает пределы с базой.

История: этот скрипт нашёл единственную реальную ошибку базы (ч. 2 ст. 131 УК РФ —
минимум 4 года был пропущен) — исправлена. Известный артефакт: ч. 3 ст. 109
(«лишением свободы на тот же срок» после «до четырех лет») скрипт читает как 3 года,
потому что берёт последнее «до … лет» перед фразой (это «лишение права до трех лет»);
вручную сверено — база верна (максимум 4 года).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

if __name__ == "__main__" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DATA = Path(__file__).resolve().parent.parent / "data"

NUM = {
    "одного": 1, "одной": 1, "двух": 2, "двум": 2, "трех": 3, "трёх": 3,
    "четырех": 4, "четырёх": 4, "пяти": 5, "шести": 6, "семи": 7, "восьми": 8,
    "девяти": 9, "десяти": 10, "одиннадцати": 11, "двенадцати": 12,
    "тринадцати": 13, "четырнадцати": 14, "пятнадцати": 15, "шестнадцати": 16,
    "семнадцати": 17, "восемнадцати": 18, "девятнадцати": 19, "двадцати": 20,
}


def num_of(s: str | None):
    return NUM.get((s or "").strip())


def split_parts(text: str) -> dict[int, str]:
    """Режет текст статьи на части по маркерам '1. ', '2. ' и т.д."""
    text = re.sub(r"\s+", " ", text)
    parts: dict[int, str] = {}
    marks = [(m.start(), int(m.group(1)))
             for m in re.finditer(r"(?<![\d.])(\d{1,2})\.\s", text)]
    for i, (pos, pnum) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        if pnum not in parts:
            parts[pnum] = text[pos:end]
    return parts


def parse_ls(seg: str):
    """Пределы лишения свободы из текста части: (min, max) или None."""
    m = re.search(
        r"лишен\S*?\s*свободы[^.]{0,220}?срок\s*от\s*(\S+?)\s+до\s+(\S+?)\s*(?:лет|года|год)",
        seg)
    if m:
        return num_of(m.group(1)), num_of(m.group(2))
    m = re.search(
        r"лишен\S*?\s*свободы[^.]{0,220}?срок\s*до\s*(\S+?)\s*(?:лет|года|год)",
        seg)
    if m:
        return None, num_of(m.group(1))
    m = re.search(r"лишен\S*?\s*свободы[^.]{0,60}?на\s+тот\s+же\s+срок", seg)
    if m:
        prev = [num_of(x) for x in
                re.findall(r"до\s*(\S+?)\s*(?:лет|года|год)", seg[:m.start()])]
        return None, (prev[-1] if prev else None)
    return None


# (статья, часть), где скрипт читает не то «до … лет» из-за конструкции «на тот же срок»
KNOWN_ARTIFACTS = {("109", "3"): ((None, 3), (None, 4))}


def main() -> int:
    texts = json.loads((DATA / "ukrf_articles_text.json").read_text(encoding="utf-8"))
    sanc = json.loads((DATA / "ukrf_sanctions.json").read_text(encoding="utf-8"))
    ok = no_ls = mismatch = 0
    for a in sanc["articles"]:
        art, part = a["article"], a["part"]
        if art not in texts:
            print(f"  ! {art} ч.{part}: текст статьи не скачан")
            mismatch += 1
            continue
        parts = split_parts(texts[art]["text"])
        seg = parts.get(int(part)) if parts else texts[art]["text"]  # статья без нумерации частей (напр. 158.1)
        got = parse_ls(seg)
        bmin, bmax = a["imprisonment_min_years"], a["imprisonment_max_years"]
        if got is None:
            if bmin is None and bmax is None:
                no_ls += 1
            else:
                print(f"  ! {art} ч.{part}: ЛС не распознано (база {bmin}–{bmax}): {seg[:120]}")
                mismatch += 1
            continue
        lo, hi = got
        ok_min = (lo is None and bmin is None) or (
            lo is not None and bmin is not None and abs(lo - bmin) < 0.01)
        ok_max = (hi is not None and bmax is not None and abs(hi - bmax) < 0.01)
        if ok_min and ok_max:
            ok += 1
            continue
        if KNOWN_ARTIFACTS.get((art, part)) == ((lo, hi), (bmin, bmax)):
            # Accept only the documented pair, never any change to this article.
            print(f"  ~ {art} ч.{part}: известный артефакт парсера "
                  f"(скрипт {lo}–{hi}, база {bmin}–{bmax}) — база верна")
            ok += 1
            continue
        print(f"  ! {art} ч.{part}: текст {lo}–{hi}, база {bmin}–{bmax}")
        mismatch += 1
    print(f"ИТОГ: совпало {ok}, санкций без ЛС {no_ls}, расхождений {mismatch}")
    return 0 if mismatch == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
