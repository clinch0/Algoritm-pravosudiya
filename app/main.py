"""FastAPI-приложение прототипа «Второе мнение»: API, авторизация, история.

Конвейер анализа: parser.extract_text → anonymizer.mask_text →
extractor.extract → ukrf.get_sanction → checker.check → CaseStore.search/stats →
conclusion.build. Импорты модулей выполняются внутри /api/analyze, поэтому
приложение запускается даже до готовности остальных модулей (анализ вернёт
503 с русским сообщением).
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import config
from app.auth import AuthService

os.makedirs(config.STATIC_DIR, exist_ok=True)
os.makedirs(config.DATA_DIR, exist_ok=True)

auth_service = AuthService()

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
CONSENT_REQUIRED = "Подтвердите право загрузки и использование синтетического демо-документа. Эта отметка не заменяет основание по 152-ФЗ."

_CREATE_ANALYSES = """
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user TEXT NOT NULL,
    filename TEXT NOT NULL,
    created_at TEXT NOT NULL,
    article TEXT,
    ok INTEGER,
    payload_json TEXT NOT NULL
)
"""


def _analyses_conn() -> sqlite3.Connection:
    """Соединение с БД анализов (таблица создаётся при необходимости)."""
    path = Path(config.ANALYSES_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA secure_delete=ON")
    conn.execute(_CREATE_ANALYSES)
    return conn


def cleanup() -> None:
    """Удаляет анализы старше config.RETENTION_DAYS (ФЗ-152: ограничение хранения)."""
    conn = _analyses_conn()
    try:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=config.RETENTION_DAYS)
        ).isoformat(timespec="seconds")
        with conn:
            conn.execute("DELETE FROM analyses WHERE created_at < ?", (cutoff,))
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup()
    yield


app = FastAPI(title="Второе мнение", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")


# ---------- авторизация ----------

class RegisterIn(BaseModel):
    username: str
    password: str
    full_name: str


class LoginIn(BaseModel):
    username: str
    password: str


def _bearer_token(request: Request):
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def current_user(request: Request) -> dict:
    token = _bearer_token(request)
    user = auth_service.user_of(token) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    return user


@app.get("/")
def index():
    return FileResponse(config.STATIC_DIR / "projects.html")


@app.get("/demo")
def legacy_demo():
    return FileResponse(config.STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/register")
def register(body: RegisterIn):
    result = auth_service.register(body.username, body.password, body.full_name)
    if not result.get("ok"):
        raise HTTPException(
            status_code=400, detail=result.get("error", "Ошибка регистрации")
        )
    return {"ok": True}


@app.post("/api/login")
def login(body: LoginIn):
    token = auth_service.login(body.username, body.password)
    if token is None:
        raise HTTPException(
            status_code=401, detail="Неверное имя пользователя или пароль"
        )
    return {"token": token}


@app.post("/api/logout")
def logout(request: Request, user: dict = Depends(current_user)):
    auth_service.logout(_bearer_token(request))
    return {"ok": True}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    return user


# ---------- конвейер анализа ----------

def _run_pipeline(text: str, filename: str) -> dict:
    from app.pipeline import run
    return run(text)


@app.post("/api/analyze")
async def analyze(
    file: UploadFile = File(...),
    consent: str = Form(""),
    user: dict = Depends(current_user),
):
    """Загрузка документа (.pdf/.docx/.txt) и полный анализ.

    consent — техническое подтверждение загрузки демо, не правовое основание.
    """
    if consent != "true":
        raise HTTPException(status_code=403, detail=CONSENT_REQUIRED)
    filename = file.filename or "document.txt"
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Неподдерживаемый формат файла. Допустимы: .pdf, .docx, .txt",
        )
    content = await file.read(config.MAX_UPLOAD_MB * 1024 * 1024 + 1)
    await file.close()
    if not content:
        raise HTTPException(status_code=400, detail="Файл пустой")
    if len(content) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail=f"Файл слишком большой: максимум {config.MAX_UPLOAD_MB} МБ",
        )
    try:
        from app import parser as parser_mod
        from starlette.concurrency import run_in_threadpool
        text = await run_in_threadpool(parser_mod.extract_bytes, content, ext)
        payload = await run_in_threadpool(_run_pipeline, text, filename)
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Модули анализа недоступны: система находится в стадии развёртывания",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc) or "Не удалось обработать документ",
        )
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Не удалось обработать документ. Проверьте содержимое файла.",
        )
    history_id = _save_analysis(user["username"], filename, payload)
    return {**payload, "history_id": history_id}


def _save_analysis(username: str, filename: str, payload: dict) -> int:
    from app.pipeline import minimized
    from app.audit import record
    payload = minimized(payload)
    filename = payload["case_id"] + ".report"
    record(username, "analyze", payload["case_id"])
    cleanup()
    conn = _analyses_conn()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO analyses (user, filename, created_at, article, ok, payload_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    username,
                    filename,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    payload.get("parameters", {}).get("article"),
                    None if payload.get("check", {}).get("ok") is None else int(payload["check"]["ok"]),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            return cur.lastrowid
    finally:
        conn.close()


# ---------- пересчёт по уточнённым параметрам ----------

class RuleContextIn(BaseModel):
    article_64: bool | None = None
    agreement: bool | None = None
    special_order: bool | None = None
    reduced_inquiry: bool | None = None
    jury_leniency: bool | None = None
    aggregate: bool | None = None
    aggregate_crimes: bool | None = None


class RecheckIn(BaseModel):
    crime_date: str | None = None
    rule_context: RuleContextIn = Field(default_factory=RuleContextIn)
    review_flags: list[str] = Field(default_factory=list)
    mentioned_articles: list[str] = Field(default_factory=list)
    release_grounds: list[str] = Field(default_factory=list)
    article: str | None = None
    part: str | None = None
    punishment_type: str | None = None
    punishment_years: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    punishment_months: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    fine_rub: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    probation: bool = False
    probation_years: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    probation_months: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    stage: str | None = None
    mitigating: list[str] = []
    aggravating: list[str] = []
    recidivism: str | None = None
    is_minor: bool | None = None


@app.post("/api/recheck")
def recheck(body: RecheckIn, user: dict = Depends(current_user)):
    """Пересчёт проверки по параметрам, уточнённым человеком (без документа).

    Не сохраняется в истории: исходный документ отсутствует, а ручные параметры
    не являются доказательным источником. Результат — только для просмотра.
    """
    from app.pipeline import run_parameters
    from app.schemas import CaseParameters, PersonInfo
    from app.audit import record

    if not body.article or not body.part or not body.punishment_type:
        raise HTTPException(status_code=400, detail="Укажите статью, часть и вид наказания")
    if body.crime_date:
        try:
            datetime.strptime(body.crime_date, "%d.%m.%Y")
        except ValueError:
            raise HTTPException(status_code=400, detail="Дата должна быть существующей датой ДД.ММ.ГГГГ")
    params = CaseParameters(
        case_id="RECHECK-" + uuid.uuid4().hex[:8].upper(),
        crime_date=body.crime_date,
        rule_context=body.rule_context.model_dump(),
        review_flags=list(body.review_flags),
        mentioned_articles=list(body.mentioned_articles),
        release_grounds=list(body.release_grounds),
        article=body.article,
        part=body.part,
        punishment_type=body.punishment_type,
        punishment_years=body.punishment_years,
        punishment_months=body.punishment_months,
        fine_rub=body.fine_rub,
        probation=body.probation,
        probation_years=body.probation_years,
        probation_months=body.probation_months,
        stage=body.stage,
        mitigating=list(body.mitigating),
        aggravating=list(body.aggravating),
        person=PersonInfo(recidivism=body.recidivism, is_minor=body.is_minor),
    )
    try:
        payload = run_parameters(params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "Не удалось выполнить пересчёт")
    except Exception:
        raise HTTPException(status_code=400, detail="Не удалось выполнить пересчёт. Проверьте параметры.")
    record(user["username"], "recheck", payload["case_id"])
    return payload


# ---------- история анализов ----------

@app.get("/api/history")
def history(user: dict = Depends(current_user)):
    cleanup()
    conn = _analyses_conn()
    try:
        rows = conn.execute(
            "SELECT id, filename, created_at, article, ok FROM analyses "
            "WHERE user = ? ORDER BY id DESC",
            (user["username"],),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "filename": row["filename"],
                "created_at": row["created_at"],
                "article": row["article"],
                "ok": None if row["ok"] is None else bool(row["ok"]),
            }
            for row in rows
        ]
    finally:
        conn.close()


@app.get("/api/history/{history_id}")
def history_item(history_id: int, user: dict = Depends(current_user)):
    cleanup()
    conn = _analyses_conn()
    try:
        row = conn.execute(
            "SELECT * FROM analyses WHERE id = ? AND user = ?",
            (history_id, user["username"]),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Запись не найдена")
        from app.audit import record
        record(user["username"], "view", str(history_id))
        return {
            "id": row["id"],
            "filename": row["filename"],
            "created_at": row["created_at"],
            "article": row["article"],
            "ok": None if row["ok"] is None else bool(row["ok"]),
            "result": json.loads(row["payload_json"]),
        }
    finally:
        conn.close()


@app.get("/api/history/{history_id}/export")
def history_export(history_id: int, user: dict = Depends(current_user)):
    """Экспорт сохранённого (минимизированного) заключения в Markdown."""
    cleanup()
    conn = _analyses_conn()
    try:
        row = conn.execute(
            "SELECT * FROM analyses WHERE id = ? AND user = ?",
            (history_id, user["username"]),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Запись не найдена")
        payload = json.loads(row["payload_json"])
    finally:
        conn.close()
    from app.audit import record
    record(user["username"], "export", str(history_id))
    lines = ["# Заключение «Второе мнение»", ""]
    concl = payload.get("conclusion") or {}
    lines.append("**Аннотация.** " + (concl.get("annotation") or "—"))
    lines.append("")
    check = payload.get("check") or {}
    status_labels = {"issues": "Выявлены возможные несоответствия",
                     "incomplete": "Недостаточно данных для проверки",
                     "partial": "В проверенной части несоответствий не выявлено"}
    lines.append("**Статус проверки.** " + status_labels.get(check.get("status"), "—"))
    lines.append("")
    for v in check.get("violations") or []:
        lines.append("- «" + str(v.get("code")) + "» (" + str(v.get("level")) + "): " + str(v.get("message")))
    if not check.get("violations"):
        lines.append("- Нарушений не зафиксировано (в проверенной части).")
    lines.append("")
    if check.get("warnings"):
        lines.append("## Замечания")
        for w in check["warnings"]:
            lines.append("- " + str(w))
        lines.append("")
    if check.get("trace"):
        lines.append("## Расчёт специальных максимумов")
        for t in check["trace"]:
            lines.append("- " + str(t.get("norm")) + ": " + str(t.get("base_years")) + " × " +
                         str(t.get("factor")) + " ≈ " + str(t.get("cap_years")) + " лет")
        lines.append("")
    deeper = concl.get("deeper_analysis") or []
    if deeper:
        lines.append("## Области для глубокого анализа")
        for s in deeper:
            if s:
                lines.append("- " + str(s))
        lines.append("")
    ed = (payload.get("stats") or {}).get("edition") or {}
    if ed.get("current_redaction"):
        lines.append("*Текущая редакция статьи по справочнику: " + str(ed["current_redaction"]) +
                     ". История редакций частичная.*")
    lines.append("")
    lines.append("---")
    lines.append("*" + config.DISCLAIMER + "*")
    md = "\n".join(lines)
    from fastapi.responses import Response
    filename = payload.get("case_id", "report") + ".md"
    return Response(
        content=md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=\"" + filename + "\""},
    )


@app.delete("/api/history/{history_id}")
def history_delete(history_id: int, user: dict = Depends(current_user)):
    conn = _analyses_conn()
    try:
        with conn:
            cur = conn.execute(
                "DELETE FROM analyses WHERE id = ? AND user = ?",
                (history_id, user["username"]),
            )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Запись не найдена")
        from app.audit import record
        record(user["username"], "delete", str(history_id))
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/demo/{sample}")
def demo(sample: str, user: dict = Depends(current_user)):
    names = {"ok":"приговор_пример_ok.docx", "error":"приговор_пример_ошибка.docx",
             "attempt":"приговор_пример_покушение.docx"}
    if sample not in names:
        raise HTTPException(404, "Учебный пример не найден")
    from app.parser import extract_text
    payload = _run_pipeline(extract_text(str(config.BASE_DIR / "samples" / names[sample])), "demo")
    return {**payload, "history_id": _save_analysis(user["username"], "demo", payload)}


from app.project_api import install as install_projects
install_projects(app, current_user)
