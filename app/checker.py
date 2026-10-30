"""Проверка назначенного наказания на соответствие закону (Общая часть УК РФ).

Реализован демонстрационный набор правил. Для продукта набор должен быть расширен
(ст. 69, 70, 72, 80, 88 в полном объёме, специальные кратные штрафы и т.д.).
"""
from __future__ import annotations
from typing import Optional
import math
import re
from .extractor import affirmed

from .schemas import CaseParameters, CheckResult, Sanction, Violation

EPS = 1e-6


def _years(params: CaseParameters) -> Optional[float]:
    if params.punishment_years is None and params.punishment_months is None:
        return None
    return (params.punishment_years or 0.0) + (params.punishment_months or 0.0) / 12.0


def _fmt_years(y: float) -> str:
    return f"{y:.6g} г. (≈ {y*12:.6g} мес.)"


def _probation_article_bans(params: CaseParameters, text_l: str, viol: list[Violation]) -> None:
    """Запреты условного осуждения по статье/потерпевшему (не зависят от санкции)."""
    if not params.probation:
        return
    banned_parts = {"205.1": {"1", "1.1", "2"}, "205.4": {"2"},
                    "206": {"1", "2", "3"}, "210": {"4"}, "281.3": {"2"}}
    if params.article in {"205.2", "210.1", "360"} or params.part in banned_parts.get(params.article, set()):
        viol.append(Violation("PROBATION_FORBIDDEN_ARTICLE", "ошибка",
            f"Условное осуждение не назначается за преступление, предусмотренное ст. {params.article} УК РФ "
            f"(п. «а.1» ч. 1 ст. 73 УК РФ)."))
    if params.article in {"131", "132", "133", "134", "135"} and re.search(
        r"не достиг\w*\s+(?:четырнадцатилетнего|14-летнего)\s+возраста", text_l
    ):
        viol.append(Violation("PROBATION_SEX_MINOR", "ошибка",
            f"Условное осуждение не назначается за преступление против половой неприкосновенности "
            f"лица, не достигшего четырнадцатилетнего возраста (п. «а» ч. 1 ст. 73 УК РФ)."))


CONTEXT_PHRASES = {
    "article_64": ("ст. 64", "ст 64", "статьи 64", "статьей 64"),
    "agreement": ("досудебного соглашения", "досудебное соглашение", "главы 40.1", "гл. 40.1"),
    "special_order": ("особый порядок", "особом порядке", "глава 40", "гл. 40", "ст. 316 упк"),
    "reduced_inquiry": ("226.9", "дознание в сокращенной форме"),
    "jury_leniency": ("снисхождении", "снисхождение"),
    "aggregate_crimes": ("совокупности преступлений", "совокупность преступлений"),
}
CONTEXT_KEYS = (*CONTEXT_PHRASES, "aggregate")


def rule_context(params: CaseParameters) -> dict[str, bool]:
    """Structured facts take precedence; text inference remains a candidate, not confirmation."""
    text = params.masked_text.lower().replace("ё", "е")
    result = {key: any(affirmed(text, phrase) for phrase in phrases)
              for key, phrases in CONTEXT_PHRASES.items()}
    result["aggregate"] = bool(re.search(r"совокупност|ст\.\s*(?:69|70)\b", text)
                               or set(params.review_flags) & {"MULTIPLE_ARTICLES", "AGGREGATE_SENTENCE"})
    result.update({key: value for key, value in params.rule_context.items()
                   if key in CONTEXT_KEYS and isinstance(value, bool)})
    return result


def check(params: CaseParameters, sanction: Optional[Sanction]) -> CheckResult:
    result = CheckResult()
    viol: list[Violation] = result.violations
    incomplete = bool(params.review_flags)
    result.warnings.append("Демонстрационный справочник: редакция закона на дату преступления и обратная сила (ст. 9–10 УК РФ) автоматически не проверены.")
    if params.review_flags:
        result.warnings.append("Требуется проверка извлечения: " + ", ".join(params.review_flags))
    for name in ("punishment_years", "punishment_months", "fine_rub", "probation_years", "probation_months"):
        value = getattr(params, name)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
            result.ok, result.status = None, "incomplete"
            result.warnings.append("INVALID_PARAMETER: требуется конечное неотрицательное число: " + name)
            return result
    if not params.article or not params.part or not params.punishment_type:
        incomplete = True
        result.warnings.append("MISSING_PARAMETERS: не извлечены квалификация или вид наказания.")
    context = rule_context(params)
    aggregate_mode = context["aggregate"] or bool(
        "AGGREGATE_SENTENCE" in params.review_flags
        or "MULTIPLE_ARTICLES" in params.review_flags
        or re.search(r"совокупност|ст\.\s*(?:69|70)\b", params.masked_text.lower())
    )
    if aggregate_mode:
        incomplete = True
        result.warnings.append("AGGREGATE_PARTIAL: полный расчёт ст. 69–70 не выполнен; проверяются только абсолютные пределы и потолок совокупности.")
    text_l = params.masked_text.lower().replace("ё", "е")
    use64 = context["article_64"]

    # --- 0. Санкция не найдена ---
    if sanction is None:
        viol.append(Violation("SANCTION_NOT_FOUND", "информация",
            f"Статья {params.article or '?'} УК РФ не найдена в демо-базе санкций — "
            "проверка по пределам санкции не выполнялась. Подключите полную базу."))
        _probation_article_bans(params, text_l, viol)
        has_errors = any(v.level == "ошибка" for v in viol)
        result.ok, result.status = (False, "issues") if has_errors else (None, "incomplete")
        result.warnings.append("Проверка выполнена в ограниченном объёме: санкция статьи отсутствует в базе.")
        return result

    if (params.article, params.part) != (sanction.article, sanction.part):
        result.ok, result.status = None, "incomplete"
        result.warnings.append("SANCTION_MISMATCH: санкция не соответствует статье/части.")
        return result
    ptype = params.punishment_type
    years = _years(params)
    _probation_article_bans(params, text_l, viol)
    if ptype not in ("лишение свободы", "штраф") or (ptype == "штраф" and params.fine_rub is None):
        incomplete = True
        result.warnings.append("Размер выбранного вида наказания не проверен.")
    if ptype == "штраф" and params.person.is_minor is None:
        incomplete = True
        result.warnings.append("FINE_AGE_UNKNOWN: для проверки границ штрафа подтвердите возраст.")
    if params.person.is_minor:
        incomplete = True
        result.warnings.append("Статья 88 реализована частично: нужны возраст, категория и специальные запреты/пределы.")
    result.limits["sanction_min_years"] = sanction.imprisonment_min_years
    result.limits["sanction_max_years"] = sanction.imprisonment_max_years
    result.limits["sanction_fine_min"] = sanction.fine_min_rub
    result.limits["sanction_fine_max"] = sanction.fine_max_rub

    # --- 0.5. Only an explicit aggregate of crimes with a complete known list. ---
    if aggregate_mode and ptype == "лишение свободы" and years is not None:
        from . import ukrf as _ukrf
        is_sentences = bool(re.search(r"совокупност\w*\s+приговор|ст\.?\s*70\b", text_l))
        is_crimes = context["aggregate_crimes"]
        episodes = set(params.mentioned_articles)
        maxima = []
        complete = len(episodes) >= 2 and f"{params.article}~{params.part}" in episodes
        for item in episodes:
            parts = item.split("~", 1)
            other = _ukrf.get_sanction(*parts) if len(parts) == 2 else None
            if other is None or other.imprisonment_max_years is None or other.life_or_death:
                complete = False
            else:
                maxima.append(other.imprisonment_max_years)
        if is_crimes and not is_sentences and complete and not params.crime_date:
            agg_cap = 1.5 * max(maxima)
            result.limits["aggregate_1_5_max"] = agg_cap
            if years > agg_cap + EPS:
                viol.append(Violation("AGGREGATE_OVER_1_5", "ошибка",
                    f"В учебном расчёте совокупности преступлений предел 1,5 × максимум санкций "
                    f"(ч. 2–3 ст. 69 УК РФ) составляет {_fmt_years(agg_cap)}; назначено {_fmt_years(years)}. "
                    "Проверьте полноту перечня эпизодов и применимую редакцию."))
        else:
            result.warnings.append("AGGREGATE_CAP_UNVERIFIED: вид совокупности, полный перечень санкций "
                                   "или их редакции не подтверждены; предел 1,5 не вычислялся.")

    # --- 1. Вид наказания предусмотрен санкцией? ---
    if not aggregate_mode and ptype and sanction.punishment_types and ptype not in sanction.punishment_types and use64:
        incomplete = True
        result.warnings.append("TYPE_64_REVIEW: вид вне санкции при ссылке на ст. 64 — требуется правовая оценка.")
    if not aggregate_mode and ptype and sanction.punishment_types and ptype not in sanction.punishment_types and not use64:
        viol.append(Violation("TYPE_NOT_IN_SANCTION", "ошибка",
            f"Вид наказания «{ptype}» не предусмотрен санкцией ч. {sanction.part} ст. {sanction.article} УК РФ "
            f"(санкция предусматривает: {', '.join(sanction.punishment_types)})."))

    # --- 2. Лишение свободы: пределы санкции ---
    if not aggregate_mode and ptype == "лишение свободы" and years is not None:
        smax = sanction.imprisonment_max_years
        smin = sanction.imprisonment_min_years
        if smax is not None and years > smax + EPS:
            viol.append(Violation("OUT_OF_RANGE_MAX", "ошибка",
                f"Лишение свободы {_fmt_years(years)} превышает максимум санкции ч. {sanction.part} "
                f"ст. {sanction.article} УК РФ ({_fmt_years(smax)})."))
    # --- 3. Ст. 56 ч. 2 УК РФ: общие пределы лишения свободы ---
    if ptype == "лишение свободы" and years is not None:
        text_l = params.masked_text.lower().replace("ё", "е")
        if years < 2 / 12 - EPS:
            viol.append(Violation("GENERAL_MIN", "ошибка",
                f"Лишение свободы {_fmt_years(years)} меньше минимального срока 2 месяца (ч. 2 ст. 56 УК РФ)."))
        if years > 20 + EPS:
            if aggregate_mode:
                incomplete = True
                result.warnings.append("GENERAL_AGGREGATE_MAX_REVIEW: пределы 25/30 лет имеют специальные исключения; полный расчёт ч. 4–5 ст. 56 не выполнен.")
            else:
                viol.append(Violation("GENERAL_MAX_20", "ошибка",
                    f"Лишение свободы {_fmt_years(years)} превышает общий максимум 20 лет (ч. 2 ст. 56 УК РФ)."))

    # --- 4. Специальные правила снижения максимума (ст. 62, 65, 66 УК РФ) ---
    # Ограничения применяются последовательно (по разъяснениям Пленума ВС РФ от 22.12.2015 № 58):
    # например, ч. 1 ст. 62 (2/3) + ч. 5 ст. 62 (2/3) = 2/3 от 2/3 максимума = 4/9.
    if not aggregate_mode and ptype == "лишение свободы" and years is not None and sanction.imprisonment_max_years is not None:
        smax = sanction.imprisonment_max_years
        has_agg = bool(params.aggravating) or params.person.recidivism in ("простой", "опасный", "особо опасный")
        mit = set(params.mitigating)
        p62_1_triggers = {"явка_с_повинной", "активное_способствование", "возмещение_ущерба", "оказание_помощи_потерпевшему"}
        life_exempt = sanction.life_or_death and params.stage not in ("приготовление", "покушение")
        text_l = params.masked_text.lower().replace("ё", "е")

        agreement = context["agreement"]
        special_order = context["special_order"]
        reduced_inquiry = context["reduced_inquiry"]
        leniency = context["jury_leniency"]
        combined = leniency and (agreement or special_order or reduced_inquiry or bool(mit & p62_1_triggers))
        if combined:
            incomplete = True
            result.warnings.append("COMBINED_RULES_REVIEW: снисхождение с другими основаниями — сочетание множителей требует правовой проверки.")
        if combined:
            agreement = special_order = reduced_inquiry = leniency = False
            mit = set()
        cap_rules: list[tuple[str, float, str]] = []  # (код, множитель, норма)

        if agreement and (has_agg or not (mit & {"явка_с_повинной", "активное_способствование"})):
            incomplete = True
            result.warnings.append("AGREEMENT_CONDITIONS_REVIEW: для ч. 2/4 ст. 62 проверить п. «и», отсутствие отягчающих и выполнение соглашения; автоматическое снижение не применено.")
        elif agreement:
            # ч. 2, 4 ст. 62 УК РФ — специальные правила вместо ч. 1
            if life_exempt:
                cap_rules.append(("CAP_62_4", 2 / 3,
                    "ч. 4 ст. 62 УК РФ (досудебное соглашение при статье с пожизненным лишением свободы/смертной казнью)"))
                viol.append(Violation("CAP_62_LIFE", "информация",
                    "При досудебном соглашении по статье, предусматривающей пожизненное лишение свободы или смертную казнь, "
                    "эти виды наказания не применяются (ч. 4 ст. 62 УК РФ)."))
            elif mit & p62_1_triggers and not has_agg:
                cap_rules.append(("CAP_62_2", 1 / 2,
                    "ч. 2 ст. 62 УК РФ (досудебное соглашение при наличии п. «и» ч. 1 ст. 61 УК РФ и отсутствии отягчающих)"))
            else:
                cap_rules.append(("CAP_62_2", 1 / 2,
                    "ч. 2 ст. 62 УК РФ (досудебное соглашение; 1/2 максимума)"))
        else:
            # ч. 1 ст. 62 УК РФ
            if mit & p62_1_triggers and not has_agg and not life_exempt:
                cap_rules.append(("CAP_62_1", 2 / 3,
                    "ч. 1 ст. 62 УК РФ (пп. «и», «к» ч. 1 ст. 61 УК РФ, нет отягчающих)"))
            # ч. 5 ст. 62 УК РФ: особый порядок (гл. 40 УПК) / сокращённое дознание (ст. 226.9 УПК)
            if reduced_inquiry:
                cap_rules.append(("CAP_62_5_226_9", 1 / 2,
                    "ч. 5 ст. 62 УК РФ (ст. 226.9 УПК РФ — дознание в сокращённой форме)"))
            elif special_order:
                cap_rules.append(("CAP_62_5", 2 / 3,
                    "ч. 5 ст. 62 УК РФ (особый порядок судебного разбирательства, гл. 40 УПК РФ)"))

        # ст. 65 УК РФ (вердикт присяжных о снисхождении)
        if leniency:
            if life_exempt:
                viol.append(Violation("CAP_65_LIFE", "информация",
                    "При вердикте присяжных о снисхождении пожизненное лишение свободы и смертная казнь не применяются (ч. 1 ст. 65 УК РФ)."))
            else:
                cap_rules.append(("CAP_65", 2 / 3, "ч. 1 ст. 65 УК РФ (вердикт присяжных о снисхождении)"))

        if sanction.life_or_death and params.stage in ("приготовление", "покушение"):
            viol.append(Violation("CAP_66_LIFE", "информация", "За неоконченное преступление пожизненное лишение свободы/смертная казнь исключены; применяется доля срочного максимума (ст. 66 УК РФ)."))
        # ст. 66 УК РФ (неоконченное преступление)
        if params.stage == "приготовление":
            if life_exempt:
                viol.append(Violation("CAP_66_LIFE", "информация",
                    "За приготовление к преступлению пожизненное лишение свободы и смертная казнь не назначаются (ч. 4 ст. 66 УК РФ)."))
            else:
                cap_rules.append(("CAP_66_PREP", 1 / 2, "ч. 2 ст. 66 УК РФ (приготовление к преступлению)"))
        elif params.stage == "покушение":
            if life_exempt:
                viol.append(Violation("CAP_66_LIFE", "информация",
                    "За покушение пожизненное лишение свободы и смертная казнь не назначаются (ч. 4 ст. 66 УК РФ)."))
            else:
                cap_rules.append(("CAP_66_ATT", 3 / 4, "ч. 3 ст. 66 УК РФ (покушение на преступление)"))

        # Stage is the base for other fractional limits (Plenum 58, paragraph 34).
        cap_rules.sort(key=lambda rule: 0 if rule[0].startswith("CAP_66") else 1)
        # Последовательное применение ограничений
        effective = smax
        if cap_rules:
            result.limits["cap_rules"] = "; ".join(norm for _, _, norm in cap_rules)
        for code, factor, norm in cap_rules:
            before = effective
            effective *= factor
            result.trace.append({"rule": code, "norm": norm, "base_years": before,
                                 "factor": factor, "cap_years": effective,
                                 "source": "https://www.vsrf.ru/documents/all/8470/"})
            result.limits[code.lower()] = effective
            if years > effective + EPS:
                viol.append(Violation(code, "ошибка",
                    f"По правилам {norm} срок лишения свободы не может превышать {_fmt_years(effective)}; "
                    f"назначено {_fmt_years(years)}."))
        result.limits["effective_max"] = effective

    # Special maxima at or below the lower bound do not require article 64.
    if not aggregate_mode and ptype == "лишение свободы" and years is not None and sanction.imprisonment_min_years is not None and years < sanction.imprisonment_min_years - EPS:
        effective = result.limits.get("effective_max")
        if result.trace and effective is not None and effective <= sanction.imprisonment_min_years + EPS:
            viol.append(Violation("BELOW_MIN_SPECIAL_CAP", "информация", "Специальный максимум достиг нижнего предела или ниже него; ссылка на ст. 64 не обязательна (п. 34 Пленума № 58)."))
        elif use64:
            viol.append(Violation("BELOW_MIN_64", "информация", "Указана ст. 64 УК РФ; проверить исключительные обстоятельства и запреты её применения."))
        elif not params.person.is_minor:
            viol.append(Violation("BELOW_MIN", "ошибка", "Срок ниже минимума санкции; проверить специальные правила и основания ст. 64 УК РФ."))

    # --- 5. Ст. 68 УК РФ: минимальный срок при рецидиве ---
    if not aggregate_mode and ptype == "лишение свободы" and years is not None and sanction.imprisonment_max_years is not None:
        rec = params.person.recidivism
        if rec in ("простой", "опасный", "особо опасный"):
            smax = sanction.imprisonment_max_years
            stage_factor = .5 if params.stage == "приготовление" else .75 if params.stage == "покушение" else 1
            third = smax * stage_factor / 3
            result.limits["recidivism_min_1_3_max"] = third
            if years < third - EPS:
                if params.mitigating or use64:
                    viol.append(Violation("RECIDIVISM_MIN_MITIGATING", "информация",
                        f"Срок {_fmt_years(years)} менее 1/3 максимума ({_fmt_years(third)}), что по общему правилу "
                        "недопустимо при рецидиве (ч. 2 ст. 68 УК РФ), однако при наличии смягчающих обстоятельств "
                        "суд вправе назначить менее 1/3 (ч. 3 ст. 68 УК РФ)."))
                else:
                    viol.append(Violation("RECIDIVISM_MIN", "ошибка",
                        f"При рецидиве срок не может быть менее 1/3 максимального срока наиболее строгого вида "
                        f"наказания, т.е. {_fmt_years(third)} (ч. 2 ст. 68 УК РФ)."))

    # --- 6. Ст. 73 УК РФ: условное осуждение ---
    if params.probation and params.person.recidivism in ("опасный", "особо опасный"):
        viol.append(Violation("PROBATION_RECIDIVISM", "ошибка",
            "Условное осуждение не назначается при опасном или особо опасном рецидиве (п. «в» ч. 1 ст. 73 УК РФ)."))
    if params.probation and ptype == "лишение свободы" and years is not None and years > 8 + EPS:
        viol.append(Violation("PROBATION_OVER_8", "ошибка",
            f"Условное осуждение возможно только при лишении свободы на срок до 8 лет включительно "
            f"(ч. 1 ст. 73 УК РФ); назначено {_fmt_years(years)}."))
    if (params.probation and sanction.category in ("тяжкое", "особо тяжкое")
            and re.search(r"(?:в течение|в период)\s+испытательного срока|условно-досрочн", text_l)):
        incomplete = True
        viol.append(Violation("PROBATION_DURING_PROBATION", "предупреждение",
            "Условное осуждение не назначается при совершении тяжкого или особо тяжкого преступления "
            "в течение испытательного срока при условном осуждении либо при условно-досрочном освобождении "
            "(п. «б» ч. 1 ст. 73 УК РФ). Упоминание требует проверки: установите связь с новым деянием "
            "и предыдущее осуждение за умышленное преступление; автоматический вывод о нарушении не сделан."))
    # Испытательный срок: пределы ч. 3 ст. 73 УК РФ
    if params.probation:
        if params.probation_years is None and params.probation_months is None:
            incomplete = True
            result.warnings.append("Испытательный срок не извлечён — проверка пределов ч. 3 ст. 73 УК РФ пропущена.")
        elif ptype == "лишение свободы" and years is None:
            incomplete = True
            result.warnings.append("Неизвестен основной срок — верхний предел испытательного срока не выбран.")
        else:
            term = (params.probation_years or 0.0) + (params.probation_months or 0.0) / 12.0
            long_sentence = ptype == "лишение свободы" and years is not None and years > 1 + EPS
            lo, hi = 0.5, (5.0 if long_sentence else 3.0)
            basis = ("лишении свободы на срок свыше одного года" if long_sentence
                     else "лишении свободы на срок до одного года включительно или более мягком виде наказания")
            result.limits["probation_term_min_years"] = lo
            result.limits["probation_term_max_years"] = hi
            result.limits["probation_term_basis"] = basis
            if term < lo - EPS:
                viol.append(Violation("PROBATION_TERM_BELOW_MIN", "ошибка",
                    f"Испытательный срок {_fmt_years(term)} меньше минимального 6 месяцев при {basis} "
                    f"(ч. 3 ст. 73 УК РФ)."))
            if term > hi + EPS:
                viol.append(Violation("PROBATION_TERM_ABOVE_MAX", "ошибка",
                    f"Испытательный срок {_fmt_years(term)} превышает максимум {hi:.0f} лет при {basis} "
                    f"(ч. 3 ст. 73 УК РФ)."))

    # --- 7. Ст. 88 УК РФ: несовершеннолетние ---
    if params.person.is_minor and ptype == "лишение свободы" and years is not None and years > 10 + EPS:
        viol.append(Violation("MINOR_MAX_10", "ошибка",
            f"Несовершеннолетним лишение свободы назначается на срок не свыше 10 лет (ч. 6 ст. 88 УК РФ), "
            f"назначено {_fmt_years(years)}."))
    if (not aggregate_mode and params.person.is_minor and ptype == "лишение свободы" and years is not None
            and sanction.category in ("тяжкое", "особо тяжкое")
            and sanction.imprisonment_min_years is not None):
        half_min = sanction.imprisonment_min_years / 2
        result.limits["minor_half_min"] = half_min
        if years < half_min - EPS and not (result.trace and result.limits.get("effective_max", float("inf")) <= half_min + EPS):
            if use64:
                viol.append(Violation("MINOR_64_REVIEW", "информация",
                    f"Несовершеннолетнему за тяжкое/особо тяжкое преступление низший предел сокращается наполовину "
                    f"(ч. 6.1 ст. 88 УК РФ): {_fmt_years(half_min)}; срок ниже — проверьте основания ст. 64 УК РФ."))
            else:
                viol.append(Violation("MINOR_BELOW_HALF_MIN", "ошибка",
                    f"Несовершеннолетнему за тяжкое/особо тяжкое преступление низший предел сокращается наполовину "
                    f"(ч. 6.1 ст. 88 УК РФ): минимум {_fmt_years(half_min)}; назначено {_fmt_years(years)}."))

    if params.probation:
        result.warnings.append("Проверены запреты пп. «а», «а.1», «б», «в» ч. 1 и пределы ч. 3 ст. 73 УК РФ по распознанным признакам; полнота распознавания признаков не гарантируется.")
    # --- 8. Штраф: пределы ---
    if ptype == "штраф" and params.fine_rub is not None:
        if params.person.is_minor is True:
            result.warnings.append("MINOR_FINE_REVIEW: штраф несовершеннолетнему требует применения ч. 2 ст. 88; взрослые пределы не применялись.")
        elif params.person.is_minor is None and params.fine_rub < 5000 - EPS:
            incomplete = True
            result.warnings.append("FINE_AGE_UNKNOWN: возраст не установлен; общий минимум для взрослых не применялся.")
        elif params.fine_rub < 5000 - EPS:
            viol.append(Violation("FINE_BELOW_GENERAL_MIN", "ошибка",
                f"Штраф взрослому ниже общего минимума 5000 рублей (ч. 2 ст. 46 УК РФ); "
                f"назначено {params.fine_rub:g} руб. Ссылка на ст. 64 сама по себе не снимает общий минимум."))
    if ptype == "штраф" and sanction.article in ("290", "291", "291.1", "291.2", "204"):
        incomplete = True
        result.warnings.append("MULTIPLE_FINE_UNSUPPORTED: кратный штраф и альтернативы по доходу не рассчитаны.")
    if not aggregate_mode and params.person.is_minor is False and ptype == "штраф" and params.fine_rub is not None and sanction.article not in ("290", "291", "291.1", "291.2", "204"):
        fmin, fmax = sanction.fine_min_rub, sanction.fine_max_rub
        if fmax is not None and params.fine_rub > fmax + EPS:
            viol.append(Violation("FINE_MAX", "ошибка",
                f"Штраф {params.fine_rub:,.0f} руб. превышает максимум санкции "
                f"({fmax:,.0f} руб.) (ч. {sanction.part} ст. {sanction.article} УК РФ).".replace(",", " ")))
        if fmin is not None and params.fine_rub < fmin - EPS and use64:
            incomplete = True
            result.warnings.append("FINE_64_REVIEW: проверить ст. 64 и общий минимум штрафа.")
        if fmin is not None and params.fine_rub < fmin - EPS and not use64:
            viol.append(Violation("FINE_MIN", "ошибка",
                f"Штраф {params.fine_rub:,.0f} руб. ниже минимального размера по санкции "
                f"({fmin:,.0f} руб.) (ч. {sanction.part} ст. {sanction.article} УК РФ).".replace(",", " ")))

    # --- 9. Раздел IV УК РФ: основания освобождения ---
    for ground in params.release_grounds:
        viol.append(Violation("RELEASE_GROUNDS", "информация",
            f"В тексте упоминаются основания освобождения от уголовной ответственности/наказания "
            f"(ст. {ground} УК РФ, раздел IV). Проверьте, обсуждены ли они в судебном акте и мотивировано ли их неприменение."))

    # --- 10. Итог ---
    errors = [v for v in viol if v.level == "ошибка"]
    if years is None and ptype == "лишение свободы":
        incomplete = True
        result.warnings.append("Размер лишения свободы не извлечён — проверка пределов по размеру пропущена.")
    result.status = "issues" if errors else "incomplete" if incomplete else "partial"
    result.ok = False if errors else None if incomplete else True
    return result
