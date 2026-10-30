from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
import pytest
from app.parser import extract_bytes


def test_empty_text_rejected():
    with pytest.raises(ValueError):
        extract_bytes(b"  ", ".txt")


def test_broken_docx_rejected():
    with pytest.raises(ValueError, match="DOCX"):
        extract_bytes(b"not a zip file", ".docx")


def test_uncompressed_docx_limit():
    output=BytesIO()
    with ZipFile(output,"w",ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"A"*(41*1024*1024))
    with pytest.raises(ValueError, match="распакованный"):
        extract_bytes(output.getvalue(), ".docx")


def test_text_size_limit():
    with pytest.raises(ValueError, match="символов"):
        extract_bytes(b"a"*500001, ".txt")


def test_utf8_bom():
    assert extract_bytes("\ufeffУчебный текст".encode("utf-8"),".txt") == "Учебный текст"
