"""Boundary regressions: unknown qualification and local MCP paths."""
import pytest
from app import ukrf
from app.extractor import extract
from app.checker import check
from app.schemas import CaseParameters


def test_missing_part_is_not_invented():
    p = extract("Осужден по ст. 158 УК РФ, лишение свободы сроком 3 года.", "TEST")
    assert p.article == "158"
    assert p.part is None
    assert "MISSING_PART" in p.review_flags
    assert ukrf.get_sanction(p.article, p.part) is None
    assert check(p, None).ok is None


def test_explicit_sanction_cannot_hide_missing_part():
    p = CaseParameters(case_id="T", article="158", punishment_type="лишение свободы", punishment_years=3)
    result = check(p, ukrf.get_sanction("158", "1"))
    assert result.ok is None
    assert any("SANCTION_MISMATCH" in w for w in result.warnings)


@pytest.mark.parametrize("path", [r"\\example.invalid\share\file.docx", "//example.invalid/share/file.docx", r"\\?\C:\secret.docx"])
def test_mcp_network_paths_rejected_before_filesystem_lookup(monkeypatch, path):
    import mcp_server.server as server
    def forbidden(*args, **kwargs):
        raise AssertionError("Filesystem lookup attempted")
    monkeypatch.setattr(server.Path, "resolve", forbidden)
    assert "Сетевые" in server.analyze_document(path)["error"]
