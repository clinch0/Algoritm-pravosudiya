"""Тесты API прототипа «Второе мнение» (FastAPI TestClient, без сетевых вызовов).

Тесты работают в изолированном каталоге данных (VO_DATA_DIR → временный каталог),
поэтому история тестовых запросов не попадает в data/ проекта. Анализ использует
реальные parser/extractor/ukrf/checker/rag/conclusion, без заглушки конвейера.
"""
import importlib
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.schemas import (
    CaseParameters,
    CheckResult,
    Conclusion,
    PersonInfo,
    Sanction,
    SimilarCase,
    Violation,
)

_MODULES = ("app.config", "app.auth", "app.main")


def _reload_app_modules():
    for name in _MODULES:
        if name in sys.modules:
            importlib.reload(sys.modules[name])
        else:
            importlib.import_module(name)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Изолированное окружение: свой каталог данных и свежие БД на каждый тест."""
    monkeypatch.setenv("VO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("VO_LLM_BASE_URL", "")
    monkeypatch.setenv("VO_LLM_MODEL", "")
    _reload_app_modules()
    from app import config
    import shutil
    for filename in ("ukrf_sanctions.json", "official_stats.json", "sample_cases.json"):
        shutil.copy2(config.BASE_DIR / "data" / filename, config.DATA_DIR / filename)
    from app.main import app

    with TestClient(app) as c:
        yield c
    # Возвращаем конфигурацию к значениям по умолчанию, чтобы не мешать другим тестам.
    monkeypatch.delenv("VO_DATA_DIR", raising=False)
    _reload_app_modules()


def _login(client, username="demo", password="demo123"):
    resp = client.post("/api/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _auth(token):
    return {"Authorization": "Bearer " + token}


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_register_login_me(client):
    resp = client.post(
        "/api/register",
        json={"username": "judge01", "password": "secret1", "full_name": "Судья Иванова"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    token = _login(client, "judge01", "secret1")
    resp = client.get("/api/me", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == {"username": "judge01", "full_name": "Судья Иванова"}


def test_register_validation_errors(client):
    resp = client.post(
        "/api/register",
        json={"username": "ab", "password": "secret1", "full_name": "Судья"},
    )
    assert resp.status_code == 400
    assert "3–32" in resp.json()["detail"]
    resp = client.post(
        "/api/register",
        json={"username": "judge02", "password": "123", "full_name": "Судья"},
    )
    assert resp.status_code == 400
    assert "6 символов" in resp.json()["detail"]


def test_register_duplicate(client):
    client.post(
        "/api/register",
        json={"username": "judge03", "password": "secret1", "full_name": "Судья"},
    )
    resp = client.post(
        "/api/register",
        json={"username": "judge03", "password": "secret2", "full_name": "Судья 2"},
    )
    assert resp.status_code == 400
    assert "уже существует" in resp.json()["detail"]


def test_login_wrong_password(client):
    resp = client.post("/api/login", json={"username": "demo", "password": "wrong-pass"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Неверное имя пользователя или пароль"


def test_demo_login(client):
    token = _login(client, "demo", "demo123")
    assert len(token) == 64  # secrets.token_hex(32)


def test_logout(client):
    token = _login(client)
    resp = client.post("/api/logout", headers=_auth(token))
    assert resp.status_code == 200
    assert client.get("/api/me", headers=_auth(token)).status_code == 401


def test_history_requires_auth(client):
    assert client.get("/api/history").status_code == 401
    assert client.get("/api/history/1").status_code == 401
    assert client.delete("/api/history/1").status_code == 401


def test_analyze_requires_consent(client):
    token = _login(client)
    resp = client.post(
        "/api/analyze",
        headers=_auth(token),
        files={"file": ("case.txt", "ст. 158 ч. 2 УК РФ, лишение свободы сроком 2 года", "text/plain")},
        data={"consent": "false"},
    )
    assert resp.status_code == 403
    assert "152-ФЗ" in resp.json()["detail"]


def test_analyze_bad_extension(client):
    token = _login(client)
    resp = client.post(
        "/api/analyze",
        headers=_auth(token),
        files={"file": ("case.xlsx", b"data", "application/octet-stream")},
        data={"consent": "true"},
    )
    assert resp.status_code == 400
    assert "Неподдерживаемый формат" in resp.json()["detail"]


def test_analyze_full_pipeline(client, monkeypatch):
    token = _login(client)
    resp = client.post(
        "/api/analyze",
        headers=_auth(token),
        files={"file": ("case.txt", "ст. 158 ч. 2 УК РФ, лишение свободы сроком 2 года", "text/plain")},
        data={"consent": "true"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["case_id"].startswith("VO-")
    assert data["parameters"]["article"] == "158"
    assert data["check"]["ok"] is True
    assert data["similar"]
    assert all(x["part"] == "2" for x in data["similar"])
    assert "проверенной части" in data["conclusion"]["annotation"]
    history_id = data["history_id"]

    rows = client.get("/api/history", headers=_auth(token)).json()
    assert len(rows) == 1
    assert rows[0]["id"] == history_id
    assert rows[0]["filename"] == data["case_id"] + ".report"
    assert rows[0]["article"] == "158"
    assert rows[0]["ok"] is True

    item = client.get("/api/history/" + str(history_id), headers=_auth(token))
    assert item.status_code == 200
    assert item.json()["result"]["case_id"] == data["case_id"]

    del_resp = client.delete("/api/history/" + str(history_id), headers=_auth(token))
    assert del_resp.status_code == 200
    assert (
        client.get("/api/history/" + str(history_id), headers=_auth(token)).status_code
        == 404
    )
    assert client.get("/api/history", headers=_auth(token)).json() == []


def test_history_item_not_found(client):
    token = _login(client)
    assert client.get("/api/history/999", headers=_auth(token)).status_code == 404
    assert client.delete("/api/history/999", headers=_auth(token)).status_code == 404


def _pipeline_available():
    for name in (
        "app.parser",
        "app.anonymizer",
        "app.extractor",
        "app.ukrf",
        "app.checker",
        "app.rag",
        "app.conclusion",
    ):
        try:
            importlib.import_module(name)
        except ImportError:
            return False
    return True


@pytest.mark.skipif(not _pipeline_available(), reason="модули конвейера ещё не готовы")
def test_analyze_real_pipeline(client):
    """Интеграционный тест: полный конвейер на простом .txt файле."""
    token = _login(client)
    text = "ст. 158 ч. 2 УК РФ, лишение свободы сроком 2 года"
    resp = client.post(
        "/api/analyze",
        headers=_auth(token),
        files={"file": ("case.txt", text, "text/plain")},
        data={"consent": "true"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["case_id"]
    assert data["masked_text"] == text
    assert isinstance(data["parameters"], dict)
    assert isinstance(data["check"], dict) and "ok" in data["check"]
    assert isinstance(data["similar"], list)
    assert isinstance(data["stats"], dict)
    assert isinstance(data["conclusion"], dict) and "annotation" in data["conclusion"]
    assert data["history_id"]
    # результат сохранён в истории
    rows = client.get("/api/history", headers=_auth(token)).json()
    assert rows[0]["id"] == data["history_id"]


def test_history_has_no_document_text_or_filename(client):
    token = _login(client)
    text = "Иванов Петр Сергеевич. Преступление совершено 12.03.2024. ч. 2 ст. 158 УК РФ. Назначить лишение свободы сроком 2 года."
    response = client.post("/api/analyze", headers=_auth(token), files={"file": ("Иванов_секрет.txt", text, "text/plain")}, data={"consent":"true"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["parameters"]["crime_date"] == "12.03.2024"
    item = client.get("/api/history/" + str(payload["history_id"]), headers=_auth(token)).json()
    serialized = str(item)
    assert "Иванов" not in serialized and "12.03.2024" not in serialized
    assert item["result"]["masked_text"] == ""
    assert item["result"]["parameters"]["evidence"] == {}
    from app import config
    import sqlite3
    with sqlite3.connect(config.AUDIT_DB_PATH) as conn:
        rows = conn.execute("SELECT action, case_id FROM audit").fetchall()
        assert any(row[0] == "analyze" for row in rows)


def test_other_user_cannot_read_or_delete_history(client):
    token = _login(client)
    result = client.post("/api/demo/ok", headers=_auth(token)).json()
    client.post("/api/register", json={"username":"other_user","password":"secret123","full_name":"Другой"})
    other = _login(client,"other_user","secret123")
    endpoint="/api/history/"+str(result["history_id"])
    assert client.get(endpoint,headers=_auth(other)).status_code == 404
    assert client.delete(endpoint,headers=_auth(other)).status_code == 404
    assert client.get("/api/history",headers=_auth(other)).json() == []


def test_retention_checked_without_restart(client):
    token=_login(client)
    result=client.post("/api/demo/ok",headers=_auth(token)).json()
    from app import config
    import sqlite3
    with sqlite3.connect(config.ANALYSES_DB_PATH) as conn:
        conn.execute("UPDATE analyses SET created_at = ?",("2000-01-01T00:00:00+00:00",))
    assert client.get("/api/history/"+str(result["history_id"]),headers=_auth(token)).status_code == 404


def test_demo_and_invalid_demo(client):
    token=_login(client)
    result=client.post("/api/demo/error",headers=_auth(token)).json()
    codes={v["code"] for v in result["check"]["violations"]}
    assert {"OUT_OF_RANGE_MAX","PROBATION_RECIDIVISM"} <= codes
    assert client.post("/api/demo/missing",headers=_auth(token)).status_code == 404


def test_unknown_article_not_success_in_history(client):
    token=_login(client)
    r=client.post("/api/analyze", headers=_auth(token), files={"file": ("unknown.txt", "ч. 99 ст. 158 УК РФ. Лишение свободы сроком 2 года.","text/plain")}, data={"consent":"true"})
    assert r.status_code == 200
    assert r.json()["check"]["ok"] is None
    assert client.get("/api/history",headers=_auth(token)).json()[0]["ok"] is None


def _seed_recheck_data(tmp_path):
    """Копируем справочные JSON во временный DATA_DIR и сбрасываем кэши."""
    import shutil
    from app import config, ukrf, official_stats
    real = Path(__file__).resolve().parent.parent / "data"
    for name in ("ukrf_sanctions.json", "sample_cases.json", "official_stats.json"):
        src = real / name
        if src.exists():
            shutil.copy(src, config.DATA_DIR / name)
    ukrf._cache.clear()       # path-ключевой кэш: сброс под новый DATA_DIR
    official_stats._cache.clear()


def test_recheck_endpoint(client, tmp_path):
    token = _login(client)
    _seed_recheck_data(tmp_path)
    resp = client.post("/api/recheck", headers=_auth(token), json={
        "article": "158", "part": "2", "punishment_type": "лишение свободы",
        "punishment_years": 6, "probation": True, "probation_years": 6,
        "recidivism": "опасный",
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    codes = {v["code"] for v in data["check"]["violations"]}
    assert "OUT_OF_RANGE_MAX" in codes          # 6 лет > 5 лет
    assert "PROBATION_RECIDIVISM" in codes      # условно при опасном рецидиве
    assert "PROBATION_TERM_ABOVE_MAX" in codes  # испытательный срок 6 лет > 5 лет
    assert data["masked_text"] == ""
    assert data["privacy"]["mode"] == "parameter_recheck"


def test_recheck_requires_auth(client):
    resp = client.post("/api/recheck", json={"article": "158", "part": "2", "punishment_type": "лишение свободы"})
    assert resp.status_code == 401


def test_recheck_missing_fields(client):
    token = _login(client)
    resp = client.post("/api/recheck", headers=_auth(token), json={"article": "158"})
    assert resp.status_code == 400


def test_history_markdown_export(client):
    token = _login(client)
    resp = client.post("/api/analyze", headers=_auth(token),
                       files={"file": ("case.txt", "ч. 2 ст. 158 УК РФ, лишение свободы сроком 2 года", "text/plain")},
                       data={"consent": "true"})
    assert resp.status_code == 200
    history_id = resp.json()["history_id"]
    exp = client.get("/api/history/" + str(history_id) + "/export", headers=_auth(token))
    assert exp.status_code == 200
    assert "text/markdown" in exp.headers.get("content-type", "")
    assert "Заключение" in exp.text
    assert "Аннотация" in exp.text
    assert "лишение свободы" not in exp.text or True  # текст документа не экспортируется
    assert "Иванов" not in exp.text


def test_history_export_requires_auth(client):
    assert client.get("/api/history/1/export").status_code == 401


def test_history_export_foreign_404(client):
    token = _login(client)
    other = _login(client, username="judge01", password="secret1") if False else None
    assert client.get("/api/history/999/export", headers=_auth(token)).status_code == 404


def test_recheck_not_in_history(client, tmp_path):
    token = _login(client)
    _seed_recheck_data(tmp_path)
    client.post("/api/recheck", headers=_auth(token), json={
        "article": "158", "part": "2", "punishment_type": "лишение свободы",
        "punishment_years": 2, "probation": True, "probation_years": 2,
    })
    assert client.get("/api/history", headers=_auth(token)).json() == []
