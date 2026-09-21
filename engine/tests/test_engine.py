"""TuningCore-tests: parser, scan, piplijn, paren, resume, fout-isolatie.

De synthetische OLS-builder (tuningcore.sample) volgt de bewezen structuur
van een echte WinOLS 5-export: length-prefixed ASCII-records in de header,
nul-padding, versiepagina's met identiteitsheader op vaste afstand en
pagina's die ≥99% identiek zijn (zoals echte versies).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tuningcore import olsparse                      # noqa: E402
from tuningcore.db import connect                    # noqa: E402
from tuningcore.labels import role_from_name, stage_from_name  # noqa: E402
from tuningcore.process import parse_pending         # noqa: E402
from tuningcore.sample import build_ols              # noqa: E402
from tuningcore.scan import scan                     # noqa: E402


def test_role_and_stage_labels():
    assert role_from_name("Origineel v1")[0] == "original"
    assert role_from_name("original stock")[0] == "original"
    assert role_from_name("Stage 1 v2 tune")[0] == "tuned"
    assert role_from_name("Vmax pops")[0] == "tuned"
    assert role_from_name("onduidelijk")[0] == "unknown"
    assert stage_from_name("WinOLS 5 VW Golf Stage 1") == "stage1"
    assert stage_from_name("stage3 mod") == "stage3"
    assert stage_from_name("origineel") is None


def test_parse_ols_versions_and_binaries():
    binary_a = bytes(2048)
    binary_b = bytes(2047) + b"\x11"          # ≥99% identiek, zoals echte versies
    data = build_ols("1/1/EDC17/C64/BOSCH",
                     [("origineel v1", binary_a), ("stage 1 tuned v2", binary_b)])
    result = olsparse.parse_ols(data)
    assert result["signature"] == "WinOLS File"
    roles = {version["name"]: version["role"] for version in result["versions"]}
    assert roles.get("origineel v1") == "original"
    assert roles.get("stage 1 tuned v2") == "tuned"
    complete = [version for version in result["versions"] if version.get("complete")]
    assert len(complete) == 2
    assert all(version.get("binary_sha256") for version in complete)
    stages = {version["name"]: version.get("stage") for version in result["versions"]}
    assert stages.get("stage 1 tuned v2") == "stage1"


def test_parse_real_gasdrop_file():
    gasdrop = Path(__file__).resolve().parents[2] / "data" / "winols_projects" / "GASDROP_100119.ols"
    if not gasdrop.exists():
        pytest.skip("GASDROP-testbestand niet aanwezig")
    result = olsparse.parse_ols_file(str(gasdrop))
    assert result["signature"] == "WinOLS File"
    assert len(result["versions"]) == 4          # identiek aan oude structuurparser
    roles = [version["role"] for version in result["versions"]]
    assert "original" in roles and "tuned" in roles


def test_scan_hash_parse_pairs_end_to_end(tmp_path):
    root = tmp_path / "bron"
    root.mkdir()
    for index in range(3):
        (root / f"proj_{index}.ols").write_bytes(
            build_ols(f"1/1/EDC17/E{index}/BOSCH",
                      [("origineel", bytes(2048)),
                       ("stage 1 tuned", bytes(2047) + b"\x22")]))
    db = connect(tmp_path / "core.db")
    stats = scan(db, str(root))
    assert stats["new"] == 3 and stats["errors"] == 0
    pipeline = parse_pending(db, workers=2)
    assert pipeline["parsed"] == 3
    assert pipeline["versions"] == 6
    assert pipeline["pairs"] == 3                 # 1 origineel × 1 stage1 per project
    status = db.execute(
        "SELECT COUNT(*) FROM pairs WHERE state='suggested'").fetchone()[0]
    assert status == 3


def test_rescan_is_cached(tmp_path):
    root = tmp_path / "bron"
    root.mkdir()
    (root / "a.ols").write_bytes(build_ols("1/1/EDC17/X/BOSCH",
                                           [("origineel", bytes(4096)),
                                            ("stage 1", bytes(4095) + b"\x11")]))
    db = connect(tmp_path / "core.db")
    first = scan(db, str(root))
    assert first["new"] == 1
    second = scan(db, str(root))
    assert second["new"] == 0 and second["unchanged"] == 1


def test_corrupt_ols_is_logged_not_crashing(tmp_path):
    root = tmp_path / "bron"
    root.mkdir()
    (root / "good.ols").write_bytes(build_ols("1/1/EDC17/Y/BOSCH",
                                              [("origineel", bytes(4096)),
                                               ("stage 1", bytes(4095) + b"\x11")]))
    (root / "rot.ols").write_bytes(b" NOG EEN HEEL ANDER BESTAND \x00\x01")
    db = connect(tmp_path / "core.db")
    scan(db, str(root))
    pipeline = parse_pending(db, workers=1)
    assert pipeline["parsed"] == 1
    assert pipeline["errors"] == 1
    error = db.execute("SELECT path, message FROM errors WHERE phase='ols_parse'").fetchone()
    assert error and "rot.ols" in error["path"]


def test_parse_resume_skips_already_parsed(tmp_path):
    root = tmp_path / "bron"
    root.mkdir()
    for index in range(4):
        (root / f"p{index}.ols").write_bytes(
            build_ols(f"1/1/EDC17/Z{index}/BOSCH",
                      [("origineel", bytes(4096)),
                       ("stage 1", bytes(4095) + b"\x11")]))
    db = connect(tmp_path / "core.db")
    scan(db, str(root))
    first = parse_pending(db, workers=2)
    assert first["parsed"] == 4
    second = parse_pending(db, workers=2)
    assert second["pending"] == 0 and second["parsed"] == 0
