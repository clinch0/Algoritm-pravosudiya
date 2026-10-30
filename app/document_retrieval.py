"""Bounded lexical retrieval over already masked documents, never originals."""
import hashlib
import re

STOP = {"какие", "какой", "этого", "которые", "также", "можно", "нужно", "гражданин"}


def terms(text):
    return {w[:6] for w in re.findall(r"[а-яёa-z0-9]{3,}", text.casefold()) if w not in STOP}


def retrieve_documents(documents, question, limit=4):
    query = terms(question)
    candidates = []
    for document in documents:
        text = document["text"]
        # Sentence/paragraph boundaries avoid breaking entity tokens in half.
        parts = re.split(r"(?<=[.!?])\s+|\n+", text)
        chunks, current = [], ""
        for part in parts:
            if len(current) + len(part) > 1400 and current:
                chunks.append(current)
                current = ""
            current += ("\n" if current else "") + part
        if current:
            chunks.append(current)
        for index, chunk in enumerate(chunks):
            # Extremely long unbroken paragraphs are omitted, never silently cut.
            if len(chunk) > 4000:
                continue
            score = len(query & terms(chunk))
            if not score:
                continue
            digest = hashlib.sha256(chunk.encode()).hexdigest()[:12]
            candidates.append((score, {"id": f"doc:{document['id']}:{index}:{digest}",
                "document_id": document["id"], "chunk": index, "text": chunk,
                "kind": "case_document", "limitation": "Фрагмент документа стороны; не установленный судом факт."}))
    candidates.sort(key=lambda x: (-x[0], x[1]["id"]))
    result, size = [], 0
    for _, chunk in candidates:
        if len(result) >= limit:
            break
        if size + len(chunk["text"]) <= 6000:
            result.append(chunk)
            size += len(chunk["text"])
    return result
