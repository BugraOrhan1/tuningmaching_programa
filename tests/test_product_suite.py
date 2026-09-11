"""V5-producttests: analysepijplijn, watch folders, job-control, audit,
backup/restore, health en rapportexport. Bewijsregels: bronbestanden worden
nooit gewijzigd; Original/Tuned alleen op bewijs; UNKNOWN is een geldige
uitkomst."""
from __future__ import annotations

import json

import pytest

from app.service import Service


@pytest.fixture()
def library(service, tmp_path):
    root = tmp_path / "Lib"
    root.mkdir()
    (root / "a.bin").write_bytes(b"AAABBBCCC" * 4)
    (root / "b.bin").write_bytes(b"XXXYYYZZZ" * 4)
    (root / "copy_of_a.bin").write_bytes(b"AAABBBCCC" * 4)
    library = service.library.add_root(str(root))
    service.library.scan_root(library["id"])
    return library


def test_analyze_content_dedups_knowledge(service, library):
    content_id = service.library.locations(library["id"], "a.bin")[0]["content_id"]
    first = service.library.analyze_content(content_id)
    assert first["status"] == "analyzed"
    # identieke content (copy_of_a) deelt het content-object: tweede analyse is een cache-hit
    duplicate = service.library.locations(library["id"], "copy_of_a.bin")[0]
    assert duplicate["content_id"] == content_id
    again = service.library.analyze_content(content_id)
    assert again["status"] == "cached"
    summary = service.library.storage_summary()
    assert summary["unique_contents"] == 2  # a + b, geen derde
    assert service.library.content(content_id)["analysis_state"] == "ANALYZED"


def test_analyze_pending_resumable_and_error_safe(service, tmp_path):
    root = tmp_path / "Lib2"
    root.mkdir()
    for index in range(5):
        (root / f"f{index}.bin").write_bytes(bytes([index]) * 128)
    (root / "bad.bin").write_bytes(b"corrupt")
    library = service.library.add_root(str(root))
    service.library.scan_root(library["id"])
    # alles analyseren: het corrupte bestand stopt de taak niet (§52)
    report = service.library.analyze_pending(resume=False)
    assert report["status"] == "done"
    assert report["analyzed"] + report["linked"] >= 5
    # tweede run: niets meer te doen (dedup van werk)
    second = service.library.analyze_pending(resume=False)
    assert second["status"] == "done"
    assert second["analyzed"] + second["linked"] == 0


def test_watch_policy_never_auto_original_tuned(service, tmp_path):
    root = tmp_path / "Incoming"
    root.mkdir()
    (root / "new.bin").write_bytes(b"FRESH" * 16)
    library = service.library.add_root(str(root))
    service.library.set_watch(library["id"], True,
                              policy={"auto_analyze": True,
                                      "classify_exact_duplicates": True})
    report = service.library.process_watch()
    assert report["roots"] and report["new"] >= 1
    rows = service.repo.db.rows(
        "SELECT DISTINCT file_type FROM files")
    # geen enkele file is zonder technicus/bewijs original of tuned geworden
    assert all(row["file_type"] in ("unknown",) for row in rows), rows
    # exact-duplicate regel classifyt alléén bij byte-identiek getypeerd bewijs
    assert report["classified"] == 0


def test_library_search_finds_by_name_and_hash(service, library):
    result = service.library.search("a.bin")
    assert result["count"] >= 1
    sha = service.library.locations(library["id"], "a.bin")[0]["sha256"]
    by_hash = service.library.search(sha[:16])
    assert by_hash["count"] >= 1


def _pair(service, tmp_path, index, tweak):
    source = tmp_path / f"src{index}"
    source.mkdir()
    original = b"\x00SW:P" + str(index).encode() + b" HW:PH\x00" + bytes(range(256)) * 8
    tuned = bytearray(original)
    tuned[tweak:tweak + 4] = b"\xff" * 4
    a, b = source / f"original_00{index}.bin", source / f"tuned_00{index}.bin"
    a.write_bytes(original)
    b.write_bytes(tuned)
    aid, bid = service.repo.import_file(a), service.repo.import_file(b)
    return service.repo.pair(aid, bid, True)


def test_job_pause_resume_cancel_on_pattern_rebuild(service, tmp_path):
    for index in range(1, 4):
        _pair(service, tmp_path, index, 100 * index)

    def pause_midway(_message):
        latest = service.jobs()[0]
        if latest["status"] == "running":
            service.job_pause(latest["id"])

    result = service.rebuild_patterns(batch_size=1, resume=False, progress=pause_midway)
    assert result["status"] == "paused"
    run_id = result["run_id"]
    checkpoint = service.job(run_id)["checkpoint"]
    assert "last_pair_id" in checkpoint
    # hervatten: de run loopt door tot done
    resumed = service.job_resume(run_id)
    assert resumed["status"] == "done"
    assert service.repo.run_status(run_id) == "done"
    # annuleren van een gepauzeerde run
    second_run = service.repo.start_run("pattern_rebuild", {"batch_size": 1})
    service.repo.pause_run(second_run, {}, {})
    cancelled = service.job_cancel(second_run)
    assert cancelled["status"] == "cancelled"


def test_analyze_pending_pause_and_resume(service, tmp_path):
    root = tmp_path / "LibPause"
    root.mkdir()
    for index in range(6):
        (root / f"g{index}.bin").write_bytes(bytes([index + 1]) * 64)
    library = service.library.add_root(str(root))
    service.library.scan_root(library["id"])
    state = {"paused": False}

    def pause_midway(_message):
        if not state["paused"]:
            latest = service.jobs()[0]
            if latest["run_type"] == "library_analysis" and latest["status"] == "running":
                service.job_pause(latest["id"])
                state["paused"] = True

    paused = service.library.analyze_pending(resume=False, progress=pause_midway)
    assert paused["status"] == "paused"
    resumed = service.job_resume(paused["run_id"])
    assert resumed["status"] == "done"


def test_audit_log_records_review_actions(service, tmp_path):
    source = tmp_path / "audit_src"
    source.mkdir()
    original = b"\x00SW:AU HW:AH\x00" + bytes(range(256)) * 8
    tuned = bytearray(original)
    tuned[64:68] = b"\xff" * 4
    a, b = source / "original_001.bin", source / "tuned_001.bin"
    a.write_bytes(original)
    b.write_bytes(tuned)
    aid, bid = service.repo.import_file(a), service.repo.import_file(b)
    pair_id = service.repo.pair(aid, bid)
    service.repo.confirm_pair(pair_id)
    # los bestand herclassificeren (gekoppelde bestanden zijn vergrendeld)
    loose = source / "loose.bin"
    loose.write_bytes(b"UNCLASSIFIED" * 32)
    loose_id = service.repo.import_file(loose)
    service.repo.reclassify_files([loose_id], "original")
    service.review_pattern(1, "mark_unknown", reviewer="jan", note="onvoldoende bewijs")
    entries = service.audit_log()
    actions = {entry["action"] for entry in entries}
    assert {"confirm_pair", "reclassify", "mark_unknown"} <= actions
    reclassified = [entry for entry in entries if entry["action"] == "reclassify"][0]
    assert json.loads(reclassified["before_state"])["file_type"] == "unknown"
    assert json.loads(reclassified["after_state"])["file_type"] == "original"


def test_backup_restore_roundtrip_and_health(service, tmp_path):
    # staat opbouwen
    (tmp_path / "src.bin").write_bytes(b"K" * 512)
    file_id = service.repo.import_file(tmp_path / "src.bin")
    before_counts = service.health_check()["row_counts"]["files"]
    backup = service.backup(str(tmp_path / "backups"))
    # mutatie na backup
    (tmp_path / "src2.bin").write_bytes(b"L" * 512)
    service.repo.import_file(tmp_path / "src2.bin")
    assert service.health_check()["row_counts"]["files"] == before_counts + 1
    # herstellen: oude staat terug, veiligheidsbackup gemaakt
    result = service.restore(backup["backup_path"])
    assert service.health_check()["row_counts"]["files"] == before_counts
    assert result["safety_backup"]
    # manifest-manipulatie wordt geweigerd
    import hashlib
    from pathlib import Path as P
    manifest_path = P(backup["backup_path"]) / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["database_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        service.restore(backup["backup_path"])


def test_health_check_reports_ok(service):
    health = service.health_check()
    assert health["status"] == "OK"
    assert health["integrity"] == "ok"
    assert health["orphans"]["regions_without_pair"] == 0


def test_export_report_formats(service, tmp_path):
    (tmp_path / "z.bin").write_bytes(b"M" * 512)
    file_id = service.repo.import_file(tmp_path / "z.bin")
    outputs = {}
    for fmt in ("json", "csv", "md", "html"):
        result = service.export_report("new_bin", file_id, fmt,
                                       str(tmp_path / f"rapport.{fmt}"))
        outputs[fmt] = result["path"]
    assert "overall_confidence" in open(outputs["json"]).read()
    assert outputs["csv"].endswith(".csv")
    assert "# New Bin" in open(outputs["md"]).read()
    html_text = open(outputs["html"]).read()
    assert "<html" in html_text and "TECHNICIAN REVIEW" in html_text
    # HTML ontsnapt gevaarlijke tekens
    malicious = service.export_report("library", None, "html",
                                      str(tmp_path / "xss.html")) if False else None
    from app.reporting import export_report
    evil_path = export_report({"report": "x", "note": "<script>alert(1)</script>"},
                              "html", str(tmp_path / "evil.html"))
    assert "<script>" not in open(evil_path).read()
    with pytest.raises(ValueError):
        export_report({"report": "x"}, "pdf", str(tmp_path / "no.pdf"))


def test_new_bin_library_multistage(service, tmp_path):
    root = tmp_path / "Lib3"
    root.mkdir()
    (root / "known.bin").write_bytes(b"PAYLOAD" * 64)
    library = service.library.add_root(str(root))
    service.library.scan_root(library["id"])
    content_id = service.library.locations(library["id"], "known.bin")[0]["content_id"]
    service.library.analyze_content(content_id)
    # stage 1: exacte content-hit → kennis hergebruikt, geen nieuwe analyse
    report = service.new_bin_library_report(str(root / "known.bin"))
    assert report["stages"][0]["name"] == "exact_sha256"
    assert report["stages"][0]["hits"] == 1
    assert "hergebruikt" in report["note"]
    # onbekend bestand: volledige multi-stage pijplijn
    (tmp_path / "fresh.bin").write_bytes(b"OTHER" * 64)
    fresh = service.new_bin_library_report(str(tmp_path / "fresh.bin"))
    assert fresh["stages"][0]["hits"] == 0
    assert any(stage["name"] == "fingerprint_prefilter" for stage in fresh["stages"])
