"""Правило-ориентированное извлечение ключевых параметров из текста приговора."""
from __future__ import annotations
import re
from typing import Callable, Optional

from .schemas import CaseParameters, PersonInfo


def _norm(text: str) -> str:
    """Нормализация: нижний регистр, ё→е, пробелы."""
    return re.sub(r"\s+", " ", text.lower().replace("ё", "е"))


WORD_NUM = {
    "один": 1, "одного": 1, "одному": 1, "одним": 1, "одна": 1, "одной": 1,
    "два": 2, "двух": 2, "двум": 2, "двумя": 2, "две": 2,
    "три": 3, "трех": 3, "трёх": 3, "трем": 3, "тремя": 3,
    "четыре": 4, "четырех": 4, "четырёх": 4,
    "пять": 5, "пяти": 5, "шесть": 6, "шести": 6, "семь": 7, "семи": 7,
    "восемь": 8, "восьми": 8, "девять": 9, "девяти": 9, "десять": 10, "десяти": 10,
    "одиннадцать": 11, "одиннадцати": 11, "двенадцать": 12, "двенадцати": 12,
    "тринадцать": 13, "тринадцати": 13, "четырнадцать": 14, "четырнадцати": 14,
    "пятнадцать": 15, "пятнадцати": 15, "шестнадцать": 16, "шестнадцати": 16,
    "семнадцать": 17, "семнадцати": 17, "восемнадцать": 18, "восемнадцати": 18,
    "девятнадцать": 19, "девятнадцати": 19, "двадцать": 20, "двадцати": 20,
}

WORD_YEARS = r"([а-яё]+)\s*(?:год|года|лет)"
WORD_MONTHS = r"([а-яё]+)\s*месяц"


def _word_years_months(text: str, prefix_re: str) -> tuple:
    """(годы|None, месяцы|None) словесного срока после prefix_re.

    Порядок: «X лет Y месяцев», затем только годы, затем только месяцы —
    каждая ветка с обязательной группой, чтобы не было пустого совпадения.
    """
    m = re.search(prefix_re + WORD_YEARS + r"\s*(?:и\s*)?" + WORD_MONTHS, text)
    if m:
        return WORD_NUM.get(m.group(1)), WORD_NUM.get(m.group(2))
    m = re.search(prefix_re + WORD_YEARS, text)
    if m:
        return WORD_NUM.get(m.group(1)), None
    m = re.search(prefix_re + WORD_MONTHS, text)
    if m:
        return None, WORD_NUM.get(m.group(1))
    return None, None


def affirmed(text: str, phrase: str) -> bool:
    """Reject nearby explicit negation. Ambiguous prose still needs human review."""
    for match in re.finditer(re.escape(phrase), text):
        before = text[max(0, match.start()-65):match.start()]
        after = text[match.end():match.end()+85]
        before = re.split(r"[.!?;\n]", before)[-1]
        after = re.split(r"[.!?;\n]", after)[0]
        if re.search(r"(?:\bне|\bнет|\bбез|отсутств\w*)\s+(?:\w+\s+){0,4}$", before):
            continue
        if re.search(r"^.{0,45}?(?:не\s+(?:установ|призн|име|подлеж|примен)|отсутств|исключен)", after):
            continue
        return True
    return False


def extract_crime_date(text: str) -> Optional[str]:
    # Only explicit crime-date labels; never infer from the first date in a file.
    patterns = [
        r"(?:дата\s+(?:совершения\s+)?преступления|преступление\s+совершено)\s*[:—-]?\s*(\d{1,2}\.\d{1,2}\.\d{4})",
        r"(\d{1,2}\.\d{1,2}\.\d{4})\s+(?:подсудимый\s+)?совершил",
    ]
    from datetime import datetime
    candidates = {m.group(1) for pat in patterns for m in re.finditer(pat, _norm(text))}
    if len(candidates) != 1:
        return None
    try:
        return datetime.strptime(candidates.pop(), "%d.%m.%Y").strftime("%d.%m.%Y")
    except ValueError:
        return None


MITIGATING_RULES: list[tuple[str, list[str]]] = [
    ("явка_с_повинной", ["явка с повинной", "явкой с повинной", "явку с повинной"]),
    ("активное_способствование", ["активно способствовал", "активное способствование",
                                   "способствовал раскрытию", "способствовал расследованию"]),
    ("возмещение_ущерба", ["возместил ущерб", "возмещение ущерба", "возместил вред",
                            "загладил вред", "возместил причиненный ущерб", "добровольное возмещение"]),
    ("малолетние_дети", ["малолетних детей", "малолетнего ребенка", "наличие малолетних",
                          "малолетние дети"]),
    ("беременность", ["беременн"]),
    ("несовершеннолетний_виновный", ["несовершеннолетний возраст виновного",
                                      "несовершеннолетие виновного", "несовершеннолетнего виновного"]),
    ("признание_вины", ["признал вину", "признание вины", "вину признал", "признал свою вину"]),
    ("раскаяние", ["раскаял", "чистосердечное раскаяние"]),
    ("аморальность_потерпевшего", ["противоправность поведения потерпевшего",
                                    "аморальность поведения потерпевшего", "противоправное поведение потерпевшего"]),
    ("тяжелые_жизненные_обстоятельства", ["тяжелых жизненных обстоятельств",
                                           "стечение тяжелых жизненных обстоятельств", "тяжелые жизненные обстоятельства"]),
    ("оказание_помощи_потерпевшему", ["оказание медицинской и иной помощи", "оказал помощь потерпевшему",
                                       "оказание помощи потерпевшему"]),
    ("состояние_здоровья", ["состояние здоровья", "заболеван", "хроническ"]),
]

AGGRAVATING_RULES: list[tuple[str, list[str]]] = [
    ("рецидив", ["рецидив"]),
    ("особо_активная_роль", ["особо активная роль", "особо активную роль"]),
    # «группой лиц» намеренно НЕ в отягчающих: в большинстве составов это признак
    # самого преступления, а по ч. 2 ст. 63 УК РФ признак состава не учитывается
    # повторно как отягчающее обстоятельство (см. примечание в extract()).
    ("опьянение", ["состоянии опьянения", "алкогольного опьянения", "наркотического опьянения",
                   "в состоянии алкогольного опьянения"]),
    ("в_отношении_малолетнего", ["в отношении малолетнего", "совершение преступления в отношении малолетнего"]),
    ("особая_жестокость", ["особая жестокость", "особой жестокостью"]),
    ("использование_служебного_положения", ["служебного положения", "служебным положением"]),
]

RELEASE_RULES: list[tuple[str, list[str]]] = [
    ("76.2", ["судебный штраф", "судебного штрафа"]),
    ("76", ["примирением сторон", "в связи с примирением", "примирение с потерпевшим"]),
    ("75", ["деятельное раскаяние", "деятельного раскаяния"]),
    ("78", ["сроки давности", "истечением сроков давности", "истечение сроков давности"]),
    ("81", ["в связи с болезнью", "психического расстройства"]),
    ("84", ["амнист"]),
]

_ARTICLE_PATTERNS = [
    # «ч. 2 ст. 158 УК РФ» / «ч.2 ст.158 УК РФ» (по нормализованному тексту в нижнем регистре)
    re.compile(r"ч(?:аст(?:и|ь|ью|ей)|\.)?\s*(\d{1,2})\s*ст(?:ать(?:и|я|е|ей)|\.)?\s*(\d{1,3}(?:\.\d{1,2})?)\s*ук\s*рф"),
    # «части 2 статьи 158 Уголовного кодекса Российской Федерации»
    re.compile(r"част(?:и|ь|ью)\s*(\d{1,2})\s*стать(?:и|я|е|ей)\s*(\d{1,3}(?:\.\d{1,2})?)"),
    # «ст. 158 УК РФ» / «статья 158 УК РФ» (без части)
    re.compile(r"ст(?:ать(?:и|я|е|ей)|\.)?\s*(\d{1,3}(?:\.\d{1,2})?)\s*ук\s*рф"),
    # «пункта «б» части 2 статьи 158»
    re.compile(r"пункт(?:а|ом)?\s*«?[а-я]»?\s*част(?:и|ь|ью|\.)?\s*(\d{1,2})\s*стать(?:и|я|е|ей|\.)?\s*(\d{1,3}(?:\.\d{1,2})?)"),
    # «по ст. 76.2 УК РФ» — основания освобождения
    re.compile(r"ст(?:ать(?:и|я|е|ей)|\.)?\s*(7[5-9]|8[0-4]|76\.\d)\s*ук\s*рф"),
]


def _extract_articles(text: str) -> tuple[Optional[str], Optional[str], list[str]]:
    """Вернуть (статья, часть, все найденные статьи). Приоритет у ч.X ст.Y."""
    n = _norm(text)
    found: list[tuple[str, str]] = []
    for m in re.finditer(r"ст(?:атья|атьи|атье|\.)?\s*(\d{1,3}(?:\.\d{1,2})?)\s*(?:ук\s*рф\s*)?[, ]*ч(?:асть|асти|\.)?\s*(\d{1,2})", n):
        found.append((m.group(1), m.group(2)))
    # «ч. 2 ст. 158 и ч. 1 ст. 161 УК РФ» — часть перед перечислением/союзом
    for m in re.finditer(r"ч(?:асть|асти|\.)?\s*(\d{1,2})\s*ст(?:атья|атьи|атье|\.)?\s*(\d{1,3}(?:\.\d{1,2})?)\s*(?:и|,)", n):
        if not any(a == m.group(2) for a, _ in found):
            found.append((m.group(2), m.group(1)))
    for pat in _ARTICLE_PATTERNS[:2]:
        for m in pat.finditer(n):
            part, article = m.group(1), m.group(2)
            found.append((article, part))
    for m in _ARTICLE_PATTERNS[2].finditer(n):
        if not any(a == m.group(1) for a, _ in found):
            found.append((m.group(1), None))
    for m in _ARTICLE_PATTERNS[3].finditer(n):
        part, article = m.group(1), m.group(2)
        if not any(a == article for a, _ in found):
            found.append((article, part))
    # Дедупликация; отбрасываем статьи Общей части (61–88 УК РФ, напр. ст. 73)
    general_part = {str(x) for x in range(1, 105)}
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, str]] = []
    for a, p in found:
        head = a.split(".")[0]
        if head in general_part:
            continue
        if (a, p) in seen:
            continue
        seen.add((a, p))
        unique.append((a, p))
    all_articles = [f"{a} ч.{p or '?'}" for a, p in unique] if unique else []
    if not unique:
        return None, None, all_articles
    return unique[0][0], unique[0][1], all_articles


def _extract_punishment(text: str, params: CaseParameters) -> None:
    n = _norm(text)
    # A prosecutor's request in the narrative is not the imposed punishment.
    if "приговорил" in n:
        n = re.split(r"приговорил[аи]?\s*:", n)[-1]
    # Prefer imprisonment as the principal punishment; mark mixed sanctions below.
    # Условное осуждение (ст. 73 УК РФ) — проверяем до ранних return
    if any(affirmed(n, p) for p in ("условно", "условным", "условное")):
        params.probation = True
    # Испытательный срок: «испытательным сроком 2 года», «испытательный срок 1 год 6 месяцев»
    m = re.search(
        r"испытательн\w*\s+срок\w*\s*(?:на\s*(?:срок\s*)?)?"
        r"(?:(\d{1,2}(?:[.,]\d+)?)\s*(?:лет|года|год))?\s*(?:и\s*)?"
        r"(?:(\d{1,2})\s*месяц)?",
        n,
    )
    if m and (m.group(1) or m.group(2)):
        if m.group(1):
            params.probation_years = float(m.group(1).replace(",", "."))
        if m.group(2):
            params.probation_months = float(m.group(2))
    elif params.probation:
        # словесный: «испытательный срок один год шесть месяцев»
        wy, wm = _word_years_months(n, r"испытательн\w+\s+срок\w+\s*(?:на\s*)?")
        if wy is not None:
            params.probation_years = float(wy)
        if wm is not None:
            params.probation_months = float(wm)
    # Штраф: «штраф в размере 120 000 рублей»
    m = re.search(r"штраф(?:а|у|ом)?\s*(?:в\s*размере)?\s*(\d{1,3}(?:\s?\d{3})*)\s*(?:рублей|руб\.|руб)", n)
    if m and not re.search(r"лишен(?:ие|ия|ию|ием)\s+свободы", n):
        params.punishment_type = "штраф"
        params.fine_rub = float(m.group(1).replace(" ", "").replace("\u00a0", ""))
        return
    # Лишение свободы: «лишение свободы сроком на 2 года 6 месяцев» и вариации
    m = re.search(
        r"лишен(?:ие|ия|ию|ием)\s*свободы\s*(?:сроком\s*)?(?:на\s*(?:срок\s*)?)?"
        r"(?:(\d{1,2}(?:[.,]\d+)?)\s*(?:лет|года|год))?\s*(?:и\s*)?"
        r"(?:(\d{1,2})\s*месяц)?",
        n,
    )
    if m and (m.group(1) or m.group(2)):
        params.punishment_type = "лишение свободы"
        if m.group(1):
            params.punishment_years = float(m.group(1).replace(",", "."))
        if m.group(2):
            params.punishment_months = float(m.group(2))
        return
    # «к 2 годам лишения свободы»
    m = re.search(r"к\s*(\d{1,2}(?:[.,]\d+)?)\s*(?:годам|году|лет)\s*лишения свободы", n)
    if m:
        params.punishment_type = "лишение свободы"
        params.punishment_years = float(m.group(1).replace(",", "."))
        return
    # «назначено наказание в виде 1 года исправительных работ»
    m = re.search(r"(\d{1,2}(?:[.,]\d+)?)\s*(?:года|год|лет|месяц)\s*(обязательных|исправительных|принудительных) работ", n)
    if m:
        canonical = {"обязательных": "обязательные работы",
                     "исправительных": "исправительные работы",
                     "принудительных": "принудительные работы"}[m.group(2)]
        params.punishment_type = canonical
        if "месяц" in m.group(0):
            params.punishment_months = float(m.group(1).replace(",", "."))
        else:
            params.punishment_years = float(m.group(1).replace(",", "."))
        return
    # Словесные сроки: «лишение свободы сроком на один год шесть месяцев»
    wy, wm = _word_years_months(
        n, r"лишен(?:ие|ия|ию|ием)\s*свободы\s*(?:сроком\s*)?(?:на\s*(?:срок\s*)?)?"
    )
    if wy is not None or wm is not None:
        params.punishment_type = "лишение свободы"
        if wy is not None:
            params.punishment_years = float(wy)
        if wm is not None:
            params.punishment_months = float(wm)
        return
    # Просто упоминание вида наказания
    for ptype in ("лишение свободы", "обязательные работы", "исправительные работы",
                  "принудительные работы", "ограничение свободы", "арест"):
        if ptype in n:
            params.punishment_type = ptype
            break


def extract(text: str, case_id: str) -> CaseParameters:
    """Извлечь параметры дела из текста (правило-ориентированный подход)."""
    params = CaseParameters(case_id=case_id, masked_text=text)
    n = _norm(text)

    params.article, params.part, all_articles = _extract_articles(text)
    for item in all_articles:
        # «158 ч.2» -> «158~2»; часть может отсутствовать
        mm = re.match(r"^(\S+)\s+ч\.(\d+|\?)$", item)
        if mm:
            params.mentioned_articles.append(mm.group(1) + "~" + mm.group(2))
        else:
            params.mentioned_articles.append(item.split(" ")[0] + "~?")
    params.mentioned_articles = sorted(set(params.mentioned_articles))
    if len(all_articles) > 1:
        params.review_flags.append("MULTIPLE_ARTICLES")
        params.notes.append(
            "В тексте упомянуто несколько статей: " + ", ".join(all_articles) +
            ". Анализ выполнен по первой из них; при совокупности преступлений проверьте правила ст. 69–70 УК РФ."
        )

    if params.article and params.part is None:
        params.review_flags.append("MISSING_PART")
        params.notes.append("Часть статьи не указана: автоматический выбор части 1 запрещён.")
    params.crime_date = extract_crime_date(text)

    # Стадия
    if affirmed(n, "приготовление") or re.search(r"ч\.\s*1\s*ст\.\s*30", n):
        params.stage = "приготовление"
    elif affirmed(n, "покушение") or re.search(r"ч\.\s*3\s*ст\.\s*30", n):
        params.stage = "покушение"
    else:
        params.stage = "оконченное"

    # Смягчающие / отягчающие
    for key, phrases in MITIGATING_RULES:
        if any(affirmed(n, p) for p in phrases):
            params.mitigating.append(key)
    for key, phrases in AGGRAVATING_RULES:
        if any(affirmed(n, p) for p in phrases):
            # For these circumstances, the text must explicitly show judicial recognition.
            if key != "рецидив" and not re.search(r"отягчающ\w*[^.!?]{0,100}(?:" + "|".join(re.escape(p) for p in phrases) + ")", n) and not re.search("(?:" + "|".join(re.escape(p) for p in phrases) + r")[^.!?]{0,100}отягчающ", n):
                params.review_flags.append("AGGRAVATING_REQUIRES_CONFIRMATION")
                continue
            params.aggravating.append(key)
    if any(p in n for p in ("группой лиц", "группа лиц", "группе лиц")):
        params.notes.append(
            "Упоминание совершения преступления в составе группы лиц: если это признак состава "
            "(например, п. «а» ч. 2 ст. 158 УК РФ), он не учитывается повторно как отягчающее "
            "обстоятельство (ч. 2 ст. 63 УК РФ)."
        )
    if re.search(
        r"несовершеннолетн\w*\s+(?:виновн\w*|подсудим\w*)"
        r"|(?:виновн\w*|подсудим\w*)\s+(?:\w+\s+){0,2}несовершеннолетн"
        r"|(?:является|признан|признается)\s+несовершеннолетн",
        n,
    ):
        params.person.is_minor = True
        if "несовершеннолетний_виновный" not in params.mitigating:
            params.mitigating.append("несовершеннолетний_виновный")

    # Основания освобождения (раздел IV УК РФ)
    for key, phrases in RELEASE_RULES:
        if any(affirmed(n, p) for p in phrases):
            params.release_grounds.append(key)
    for m in _ARTICLE_PATTERNS[4].finditer(n):
        if m.group(1) not in params.release_grounds:
            params.release_grounds.append(m.group(1))

    # Личность
    if affirmed(n, "особо опасный рецидив") or affirmed(n, "особо опасного рецидива"):
        params.person.recidivism = "особо опасный"
    elif affirmed(n, "опасный рецидив") or affirmed(n, "опасного рецидива"):
        params.person.recidivism = "опасный"
    elif affirmed(n, "рецидив"):
        params.person.recidivism = "простой"
    if re.search(r"ранее\s+судим|судимост", n) and not re.search(r"не\s+судим|судимост\w*\s+(?:не|отсутств)", n):
        params.person.first_offense = False
    elif re.search(r"впервые\s+(?:совершил|привлекается)|не\s+судим", n):
        params.person.first_offense = True
    if "признана виновной" in n or "осуждена" in n:
        params.person.gender = "женский"
    elif "признан виновным" in n or "осужден" in n:
        params.person.gender = "мужской"
    if "неработающ" in n:
        params.person.employment = "не работает"
    elif "работающ" in n:
        params.person.employment = "работает"

    # Unsupported scope must not silently use only one count or punishment.
    if re.search(r"совокупност|ст\.\s*(?:69|70)\b", n):
        params.review_flags.append("AGGREGATE_SENTENCE")
    if re.search(r"лишен\w* свободы", n) and re.search(r"штраф\w*\s+(?:в размере\s+)?\d", n):
        params.review_flags.append("MULTIPLE_PUNISHMENTS")
    # Наказание
    _extract_punishment(text, params)

    if params.punishment_type is None:
        params.notes.append("Вид и размер наказания не удалось извлечь автоматически — проверьте текст.")

    for key, pattern in {
        "qualification": r"(?:ч\.\s*\d+\s*)?ст\.\s*\d+(?:\.\d+)?[^\n]{0,45}",
        "punishment": r"(?:назнач\w*|лишен\w* свободы)[^\n]{0,120}",
    }.items():
        match = re.search(pattern, text, re.I)
        if match:
            params.evidence[key] = {"quote": match.group(0), "start": match.start(), "end": match.end(), "method": "regex_candidate"}
    params.review_flags = sorted(set(params.review_flags))
    return params


def extract_with_llm(text: str, case_id: str, llm_call: Optional[Callable[[str], dict]] = None) -> CaseParameters:
    """Гибридное извлечение: если передан вызов LLM (например, GigaChat/YaGPT) — используется он,
    иначе — правило-ориентированный метод."""
    if llm_call is None:
        return extract(text, case_id)
    raw = llm_call(text)
    params = extract(text, case_id)
    if isinstance(raw, dict):
        if raw.get("article"):
            params.article = str(raw["article"])
        if raw.get("part"):
            params.part = str(raw["part"])
        if raw.get("punishment_type"):
            params.punishment_type = str(raw["punishment_type"])
        if raw.get("punishment_years") is not None:
            params.punishment_years = float(raw["punishment_years"])
        if raw.get("punishment_months") is not None:
            params.punishment_months = float(raw["punishment_months"])
        if raw.get("fine_rub") is not None:
            params.fine_rub = float(raw["fine_rub"])
    params.notes.append("Часть параметров уточнена LLM-экстрактором.")
    return params
