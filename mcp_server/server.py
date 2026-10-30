"""MCP-сервер «Второе мнение» (Model Context Protocol, транспорт: stdio).

Предоставляет ИИ-ассистентам (Codex, Claude и др.) инструменты анализа:
analyze_document, check_parameters, find_similar_cases, case_statistics,
legal_reference. Используются те же модули, что и в веб-приложении;
анализ документа возвращает минимизированный отчёт без текста. Это не гарантия
юридического обезличивания; встроенные примеры синтетические.

Подключение:
- Claude Desktop: блок из mcp-config.example.json → claude_desktop_config.json.
- Codex CLI (~/.codex/config.toml):
    [mcp_servers.vsrf-second-opinion]
    command = "python"
    args = ["<ПУТЬ_К_ПРОЕКТУ>/mcp_server/server.py"]
"""
from __future__ import annotations

import sys
import os
from contextlib import closing
import uuid
from pathlib import Path

# Корень проекта — в sys.path, чтобы импорт app.* работал независимо
# от рабочего каталога, из которого запущен сервер.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    # mcp 1.x (сигнатура по спецификации)
    from mcp.server.fastmcp import FastMCP  # noqa: E402
except ImportError:
    # mcp 2.x: FastMCP переименован в MCPServer (совместимость)
    from mcp.server.mcpserver import MCPServer as FastMCP  # noqa: E402

mcp = FastMCP("vsrf-second-opinion")

try:
    from app import anonymizer, checker, extractor, parser, ukrf  # noqa: E402
    from app import conclusion as conclusion_mod  # noqa: E402
    from app.rag import CaseStore  # noqa: E402
    from app.schemas import (  # noqa: E402
        CaseParameters,
        CheckResult,
        PersonInfo,
        Violation,
        to_dict,
    )

    _MODULES_READY = True
except ImportError:
    # Модули анализа ещё не готовы: инструменты вернут {"error": ...}.
    _MODULES_READY = False

_COMMON_NORMS = [
    "ст. 60 УК РФ — общие начала назначения наказания",
    "ст. 61, 63 УК РФ — смягчающие и отягчающие обстоятельства",
    "ст. 62, 65, 66, 68 УК РФ — правила назначения при особых обстоятельствах",
    "ст. 64, 73 УК РФ — ниже низшего предела и условное осуждение",
]

_ARTICLE_NORMS = {
    "105": ["ст. 107, 108, 109 УК РФ — привилегированные составы против жизни"],
    "111": ["ст. 112, 115 УК РФ — смежные составы причинения вреда здоровью"],
    "158": [
        "ст. 158.1 УК РФ — мелкое хищение",
        "ч. 3–4 ст. 158 УК РФ — квалифицированные составы кражи",
    ],
    "159": ["ст. 159.1–159.6 УК РФ — специальные виды мошенничества"],
    "161": ["ст. 162, 163 УК РФ — смежные корыстно-насильственные составы"],
    "228": ["ст. 228.1, 229 УК РФ — смежные составы в сфере наркотиков"],
    "264": ["ст. 264.1 УК РФ — повторное управление в состоянии опьянения"],
}


def _require_modules() -> dict | None:
    if _MODULES_READY:
        return None
    return {"error": "Модули анализа недоступны: система находится в стадии развёртывания"}


def _sanction_check(params: CaseParameters):
    return checker.check(params, ukrf.get_sanction(params.article, params.part))

@mcp.tool()
def analyze_document(path: str) -> dict:
    """Анализирует документ приговора (.pdf, .docx, .txt) и возвращает результат работы
    всей системы: извлечённые параметры дела, проверку наказания, похожие дела,
    статистику и заключение без полного текста и выдержек. По умолчанию доступны
    только встроенные синтетические примеры. При ошибке возвращается {"error": "..."}."""
    if err := _require_modules():
        return err
    try:
        from app import config
        from app.pipeline import run, minimized
        # Reject UNC and Windows device paths before any filesystem lookup.
        # Otherwise even a denied request may initiate SMB authentication.
        if path.replace("\\", "/").startswith("//"):
            return {"error":"Сетевые и системные пути не разрешены"}
        candidate = Path(os.path.abspath(path))
        builtin = {(config.BASE_DIR / "samples" / name).resolve() for name in ("приговор_пример_ok.docx", "приговор_пример_ошибка.docx")}
        configured = os.environ.get("VO_MCP_DOCUMENT_DIR")
        allowed_root = None
        if configured:
            if configured.replace("\\", "/").startswith("//"):
                return {"error":"Каталог MCP должен быть локальным"}
            allowed_root = Path(os.path.abspath(configured))
        if candidate not in builtin and not (allowed_root and candidate.is_relative_to(allowed_root)):
            return {"error":"Доступ к этому документу не разрешён. По умолчанию доступны только встроенные примеры."}
        requested = candidate.resolve(strict=True)
        allowed = requested in builtin
        if allowed_root:
            allowed = allowed or requested.is_relative_to(allowed_root.resolve(strict=True))
        if not allowed or not requested.is_file():
            return {"error":"Доступ к этому документу не разрешён. По умолчанию доступны только встроенные примеры."}
        return minimized(run(parser.extract_text(str(requested))))
    except (ValueError, OSError):
        return {"error":"Документ недоступен или не прошёл проверку формата/размера"}
    except Exception:
        return {"error":"Ошибка анализа документа"}

@mcp.tool()
def check_parameters(
    article: str,
    part: str,
    punishment_type: str,
    years: float | None = None,
    months: float | None = None,
    fine_rub: float | None = None,
    mitigating: list[str] | None = None,
    aggravating: list[str] | None = None,
    stage: str | None = None,
    probation: bool = False,
    recidivism: str | None = None,
    probation_years: float | None = None,
    probation_months: float | None = None,
    is_minor: bool | None = None,
) -> dict:
    """Проверяет назначенное наказание по параметрам дела без загрузки документа.
    Аргументы: статья УК РФ, часть, вид наказания, срок (лет/месяцев), штраф (руб.),
    списки смягчающих/отягчающих обстоятельств (канонические ключи), стадия,
    условное осуждение (ст. 73), испытательный срок (лет/месяцев), рецидив
    (нет|простой|опасный|особо опасный), несовершеннолетний (true|false|null).
    Возвращает список нарушений с уровнями ошибка/предупреждение/информация."""
    if err := _require_modules():
        return err
    try:
        params = CaseParameters(
            case_id="MCP-CHECK",
            article=article,
            part=part,
            punishment_type=punishment_type,
            punishment_years=years,
            punishment_months=months,
            fine_rub=fine_rub,
            mitigating=list(mitigating or []),
            aggravating=list(aggravating or []),
            stage=stage,
            probation=bool(probation),
            probation_years=probation_years,
            probation_months=probation_months,
            person=PersonInfo(recidivism=recidivism, is_minor=is_minor),
        )
        sanction = ukrf.get_sanction(article, part)
        if sanction is None:
            return {
                "error": f"Санкция статьи {article} (ч. {part or '?'}) не найдена в справочнике"
            }
        return to_dict(checker.check(params, sanction))
    except Exception as exc:  # noqa: BLE001
        return {"error": "Проверка не выполнена"}

@mcp.tool()
def find_similar_cases(query: str, article: str | None = None, top_k: int = 5, part: str | None = None) -> list[dict]:
    """Ищет похожие приговоры в локальной базе синтетических дел (BM25).
    Возвращает список с полями: id, article, part, punishment_type, years, months,
    fine_rub, score (сходство), summary."""
    if err := _require_modules():
        return [err]
    try:
        with closing(CaseStore()) as store:
            store.ensure_samples()
            return [to_dict(item) for item in store.search(query, article=article, part=part, top_k=top_k)]
    except Exception as exc:  # noqa: BLE001
        return [{"error": "Поиск не выполнен"}]


@mcp.tool()
def case_statistics(
    article: str, part: str | None = None, punishment_type: str = "лишение свободы"
) -> dict:
    """Возвращает статистику похожих дел по статье (и части): число дел, средний и
    медианный срок, минимум, максимум, квартили p25/p75 для выбранного вида наказания."""
    if err := _require_modules():
        return err
    try:
        with closing(CaseStore()) as store:
            store.ensure_samples()
            return {**store.stats(article=article, part=part, punishment_type=punishment_type),
                    "source_kind":"synthetic", "limitation":"Учебные данные; не судебная практика"}
    except Exception as exc:  # noqa: BLE001
        return {"error": "Статистика недоступна"}


@mcp.tool()
def legal_reference(article: str, part: str | None = None) -> dict:
    """Возвращает справочную информацию по статье УК РФ: санкцию (пределы и виды
    наказаний), категорию тяжести и связанные нормы Общей и Особенной части."""
    if err := _require_modules():
        return err
    try:
        sanction = ukrf.get_sanction(article, part)
        if sanction is None:
            return {"error": f"Статья {article} не найдена в справочнике санкций"}
        try:
            category = ukrf.category_from_max(
                sanction.imprisonment_max_years, sanction.negligent
            )
        except Exception:  # noqa: BLE001
            category = None
        related = list(_ARTICLE_NORMS.get(str(article), [])) + list(_COMMON_NORMS)
        return {
            "article": article,
            "part": part,
            "sanction": to_dict(sanction),
            "category": category,
            "related_norms": related,
            "law_version_status": "unverified_for_crime_date",
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": "Справочная информация недоступна"}


@mcp.tool()
def search_law(query: str, limit: int = 5, article: str | None = None) -> dict:
    """Поиск по небольшому локальному индексу норм с источниками; историческая применимость не подтверждена."""
    from app.law_index import search_law as search
    try:
        return search(query, limit, article)
    except ValueError as exc:
        return {"error": str(exc)}


@mcp.tool()
def get_law_unit(unit_id: str) -> dict:
    """Точный версионный фрагмент нормы, ссылка на источник и хеш текста."""
    from app.law_index import get_law_unit as get_unit
    try:
        return get_unit(unit_id)
    except LookupError:
        return {"error": "Фрагмент нормы не найден"}


@mcp.resource("law://unit/{unit_id}")
def law_resource(unit_id: str) -> str:
    """Текст и паспорт нормативного фрагмента. Не содержит документов проекта или vault."""
    import json
    from app.law_index import get_law_unit
    return json.dumps(get_law_unit(unit_id), ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
