"""Project-scoped, mandatory JSON preparation. No model or network calls."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import unicodedata
import uuid

from cryptography.fernet import Fernet
from . import config

MAX_TEXT = 300_000
TOKEN = re.compile(r"⟦[^⟦⟧]+⟧")
PATTERNS = (
    ("EMAIL", re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-zА-Яа-я]{2,}(?![\w.-])")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+7|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)")),
    ("SNILS", re.compile(r"(?<!\d)\d{3}-\d{3}-\d{3}\s?\d{2}(?!\d)")),
    ("PERSON", re.compile(r"\b[А-ЯЁ][а-яё-]+\s+[А-ЯЁ][а-яё-]+\s+[А-ЯЁ][а-яё-]*(?:вич|вна|ична)\b")),
    ("PASSPORT", re.compile(r"(?i)(?:паспорт\s*(?:серия)?\s*[:№]?\s*)(\d{2}\s?\d{2}\s*(?:номер|№)?\s*\d{6})(?!\d)")),
    ("DOB", re.compile(r"(?i)(?:дата рождения|родился|родилась)\s*[:—-]?\s*(\d{1,2}[./]\d{1,2}[./]\d{4})")),
    ("ADDRESS", re.compile(r"(?im)(?:адрес(?: регистрации| проживания)?\s*:\s*)([^\n;]{5,200})")),
)
FIELD_TYPES = {
    "фио": "PERSON", "full_name": "PERSON", "person_name": "PERSON",
    "email": "EMAIL", "почта": "EMAIL", "phone": "PHONE", "телефон": "PHONE",
    "passport": "PASSPORT", "паспорт": "PASSPORT", "snils": "SNILS",
    "address": "ADDRESS", "адрес": "ADDRESS", "date_of_birth": "DOB",
    "inn": "ID", "инн": "ID",
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalized(kind, value):
    value = unicodedata.normalize("NFKC", value).casefold()
    if kind in ("PHONE", "PASSPORT", "SNILS"):
        digits = re.sub(r"\D", "", value)
        return "7" + digits[1:] if kind == "PHONE" and len(digits) == 11 and digits.startswith("8") else digits
    return " ".join(value.split())


def strings(value, depth=0, field=""):
    if depth > 12:
        raise ValueError("Слишком глубокий JSON")
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key), ""
            yield from strings(item, depth + 1, str(key))
    elif isinstance(value, list):
        for item in value:
            yield from strings(item, depth + 1, field)
    elif isinstance(value, str) or (field.casefold() in FIELD_TYPES and isinstance(value, (int, float))):
        yield str(value), field


def validate_payload(payload):
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    if len(encoded) > MAX_TEXT:
        raise ValueError("Запрос с документами превышает 300 000 символов")
    for text, _ in strings(payload):
        if "⟦" in text or "⟧" in text:
            raise ValueError("Служебные токены нельзя вводить в исходный текст")


class ProjectStore:
    def __init__(self, directory=None):
        self.directory = Path(directory or config.DATA_DIR)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db_path = self.directory / "projects.sqlite"
        self.cipher, self.key = self._cipher()
        with self.db() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS projects(
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS entities(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL,
                    kind TEXT NOT NULL, digest TEXT NOT NULL, token TEXT NOT NULL,
                    secret BLOB NOT NULL, UNIQUE(project_id, kind, digest));
                CREATE TABLE IF NOT EXISTS aliases(
                    project_id TEXT NOT NULL, entity_id INTEGER NOT NULL,
                    kind TEXT NOT NULL, digest TEXT NOT NULL, secret BLOB NOT NULL,
                    UNIQUE(project_id, kind, digest));
                CREATE TABLE IF NOT EXISTS documents(
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, label TEXT NOT NULL,
                    secret BLOB NOT NULL, masked TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS answers(id TEXT PRIMARY KEY, project_id TEXT NOT NULL, secret BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS drafts(
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    secret BLOB NOT NULL, masked TEXT NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL);
            """)

    def _cipher(self):
        # Windows DPAPI protects the key for the current OS account. It does NOT
        # isolate another process under that same account; production needs roles.
        windows = os.name == "nt"
        path = self.directory / ("project-vault.key.dpapi" if windows else "project-vault.key")
        if not path.exists():
            key = Fernet.generate_key()
            if windows:
                import win32crypt
                blob = win32crypt.CryptProtectData(key, "Second Opinion project vault", None, None, None, 0)
            else:
                blob = key
            try:
                with path.open("xb") as handle:
                    handle.write(blob)
                if not windows:
                    path.chmod(0o600)
            except FileExistsError:
                pass
        blob = path.read_bytes()
        if windows:
            import win32crypt
            key = win32crypt.CryptUnprotectData(blob, None, None, None, 0)[1]
        else:
            key = blob
        return Fernet(key), key

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA secure_delete=ON")
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def seal(self, value):
        return self.cipher.encrypt(json.dumps(value, ensure_ascii=False).encode())

    def unseal(self, value):
        return json.loads(self.cipher.decrypt(value))

    def authorize(self, conn, owner, project_id):
        row = conn.execute("SELECT * FROM projects WHERE id=? AND owner=?", (project_id, owner)).fetchone()
        if row is None:
            raise LookupError("Проект не найден")
        return row

    def create(self, owner, title):
        project_id = uuid.uuid4().hex[:12]
        with self.db() as conn:
            conn.execute("INSERT INTO projects(id,owner,title,created_at) VALUES(?,?,?,?)",
                         (project_id, owner, title.strip()[:120] or "Новый проект", now()))
        return self.view(owner, project_id)

    def list(self, owner):
        with self.db() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT id,title,revision,created_at FROM projects WHERE owner=? ORDER BY created_at DESC,id", (owner,))]

    def _digest(self, project_id, kind, value):
        return hmac.new(self.key, f"{project_id}:{kind}:{normalized(kind,value)}".encode(), hashlib.sha256).hexdigest()

    def _ensure_entity(self, conn, project_id, kind, value):
        digest = self._digest(project_id, kind, value)
        row = conn.execute("SELECT entity_id FROM aliases WHERE project_id=? AND kind=? AND digest=?",
                           (project_id, kind, digest)).fetchone()
        if row:
            return row[0], False
        count = conn.execute("SELECT count(*) FROM entities WHERE project_id=?", (project_id,)).fetchone()[0]
        if count >= 500:
            raise ValueError("В первом прототипе максимум 500 сущностей на проект")
        label = {"PERSON":"Гражданин", "PHONE":"Телефон", "EMAIL":"Почта", "ADDRESS":"Адрес", "DOB":"Дата рождения"}.get(kind, "Реквизит")
        letters = "АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЭЮЯ"
        suffix = letters[count] if count < len(letters) else str(count+1)
        token = f"⟦{label} {suffix}·{project_id[:4]}⟧"
        cursor = conn.execute("INSERT INTO entities(project_id,kind,digest,token,secret) VALUES(?,?,?,?,?)",
                              (project_id, kind, digest, token, self.seal(value)))
        conn.execute("INSERT INTO aliases VALUES(?,?,?,?,?)", (project_id, cursor.lastrowid, kind, digest, self.seal(value)))
        return cursor.lastrowid, True

    def _discover(self, conn, project_id, payload):
        changed = False
        for text, field in strings(payload):
            kind = FIELD_TYPES.get(field.casefold())
            if kind and text.strip():
                changed |= self._ensure_entity(conn, project_id, kind, text)[1]
            for kind, pattern in PATTERNS:
                for match in pattern.finditer(text):
                    value = match.group(1) if match.lastindex else match.group()
                    changed |= self._ensure_entity(conn, project_id, kind, value)[1]
        return changed

    def _entity_data(self, conn, project_id):
        return [(r["kind"], self.unseal(r["secret"]), r["token"])
                for r in conn.execute("SELECT a.kind,a.secret,e.token FROM aliases a JOIN entities e ON e.id=a.entity_id WHERE a.project_id=?", (project_id,))]

    def _mask(self, payload, entity_data):
        lookup = {(kind, normalized(kind, value)): token for kind, value, token in entity_data}
        def mask_text(text, field=""):
            kind = FIELD_TYPES.get(field.casefold())
            if kind and (kind, normalized(kind, text)) in lookup:
                return lookup[kind, normalized(kind, text)]
            spans = []
            for kind, value, token in entity_data:
                for m in re.finditer(r"(?<!\w)" + re.escape(value) + r"(?!\w)", text, re.I):
                    spans.append((m.start(), m.end(), token))
            for kind, pattern in PATTERNS:
                for m in pattern.finditer(text):
                    start, end = m.span(1) if m.lastindex else m.span()
                    token = lookup.get((kind, normalized(kind, text[start:end])))
                    if token:
                        spans.append((start, end, token))
            # Longest match at each starting position, never rematch a generated token.
            result, cursor = [], 0
            for start, end, token in sorted(set(spans), key=lambda item: (item[0], -item[1])):
                if start >= cursor:
                    result.extend((text[cursor:start], token))
                    cursor = end
            return "".join(result) + text[cursor:]
        def walk(item, field=""):
            if isinstance(item, dict):
                output = {}
                for key, value in item.items():
                    safe_key = mask_text(str(key))
                    if safe_key in output:
                        raise ValueError("После обфускации совпали ключи JSON")
                    output[safe_key] = walk(value, str(key))
                return output
            if isinstance(item, list):
                return [walk(value, field) for value in item]
            if isinstance(item, str):
                return mask_text(item, field)
            if field.casefold() in FIELD_TYPES and isinstance(item, (int, float)):
                return mask_text(str(item), field)
            return item
        return walk(payload)

    def _refresh(self, conn, project_id):
        entities = self._entity_data(conn, project_id)
        for row in conn.execute("SELECT id,secret FROM documents WHERE project_id=?", (project_id,)).fetchall():
            conn.execute("UPDATE documents SET masked=? WHERE id=?", (self._mask(self.unseal(row["secret"]), entities), row["id"]))
        # Already reviewed requests are invalidated too: new aliases require a new review.
        for row in conn.execute("SELECT id,secret FROM drafts WHERE project_id=?", (project_id,)).fetchall():
            masked = self._mask(self.unseal(row["secret"]), entities)
            conn.execute("UPDATE drafts SET masked=?,status='stale' WHERE id=?", (json.dumps(masked, ensure_ascii=False), row["id"]))

    def add_document(self, owner, project_id, text):
        validate_payload(text)
        with self.db() as conn:
            self.authorize(conn, owner, project_id)
            count = conn.execute("SELECT count(*) FROM documents WHERE project_id=?", (project_id,)).fetchone()[0]
            if count >= 30:
                raise ValueError("В первом прототипе максимум 30 документов на проект")
            self._discover(conn, project_id, text)
            conn.execute("INSERT INTO documents VALUES(?,?,?,?,?,?)",
                         (uuid.uuid4().hex, project_id, f"Документ {count+1}", self.seal(text), "", now()))
            conn.execute("UPDATE projects SET revision=revision+1 WHERE id=?", (project_id,))
            self._refresh(conn, project_id)
        return self.view(owner, project_id)

    def add_alias(self, owner, project_id, value, kind="PERSON", entity_id=None):
        validate_payload(value)
        if not value.strip() or len(value) > 300:
            raise ValueError("Укажите значение от 1 до 300 символов")
        if kind not in {"PERSON", "EMAIL", "PHONE", "SNILS", "PASSPORT", "ADDRESS", "DOB", "ID", "OTHER"}:
            raise ValueError("Неизвестный тип сущности")
        with self.db() as conn:
            self.authorize(conn, owner, project_id)
            if entity_id is None:
                self._ensure_entity(conn, project_id, kind, value)
            else:
                row = conn.execute("SELECT kind FROM entities WHERE project_id=? AND id=?", (project_id, entity_id)).fetchone()
                if row is None:
                    raise LookupError("Сущность не найдена")
                kind = row[0]
                digest = self._digest(project_id, kind, value)
                existing = conn.execute("SELECT entity_id FROM aliases WHERE project_id=? AND kind=? AND digest=?", (project_id, kind, digest)).fetchone()
                if existing and existing[0] != entity_id:
                    raise ValueError("Этот вариант уже принадлежит другой сущности; автоматическое объединение запрещено")
                conn.execute("INSERT OR IGNORE INTO aliases VALUES(?,?,?,?,?)", (project_id, entity_id, kind, digest, self.seal(value)))
            conn.execute("UPDATE projects SET revision=revision+1 WHERE id=?", (project_id,))
            self._refresh(conn, project_id)
        return self.view(owner, project_id)

    def preview(self, owner, project_id, payload):
        validate_payload(payload)
        with self.db() as conn:
            self.authorize(conn, owner, project_id)
            docs = [{"id": r["id"], "text": self.unseal(r["secret"])}
                    for r in conn.execute("SELECT id,secret FROM documents WHERE project_id=? ORDER BY id", (project_id,))]
            envelope = {"project_id": project_id, "request": payload, "documents": docs}
            validate_payload(envelope)
            if self._discover(conn, project_id, envelope):
                conn.execute("UPDATE projects SET revision=revision+1 WHERE id=?", (project_id,))
                self._refresh(conn, project_id)
            revision = self.authorize(conn, owner, project_id)["revision"]
            masked = self._mask(envelope, self._entity_data(conn, project_id))
            draft_id = uuid.uuid4().hex
            conn.execute("INSERT INTO drafts VALUES(?,?,?,?,?,?,?)",
                         (draft_id, project_id, revision, self.seal(envelope), json.dumps(masked, ensure_ascii=False), "review", now()))
            return {"draft_id": draft_id, "revision": revision, "payload": masked, "review_required": True,
                    "warning": "Проверьте текст: автоматическое обнаружение персональных данных неполно."}

    def send(self, owner, project_id, draft_id, reviewed):
        with self.db() as conn:
            project = self.authorize(conn, owner, project_id)
            row = conn.execute("SELECT * FROM drafts WHERE id=? AND project_id=?", (draft_id, project_id)).fetchone()
            if row is None:
                raise LookupError("Черновик не найден")
            if not reviewed:
                raise ValueError("Сначала проверьте замены в подготовленном JSON")
            if row["revision"] != project["revision"] or row["status"] == "stale":
                raise ValueError("Словарь или документы изменились; подготовьте запрос заново")
            # Recompute inside the transaction; never accept a caller-supplied 'safe' JSON.
            safe = self._mask(self.unseal(row["secret"]), self._entity_data(conn, project_id))
            conn.execute("UPDATE drafts SET masked=?,status='prepared' WHERE id=?", (json.dumps(safe, ensure_ascii=False), draft_id))
            return {"draft_id": draft_id, "status": "prepared", "payload": safe, "agent_connected": False,
                    "message": "Запрос подготовлен для локального агента. Модель пока не подключена; внешних вызовов нет."}

    def save_answer(self, owner, project_id, draft_id, answer):
        answer = dict(answer)
        with self.db() as conn:
            project = self.authorize(conn, owner, project_id)
            draft = conn.execute("SELECT * FROM drafts WHERE id=? AND project_id=?", (draft_id, project_id)).fetchone()
            if draft is None or draft["revision"] != project["revision"] or draft["status"] != "prepared":
                raise ValueError("Контекст изменился во время генерации; ответ не принят")
            known = {r[0] for r in conn.execute("SELECT token FROM entities WHERE project_id=?", (project_id,))}
            # Canonicalize only a complete known alias plus its namespace. Never
            # infer a person's name, merge entities, or fuzzy-match source data.
            prose = answer.get("answer", "")
            for token in known:
                pattern = re.escape(token[1:-1])
                if token.startswith("⟦Гражданин "):
                    pattern = pattern.replace("Гражданин", r"Гражданин(?:а|у|ом|е)?", 1)
                prose = re.sub(r"(?<![⟦\w])" + pattern + r"(?![⟧\w])", lambda _: token, prose, flags=re.I)
            answer["answer"] = prose
            for text, _ in strings(answer):
                if any(m.group() not in known for m in TOKEN.finditer(text)):
                    raise ValueError("Модель вернула неизвестный токен")
            # Reject raw identities in generated prose. Source quotations were
            # already prepared and must retain their exact text for verification.
            untagged = TOKEN.sub("", prose)
            if "⟦" in untagged or "⟧" in untagged or re.search(r"·[0-9a-f]{4}\b", untagged, re.I):
                raise ValueError("Модель изменила служебный заменитель; ответ не принят")
            if any(pattern.search(untagged) for _, pattern in PATTERNS):
                raise ValueError("Модель вернула незаменённые персональные данные; ответ не принят")
            if self._mask(untagged, self._entity_data(conn, project_id)) != untagged:
                raise ValueError("Модель вернула исходное значение из словаря; ответ не принят")
            conn.execute("INSERT OR REPLACE INTO answers VALUES(?,?,?)", (draft_id, project_id, self.seal(answer)))
            return answer

    def restore(self, owner, project_id, draft_id):
        with self.db() as conn:
            project = self.authorize(conn, owner, project_id)
            row = conn.execute("SELECT * FROM drafts WHERE id=? AND project_id=?", (draft_id, project_id)).fetchone()
            if row is None:
                raise LookupError("Черновик не найден")
            if row["revision"] != project["revision"] or row["status"] != "prepared":
                raise ValueError("Восстановление доступно только для актуального проверенного запроса")
            tokens = {r["token"]: self.unseal(r["secret"]) for r in conn.execute("SELECT token,secret FROM entities WHERE project_id=?", (project_id,))}
            def text(value):
                def replace(match):
                    if match.group() not in tokens:
                        raise ValueError("Неизвестный или чужой токен")
                    return tokens[match.group()]
                return TOKEN.sub(replace, value)
            def walk(value):
                if isinstance(value, str): return text(value)
                if isinstance(value, list): return [walk(x) for x in value]
                if isinstance(value, dict): return {text(k): walk(v) for k, v in value.items()}
                return value
            saved = conn.execute("SELECT secret FROM answers WHERE id=? AND project_id=?", (draft_id, project_id)).fetchone()
            return {"payload": walk(self.unseal(saved[0]) if saved else json.loads(row["masked"])),
                    "warning": "Восстановлены основные значения сущностей; исходное склонение/формат не гарантированы."}

    def view(self, owner, project_id):
        with self.db() as conn:
            project = dict(self.authorize(conn, owner, project_id))
            project.pop("owner")
            project["documents"] = [dict(r) for r in conn.execute("SELECT id,label,masked,created_at FROM documents WHERE project_id=? ORDER BY created_at,id", (project_id,))]
            project["entities"] = [{"id": r["id"], "kind": r["kind"], "token": r["token"], "value": self.unseal(r["secret"])}
                                   for r in conn.execute("SELECT * FROM entities WHERE project_id=? ORDER BY id", (project_id,))]
            project["requests"] = [{"id": r["id"], "status": r["status"], "revision": r["revision"], "payload": json.loads(r["masked"])}
                                   for r in conn.execute("SELECT * FROM drafts WHERE project_id=? ORDER BY created_at,id", (project_id,))]
            answers = {r["id"]: self.unseal(r["secret"]) for r in conn.execute("SELECT * FROM answers WHERE project_id=?", (project_id,))}
            for request in project["requests"]:
                # A stale answer may contain values found only by a later alias.
                if request["revision"] == project["revision"]:
                    request["answer"] = answers.get(request["id"])
            from .llm import configured
            project["agent_connected"] = configured()
            return project
