"""Authenticated human workspace. Model-facing MCP does not expose the vault."""
from pathlib import Path
from fastapi import Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from . import config
from .project_store import ProjectStore


class ProjectIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class PreviewIn(BaseModel):
    payload: dict


class SendIn(BaseModel):
    draft_id: str
    reviewed: bool = False


class AliasIn(BaseModel):
    value: str = Field(min_length=1, max_length=300)
    kind: str = "PERSON"
    entity_id: int | None = None


def install(app, current_user):
    def invoke(method, *args):
        try:
            return getattr(ProjectStore(), method)(*args)
        except LookupError:
            raise HTTPException(404, "Проект, документ или запрос не найден")
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/projects")
    def projects(user=Depends(current_user)):
        return invoke("list", user["username"])

    @app.post("/api/projects")
    def create_project(body: ProjectIn, user=Depends(current_user)):
        return invoke("create", user["username"], body.title)

    @app.get("/api/projects/{project_id}")
    def project(project_id: str, user=Depends(current_user)):
        return invoke("view", user["username"], project_id)

    @app.post("/api/projects/{project_id}/documents")
    async def document(project_id: str, file: UploadFile = File(...), user=Depends(current_user)):
        invoke("view", user["username"], project_id)
        extension = Path(file.filename or "").suffix.lower()
        if extension not in {".pdf", ".docx", ".txt"}:
            await file.close()
            raise HTTPException(400, "Поддерживаются PDF, DOCX и TXT")
        content = await file.read(config.MAX_UPLOAD_MB * 1024 * 1024 + 1)
        await file.close()
        from .parser import extract_bytes
        try:
            text = await run_in_threadpool(extract_bytes, content, extension)
            return await run_in_threadpool(invoke, "add_document", user["username"], project_id, text)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(400, "Не удалось разобрать документ")

    @app.post("/api/projects/{project_id}/entities")
    def alias(project_id: str, body: AliasIn, user=Depends(current_user)):
        return invoke("add_alias", user["username"], project_id, body.value, body.kind, body.entity_id)

    @app.post("/api/projects/{project_id}/preview")
    def preview(project_id: str, body: PreviewIn, user=Depends(current_user)):
        return invoke("preview", user["username"], project_id, body.payload)

    @app.post("/api/projects/{project_id}/send")
    def send(project_id: str, body: SendIn, user=Depends(current_user)):
        result = invoke("send", user["username"], project_id, body.draft_id, body.reviewed)
        from . import llm
        if llm.configured():
            try:
                answer = llm.answer(result["payload"])
                answer = invoke("save_answer", user["username"], project_id, body.draft_id, answer)
                result.update(answer=answer, agent_connected=True, message="Ответ подготовлен. Проверьте цитаты и выводы.")
            except ValueError as exc:
                raise HTTPException(400, str(exc))
        return result

    @app.post("/api/projects/{project_id}/restore")
    def restore(project_id: str, body: SendIn, user=Depends(current_user)):
        return invoke("restore", user["username"], project_id, body.draft_id)

    @app.get("/api/laws/search")
    def laws(q: str = "", article: str | None = None, user=Depends(current_user)):
        from .law_index import search_law
        try:
            return search_law(q, article=article)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
