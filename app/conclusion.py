"""Russian report with explicit coverage and provenance; no synthetic practice claims."""
from datetime import datetime, timezone
from . import config
from .schemas import Conclusion


def build(params, check, similar, stats, now=None):
    now = now or datetime.now(timezone.utc)
    qualification = (f"ч. {params.part or '?'} ст. {params.article} УК РФ" if params.article else "не извлечена")
    punishment = params.punishment_type or "не извлечено"
    if params.punishment_type == "лишение свободы":
        if params.punishment_years is None and params.punishment_months is None:
            punishment += ": срок неизвестен"
        else:
            punishment += f": {((params.punishment_years or 0) * 12 + (params.punishment_months or 0)):g} мес."
    elif params.fine_rub is not None:
        punishment += f": {params.fine_rub:g} руб."
    if params.probation:
        punishment += " условно (ст. 73 УК РФ)"
        if params.probation_years is not None or params.probation_months is not None:
            term_months = (params.probation_years or 0) * 12 + (params.probation_months or 0)
            punishment += f", испытательный срок {term_months:g} мес."
    status = {"issues":"Выявлены возможные несоответствия проверяемым правилам", "incomplete":"Недостаточно данных для проверки", "partial":"В проверенной части несоответствий не выявлено"}[check.status]
    annotation = f"Дело {params.case_id}. Квалификация: {qualification}. Наказание: {punishment}. {status}."
    deeper = list(check.warnings) + list(params.notes)
    deeper += [f"{v.code}: {v.message}" for v in check.violations]
    deeper.append("Автоматически извлечённые факты требуют подтверждения человеком; отсутствие найденного обстоятельства не доказывает его отсутствие.")
    if params.release_grounds:
        deeper.append("Основания освобождения только обнаружены по упоминанию; условия и процессуальная форма требуют проверки.")
    count = stats.get("count", 0)
    if count:
        deeper.append(f"Учебная статистика: n={count}, медиана {stats.get('median_years')} лет, диапазон {stats.get('min_years')}–{stats.get('max_years')} лет. Источник — синтетические примеры. Эти числа не отражают судебную практику и не обосновывают изменение наказания.")
    else:
        deeper.append("Для выбранной статьи/части учебная статистика отсутствует.")
    off = stats.get("official", {})
    if off.get("data"):
        deeper.append(f"Официальный агрегат: форма № 10.3, {off.get('year')} год. Доли видов наказания не являются пределами наказания, распределением сроков или оценкой сопоставимости дел.")
    ed = stats.get("edition")
    if ed and ed.get("status") == "edition_changed_after_crime_date":
        dates = ", ".join(a["date"] for a in ed.get("known_amendments_after_crime_date", []))
        deeper.append(
            f"Дата преступления: {ed['crime_date']}. Статья изменялась после этой даты (известные правки: {dates}). "
            "Применимая редакция и обратная сила (ст. 9–10 УК РФ) автоматически не проверены — требуется ручная проверка."
        )
    elif ed and ed.get("crime_date"):
        deeper.append(
            f"Дата преступления: {ed['crime_date']}. В частичной истории правок статьи изменений после этой даты "
            "не найдено; полная история редакций не проверена."
        )
    rec = (ed or {}).get("sanction_reconstruction") or {}
    if rec.get("status") == "reconstructed_partial":
        applied = rec.get("applied_changes") or []
        if applied:
            last = applied[-1]["limits"]
            deeper.append(
                "Пределы санкции применены по реконструированной редакции на дату деяния "
                f"(известные откаты: {len(applied)}; пределы до последней правки: "
                f"минимум {last.get('min') if last.get('min') is not None else 'не задан'} лет, "
                f"максимум {last.get('max')} лет). Частичная история — результат требует юридической проверки."
            )
    deeper.append(config.DISCLAIMER)
    return Conclusion(case_id=params.case_id, annotation=annotation, check=check, similar=similar,
                      stats=stats, deeper_analysis=list(dict.fromkeys(deeper)), generated_at=now.isoformat(timespec="seconds"))
