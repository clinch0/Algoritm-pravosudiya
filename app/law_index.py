"""Small versioned local law index. Search does not fetch anything from the web."""
import hashlib
import json
import re
import sqlite3
from . import config


def _path():
    return config.DATA_DIR / "law_index.sqlite"


def import_snapshot(path=None):
    source = path or config.DATA_DIR / "law_seed.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    units = data["units"]
    if not units or len(units) > 10000:
        raise ValueError("Недопустимый размер нормативного снимка")
    ids = set()
    for unit in units:
        if not all(unit.get(k) for k in ("id", "act", "article", "text", "source_url", "version_note", "retrieved_on")):
            raise ValueError("Норма без обязательного паспорта")
        if unit["id"] in ids:
            raise ValueError("Повтор идентификатора нормы")
        ids.add(unit["id"])
        if not unit["source_url"].startswith("https://"):
            raise ValueError("Источник должен содержать HTTPS URL")
    revision = hashlib.sha256(source.read_bytes()).hexdigest()
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_path(), timeout=15)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("CREATE TABLE IF NOT EXISTS snapshots(revision TEXT PRIMARY KEY, source_json TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS settings(name TEXT PRIMARY KEY,value TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS units(id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS law_fts USING fts5(id UNINDEXED,act,article,text,tokenize='unicode61')")
        for unit in units:
            packed = json.dumps(unit, ensure_ascii=False, sort_keys=True)
            existing = conn.execute("SELECT payload FROM units WHERE id=?", (unit["id"],)).fetchone()
            if existing and existing[0] != packed:
                raise ValueError("Содержимое существующей версии изменено; создайте новый id")
            if not existing:
                conn.execute("INSERT INTO units VALUES(?,?)", (unit["id"], packed))
                conn.execute("INSERT INTO law_fts VALUES(?,?,?,?)", (unit["id"], unit["act"], unit["article"], unit["text"]))
        conn.execute("INSERT OR IGNORE INTO snapshots VALUES(?,?)", (revision, json.dumps(data, ensure_ascii=False)))
        conn.execute("INSERT OR REPLACE INTO settings VALUES('latest_import',?)", (revision,))
        conn.commit()
        return {"import_revision": revision, "imported_units": len(units),
                "total_units": conn.execute("SELECT count(*) FROM units").fetchone()[0]}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure():
    if not _path().exists():
        import_snapshot()


def _public(unit):
    unit = dict(unit)
    unit["text_sha256"] = hashlib.sha256(unit["text"].encode()).hexdigest()
    unit["resource_uri"] = "law://unit/" + unit["id"]
    unit["verification_status"] = "source_excerpt_temporal_unverified"
    unit["limitation"] = "Фрагмент источника; применимая редакция и полнота корпуса не подтверждены."
    return unit


def search_law(query, limit=5, article=None):
    if not isinstance(query, str) or len(query) > 500:
        raise ValueError("Поисковый запрос: до 500 символов")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
        raise ValueError("Количество результатов: от 1 до 20")
    _ensure()
    # FTS operators supplied by callers are not executed.
    words = re.findall(r"[а-яёa-z0-9]+", query.lower())[:20]
    terms = " OR ".join('"' + word + '"*' for word in words)
    conn = sqlite3.connect(_path())
    try:
        if terms:
            rows = conn.execute("SELECT units.payload FROM law_fts JOIN units ON units.id=law_fts.id WHERE law_fts MATCH ? ORDER BY bm25(law_fts) LIMIT 200", (terms,)).fetchall()
        else:
            rows = conn.execute("SELECT payload FROM units ORDER BY id LIMIT 200").fetchall()
        units = [json.loads(row[0]) for row in rows]
        if article:
            units = [unit for unit in units if unit["article"] == str(article)]
        return {"hits": [_public(unit) for unit in units[:limit]], "count": min(len(units), limit),
                "scope": "Небольшой локальный индекс; сетевые запросы при поиске отсутствуют"}
    finally:
        conn.close()


def get_law_unit(unit_id):
    _ensure()
    conn = sqlite3.connect(_path())
    try:
        row = conn.execute("SELECT payload FROM units WHERE id=?", (unit_id,)).fetchone()
        if row is None:
            raise LookupError("Фрагмент нормы не найден")
        return _public(json.loads(row[0]))
    finally:
        conn.close()
