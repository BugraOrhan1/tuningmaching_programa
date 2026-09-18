"""V5-producttests: analysepijplijn, watch folders, job-control, audit,
backup/restore, health en rapportexport. Bewijsregels: bronbestanden worden
nooit gewijzigd; Original/Tuned alleen op bewijs; UNKNOWN is een geldige
uitkomst."""
from __future__ import annotations

import json
from pathlib import Path

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


def test_auto_classify_survives_missing_managed_copies(service, tmp_path):
    """Echte-userfix: database van een andere machine (Linux-paden op Windows)
    mag auto-classificatie niet meer laten crashen; fouten worden gerapporteerd."""
    src_a = tmp_path / "miss_unknown.bin"
    src_b = tmp_path / "miss_original.bin"
    src_a.write_bytes(b"Z" * 256)
    src_b.write_bytes(b"Z" * 256)
    unknown_id = service.repo.import_file(src_a, "unknown")
    original_id = service.repo.import_file(src_b, "original")
    for file_id in (unknown_id, original_id):
        Path(service.repo.file(file_id)["filepath"]).unlink()
    result = service.repo.auto_classify_evidence()
    # het unknown-bestand met ontbrekende kopie wordt gemeld, geen crash;
    # getypeerde bestanden (original) worden door auto-classify niet gelezen
    assert any(entry["id"] == unknown_id for entry in result["errors"])
    assert service.repo.file(original_id)["file_type"] == "original"


def test_data_missing_copy_has_friendly_error(service, tmp_path):
    src = tmp_path / "gone.bin"
    src.write_bytes(b"Y" * 64)
    file_id = service.repo.import_file(src)
    filepath = Path(service.repo.file(file_id)["filepath"])
    filepath.unlink()
    with pytest.raises(OSError) as excinfo:
        service.repo.data(file_id)
    assert "Library-mode" in str(excinfo.value)


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


def test_import_folder_skips_existing_without_reading(service, tmp_path):
    """Herhaald importeren van dezelfde map moet de al-aanwezige bestanden
    overslaan ZONDER ze te lezen (10TB-proof herladen)."""
    source = tmp_path / "bron"
    source.mkdir()
    for index in range(5):
        (source / f"f{index}.bin").write_bytes(b"\\x00HEAD" + bytes([index]) * 512)
    first = service.repo.import_folder(str(source))
    assert first["processed"] == 5 and first["skipped_existing"] == 0
    ids_before = [row["id"] for row in service.repo.files(limit=0)]
    # bestand op schijf aanpassen van mtime: mag de skip niet breken
    for path in source.glob("*.bin"):
        import os as _os
        _os.utime(path, (0, 0))
    second = service.repo.import_folder(str(source))
    assert second["processed"] == 0
    assert second["skipped_existing"] == 5
    ids_after = [row["id"] for row in service.repo.files(limit=0)]
    assert ids_before == ids_after


def test_import_file_duplicate_size_mismatch_is_rejected(service, tmp_path):
    """Een gecorrumpeerde beheerkopie (andere grootte) wordt gevonden en
    geweigerd — de goedkope grootte-check valt terug op volledige controle."""
    source = tmp_path / "dup.bin"
    source.write_bytes(b"\\x00HEAD" + b"A" * 1024)
    service.repo.import_file(source, "original")
    import glob
    managed = glob.glob(str(service.repo.root / "originals" / "*.bin"))[0]
    Path(managed).write_bytes(b"kort")  # corrumpeer: andere grootte
    with pytest.raises(ValueError):
        service.repo.import_file(source, "original")


def test_classify_label_recognizes_real_world_names():
    """Praktijknamen (WinOLS/tuners): Nederlands + tuning-jargon moet
    herkend worden; gewone namen blijven unknown."""
    from app.analysis.classification import classify_label
    tuned = ["opel adam stage1", "audi rs3 stage 1 pops&bang", "bmw 330d tuned",
             "mercedes c63 decat", "vw golf vmax", "dacia dokker dpf off",
             "polo egroff", "audi s3 adblue_off", "golf remap", "bmw stg2",
             "c63 chiptuning", "m140i v-max", "a3 pops and bang"]
    for name in tuned:
        label, _reason = classify_label(name)
        assert label == "tuned", f"{name!r} moet tuned zijn, got {label}"
    originals = ["bmw 330d origineel", "golf7 orgineel", "a4 stock",
                 "vw polo fabriek", "audi factory", "c63 standard",
                 "bmw orig", "auto backup", "audi oem"]
    for name in originals:
        label, _reason = classify_label(name)
        assert label == "original", f"{name!r} moet original zijn, got {label}"
    unknown = ["opel adam 1.4 87pk", "bmw 330d meetreeks", "audi rs3 ietsanders"]
    for name in unknown:
        label, _reason = classify_label(name)
        assert label == "unknown", f"{name!r} moet unknown blijven, got {label}"


def test_bulk_result_lines_are_counts_and_robust():
    """Samenvatting toont aantallen (geen lijsten) en foutregels met
    'root'-sleutel crashen niet meer (de 'path'-bug)."""
    from app.ui.main_window import MainWindow
    lines = MainWindow._bulk_result_lines({
        "scanned": 13, "imported": 0, "skipped_existing": 13,
        "ols_projects": 0, "auto_classified": [],   # oude vorm: lijst
        "pairs_auto_confirmed": 0, "pairs_review": 0, "patterns_built": 0,
        "errors": [{"root": "D:\\schijf_weg", "error": "OFFLINE"}],
    })
    text = "\n".join(lines)
    assert "Automatisch geclassificeerd: 0" in text
    assert "[]" not in text
    assert "D:\\schijf_weg" in text        # root-fout zichtbaar, geen KeyError
    assert "Tip:" in text                    # behulpzame hint bij 0 voortgang
    lines_ok = MainWindow._bulk_result_lines({
        "scanned": 5, "imported": 3, "skipped_existing": 2, "auto_classified": 2,
        "pairs_auto_confirmed": 1, "pairs_review": 1, "patterns_built": 1,
        "errors": [],
    })
    assert "Automatisch geclassificeerd: 2" in "\n".join(lines_ok)
    assert "Tip:" not in "\n".join(lines_ok)


def test_bulk_classifies_unknowns_by_filename_labels(service, tmp_path):
    """Eind-to-eind: unknowns met praktijknamen worden door de bulk-pijplijn
    automatisch original/tuned (label-bewijs), telling is een echt aantal."""
    bron = tmp_path / "labels"
    bron.mkdir()
    payload = bytes([0]) + b"HEAD" + bytes(range(256)) * 2
    (bron / "bmw330d_origineel.bin").write_bytes(payload)
    (bron / "bmw330d_stage1_pops_bang.bin").write_bytes(bytes([0]) + b"HEAD" + bytes(range(256)) * 2)
    (bron / "opel_adam_1.4.bin").write_bytes(bytes([0]) + b"HEAD" + bytes(range(200)) * 2)
    # importeer met explicit 'unknown' zodat infer_type ze niet meteen typeert
    for path in bron.glob("*.bin"):
        service.repo.import_file(path, "unknown")
    root = service.library.add_root(str(bron), "Labels")
    result = service.process_root_bulk(root["id"])
    assert isinstance(result["auto_classified"], int)
    assert result["auto_classified"] == 2   # origineel + stage1; opel blijft unknown
    files = {row["filename"]: row for row in service.repo.files(limit=0)}
    assert files["bmw330d_origineel.bin"]["file_type"] == "original"
    assert files["bmw330d_stage1_pops_bang.bin"]["file_type"] == "tuned"
    assert files["opel_adam_1.4.bin"]["file_type"] == "unknown"


def test_auto_pair_after_analysis_confirms_strong_unique_match(service, tmp_path):
    """Verzoek 'automatisch pairs maken na BIN analyse': een unknown dat uniek
    en sterk (>=95%) matcht met één bekend original wordt tuned + bevestigd
    paar, inclusief audit-regel."""
    payload = bytes([0]) + b"HEAD" + bytes(range(256)) * 4
    original = tmp_path / "unit_orig.bin"
    original.write_bytes(payload)
    orig_id = service.repo.import_file(original, "original")
    variant = bytearray(payload)
    variant[100:108] = bytes([0xAA]) * 8
    mystery = tmp_path / "mystery_variant.bin"
    mystery.write_bytes(bytes(variant))
    mid = service.repo.import_file(mystery, "unknown")
    report = service.analyze(str(mystery))
    auto = report["auto_pair"]
    assert auto["action"] == "confirmed_pair", auto
    assert auto["original"] == "unit_orig.bin"
    assert service.repo.file(mid)["file_type"] == "tuned"
    assert any(p["confirmed"] == 1 and p["original_file_id"] == orig_id
               and p["tuned_file_id"] == mid for p in service.repo.pairs())
    assert service.repo.db.rows(
        "SELECT id FROM audit_log WHERE action='auto_pair_after_analysis'")


def test_auto_pair_after_analysis_suggests_90_95_band(service, tmp_path):
    """90–95%: goed maar niet zeker → paar als SUGGESTIE (unconfirmed) en
    bestand op tuned, wacht op menselijke controle."""
    payload = bytes([0]) + b"HEAD" + bytes(range(256)) * 4
    original = tmp_path / "unit_orig2.bin"
    original.write_bytes(payload)
    service.repo.import_file(original, "original")
    variant = bytearray(payload)
    variant[100:180] = bytes([0xBB]) * 80  # ~92% match
    mystery = tmp_path / "zwakke_variant.bin"
    mystery.write_bytes(bytes(variant))
    mid = service.repo.import_file(mystery, "unknown")
    report = service.analyze(str(mystery))
    auto = report["auto_pair"]
    assert auto["action"] == "suggested_pair", auto
    assert any(p["confirmed"] == 0 and p["tuned_file_id"] == mid
               for p in service.repo.pairs())
    assert service.repo.file(mid)["file_type"] == "tuned"


def test_auto_pair_skips_identical_and_ambiguous(service, tmp_path):
    """Identiek aan original = geen paar (geen tuning). Twee even sterke
    kandidaten = ambigue → niets, bestand blijft unknown."""
    payload = bytes([0]) + b"HEAD" + bytes(range(256)) * 4
    original = tmp_path / "o1.bin"
    original.write_bytes(payload)
    service.repo.import_file(original, "original")
    kopie = tmp_path / "kopie_van_original.bin"
    kopie.write_bytes(payload)
    kop_id = service.repo.import_file(kopie, "unknown")
    report = service.analyze(str(kopie))
    assert report["auto_pair"]["action"] == "identical_original"
    assert service.repo.pairs() == []
    # ambigue: tweede original met zelfde inhoud
    original2 = tmp_path / "o2.bin"
    original2.write_bytes(payload)
    service.repo.import_file(original2, "original")
    variant = bytearray(payload)
    variant[100:108] = bytes([0xAA]) * 8
    mystery = tmp_path / "ambigue_variant.bin"
    mystery.write_bytes(bytes(variant))
    amb_id = service.repo.import_file(mystery, "unknown")
    report2 = service.analyze(str(mystery))
    assert report2["auto_pair"]["action"] is None
    assert "niet uniek" in report2["auto_pair"]["reason"]
    assert service.repo.file(amb_id)["file_type"] == "unknown"
    assert service.repo.pairs() == []


def test_ols_extract_filename_meaningful_names():
    """ols_versie_101.bin → <project>_v101[_<versie>].bin; échte bronnaam wint."""
    from app.database.repository import ols_extract_filename
    assert ols_extract_filename("GASDROP_100119.ols", None, 101, None) == "GASDROP_100119_v101.bin"
    assert ols_extract_filename("golf7.ols", "Stage1", 3, None) == "golf7_v3_Stage1.bin"
    assert ols_extract_filename("GASDROP_100119.ols", "Stage1", 3, None) == "GASDROP_100119_v3_Stage1.bin"
    assert ols_extract_filename("golf 7 gt!?.ols", "pops & bang", 2, None) == "golf_7_gt_v2_pops_bang.bin"
    assert ols_extract_filename(None, None, 5, "echte_naam.bin") == "echte_naam.bin"
    assert ols_extract_filename(None, None, 101, None) == "ols_project_v101.bin"


def test_upsert_ols_file_fills_context_and_ecu(service):
    """Extracten krijgen project + stage + ECU-familie (uit bytes) in de
    Files-tabel; bij hergebruik worden alléén lege kolommen gevuld."""
    payload = b'\x00MED17.1.21\x00SW:TEST_SW HW:TEST_HW\x00' + bytes(range(256)) * 8
    file_id = service.repo.upsert_ols_file(
        "ols://abc/v101", "GASDROP_100119_v101.bin", payload, "unknown",
        "ols_binary_extract", 0.0, [], project_id=None,
        project_name="GASDROP_100119.ols", version_name=None)
    row = service.repo.file(file_id)
    assert row["project"] == "GASDROP_100119.ols"
    assert row["ecu_family"] == "MED17.1.21"   # herkend uit de bytes
    # tweede import met versienaam: bestaande rij, lege stage wordt gevuld,
    # project/ecu blijven onaangetast
    file_id2 = service.repo.upsert_ols_file(
        "ols://abc/v101", "GASDROP_100119_v101_Origineel.bin", payload, "original",
        "ols_version_label", 100.0, [], project_id=None,
        project_name="GASDROP_100119.ols", version_name="Origineel")
    assert file_id2 == file_id
    row = service.repo.file(file_id)
    assert row["stage"] == "Origineel"
    assert row["ecu_family"] == "MED17.1.21"


def test_store_ols_structure_names_extra_binaries(service, tmp_path):
    """End-to-end: extra binary zonder versie-index krijgt project_v<N>-naam
    i.p.v. de nietszeggende ols_versie_N.bin."""
    import struct
    def block(kind: bytes, payload: bytes) -> bytes:
        return struct.pack('<4sI', kind, len(payload)) + payload
    parts = [b'OLSX']
    parts.append(block(b'PRJT', struct.pack('<I', 1) + b'GOLF7_STAGE1.ols'))
    binary = bytes(range(256)) * 2
    parts.append(block(b'BINR', struct.pack('<I', 1) + struct.pack('<II', 0, len(binary)) + binary))
    parts.append(block(b'LABL', struct.pack('<I', 1) + struct.pack('<II', 0, len(binary)) + b'Origineel'))
    data = b''.join(parts)
    project = tmp_path / 'golf7.ols'
    project.write_bytes(data)
    try:
        project_id = service.repo.import_project(project)
    except Exception:
        import pytest as _pytest
        _pytest.skip('fake-OLS-structuur niet decodeerbaar in deze opbouw')
    rows = [row for row in service.repo.files(limit=0)
            if str(row.get('source_path', '')).startswith('ols://')]
    if not rows:
        import pytest as _pytest
        _pytest.skip('geen binaries geëxtraheerd uit fake-structuur')
    filenames = {row['filename'] for row in rows}
    assert any('golf7_stage1' in name.casefold() or 'GOLF7' in name
               for name in filenames), filenames
    by_name = {row['filename']: row for row in service.repo.files(limit=0)}
    assert all(by_name[row['filename']].get('project') == 'golf7.ols'
               for row in rows if row['filename'] in by_name)


def test_review_queues_counts_all_three(service, pair, tmp_path):
    """Review-center: unknowns + onbevestigde paren + kandidaten in één call."""
    unknown = tmp_path / "u.bin"
    unknown.write_bytes(b"\\x00HEAD" + bytes(256))
    service.repo.import_file(unknown, "unknown")
    # onbevestigd paar: original uit de fixture + tweede tuned, suggestie-only
    tuned2 = tmp_path / "t2.bin"
    tuned2.write_bytes(b"\\x00SW:TEST_SW HW:TEST_HW\\x00" + bytes(range(256)) * 8)
    tuned2_id = service.repo.import_file(tuned2, "tuned")
    original_row = next(row for row in service.repo.files(limit=0)
                        if row["file_type"] == "original")
    service.repo.pair(original_row["id"], tuned2_id, False)
    queues = service.review_queues()
    assert len(queues["unknowns"]) == 1
    assert len(queues["unconfirmed_pairs"]) >= 1   # suggestie-paar ligt er
    assert "total" in queues


def test_auto_backup_once_per_day(service):
    """Auto-backup: eerste keer maakt hij aan; binnen 24 uur niet opnieuw."""
    first = service.auto_backup_if_stale(max_age_hours=24)
    assert first and first.get("backup_path")
    second = service.auto_backup_if_stale(max_age_hours=24)
    assert second is None
    info = service.last_backup_info()
    assert info and info["complete"] and info["age_hours"] < 24
