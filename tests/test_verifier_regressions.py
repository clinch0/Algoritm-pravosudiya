"""Corrupt the documented exception: a verifier must report new discrepancies."""
import json
from pathlib import Path
import pytest
from tools import verify_sanctions


@pytest.mark.parametrize("maximum", [5, 40, None])
def test_known_parser_artifact_does_not_hide_changed_sanction(tmp_path, monkeypatch, maximum):
    source = Path(__file__).resolve().parents[1] / "data"
    sanctions = json.loads((source / "ukrf_sanctions.json").read_text(encoding="utf-8"))
    row = next(x for x in sanctions["articles"] if (x["article"], x["part"]) == ("109", "3"))
    row["imprisonment_max_years"] = maximum
    (tmp_path / "ukrf_sanctions.json").write_text(json.dumps({"articles": [row]}), encoding="utf-8")
    (tmp_path / "ukrf_articles_text.json").write_bytes((source / "ukrf_articles_text.json").read_bytes())
    monkeypatch.setattr(verify_sanctions, "DATA", tmp_path)
    assert verify_sanctions.main() == 1
