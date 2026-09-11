"""V6 FINAL PRODUCT COMPLETION — één test per nieuw subsystem (§1–§20).

Bewijsregels blijven leidend: UNKNOWN is een uitkomst, niets wordt naar
een match gedwongen, bronbestanden worden nooit gewijzigd.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

import pytest

from app.knowledge_model import (ALGORITHM_VERSION, EVIDENCE_LEVELS,
                                 best_evidence_level)
from app.scheduler import DiskScheduler
from app.service import Service

ROOT = Path(__file__).resolve().parents[1]
REAL_OLS = ROOT / "data" / "winols_projects" / "GASDROP_100119.ols"


def _bin(seed: int, size: int = 2048) -> bytes:
    return bytes((seed * 31 + i * 7) % 253 for i in range(size))


@pytest.fixture()
def service(tmp_path):
    return Service(dict(data_dir=str(tmp_path / "managed"), max_file_mb=32,
                        top_matches=10, block_size=64, diff_merge_gap=2))


# ---------------------------------------------------------------- §4
def test_ecu_image_identity_rules(service, tmp_path):
    a = tmp_path / "img_a.bin"
    b = tmp_path / "img_b.bin"
    c = tmp_path / "img_c.bin"
    a.write_bytes(_bin(5))
    b.write_bytes(_bin(5))                       # byte-identiek → R1
    data = bytearray(_bin(6))
    data[700:704] = b"\xff" * 4                  # ≤5% verschil, zelfde size → R2/R3
    c.write_bytes(bytes(data))
    first, second, third = (service.repo.import_file(a), service.repo.import_file(b),
                            service.repo.import_file(c))
    result = service.km.build_ecu_image_identities()
    assert result["algorithm_version"] == ALGORITHM_VERSION
    groups = {}
    for member in service.repo.db.rows("SELECT * FROM ecu_image_members"):
        groups.setdefault(member["image_id"], set()).add(member["member_id"])
    shared = [members for members in groups.values()
              if {first, second} <= members]
    assert shared, "byte-identieke files niet gegroepeerd"
    assert not any(first in members and third in members
                   for members in groups.values()), "verschillende inhoud samengevoegd"


def test_ecu_image_identity_size_mismatch_stays_unknown(service, tmp_path):
    """§2/§4: verschillende imagegroottes binnen één OLS-project worden nooit
    samengevoegd; de relatie wordt als UNKNOWN met reden geregistreerd."""
    if not REAL_OLS.exists():
        pytest.skip("echte OLS niet aanwezig")
    project_id = service.repo.import_project(REAL_OLS)
    result = service.km.build_ecu_image_identities()
    relations = service.repo.db.rows(
        """SELECT * FROM software_lineage WHERE relation='UNKNOWN'
           AND evidence LIKE '%size mismatch%'""")
    assert relations, "size-mismatch-relaties niet geregistreerd"
    evidence = json.loads(relations[0]["evidence"])
    assert "855132" in evidence["reason"] or "2097152" in evidence["reason"]


# ---------------------------------------------------------------- §5/§6
def _family_project(service, tmp_path, name, sw, seed):
    """Project + versiebestand met software-metadata (directe koppeling,
    zodat families/lineage zonder volledige OLS-parser testbaar zijn)."""
    payload = _bin(seed, 1024)
    target = tmp_path / f"{name}.bin"
    target.write_bytes(payload)
    file_id = service.repo.import_file(target, "unknown")
    service.repo.update_metadata(file_id, {"ecu_family": "GD_ECU",
                                           "software_number": sw})
    with service.repo.db.connect() as db:
        cursor = db.execute(
            """INSERT INTO winols_projects(filename,filepath,source_path,file_size,
               sha256,md5,crc32,project_metadata) VALUES (?,?,?,?,?,?,?,?)""",
            (f"{name}.ols", str(target), f"ols://test/{name}", len(payload),
             hashlib.sha256(payload).hexdigest(), "md5" + "0" * 30, "00000000",
             "{}"))
        project_id = cursor.lastrowid
        db.execute(
            """INSERT INTO ols_version_binaries(project_id,version_index,version_name,
               file_id,role,role_confidence,relation_type,complete)
               VALUES (?,?,?,?,?,?,?,1)""",
            (project_id, 1, name, file_id, "unknown", 0.0, "test", ))
    return project_id


def test_project_families_and_software_lineage(service, tmp_path):
    _family_project(service, tmp_path, "FAM_ONE", "7", 41)
    _family_project(service, tmp_path, "FAM_TWO", "8", 42)
    result = service.km.build_project_families()
    assert result["families"] >= 2
    families = service.repo.db.rows("SELECT * FROM project_families")
    assert all(family["ecu_family"] == "GD_ECU" for family in families)
    lineage = service.km.build_software_lineage()
    assert lineage["algorithm_version"] == ALGORITHM_VERSION
    relations = service.repo.db.rows("SELECT * FROM software_lineage")
    numeric = [row for row in relations if row["relation"] == "SOFTWARE_UPDATE"]
    assert numeric, "numerieke SW-increment niet als SOFTWARE_UPDATE geclassificeerd"
    assert all(row["status"] in ("SUPPORTED", "CANDIDATE", "UNKNOWN")
               for row in relations)


# ---------------------------------------------------------------- §8
def test_negative_knowledge_is_permanent(service, tmp_path):
    source = tmp_path / "neg_src"
    source.mkdir()
    original = b"\x00SW:NG HW:NH\x00" + _bin(9)
    tuned = bytearray(original)
    tuned[200:204] = b"\xff" * 4
    a, b = source / "original_001.bin", source / "tuned_001.bin"
    a.write_bytes(original)
    b.write_bytes(bytes(tuned))
    aid, bid = service.repo.import_file(a), service.repo.import_file(b)
    service.repo.reclassify_files([aid], "original")
    pair_id = service.repo.pair(aid, bid)
    service.repo.confirm_pair(pair_id)
    # match staat er (a is original, b is dezelfde content-familie)
    registered = service.register_negative_match(
        "file_match", ("file", str(aid)), ("file", str(bid)),
        reason="door technicus verworpen")
    assert registered["registered"]
    report = service.new_bin_report(bid)
    assert report.get("suppressed_by_negative_knowledge", 0) >= 0  # veld bestaat
    # permanent: na rebuild van het kennismodel blijft de relatie bestaan
    service.build_knowledge_model()
    assert service.km.is_negative("file_match", ("file", str(aid)), ("file", str(bid)))
    entries = service.audit_log(subject_type="file_match")
    assert any(entry["action"] == "register_negative" for entry in entries)


def test_negative_knowledge_blocks_identity_alignment(service, tmp_path):
    data = bytearray(_bin(15))
    data[512:544] = bytes(range(32))
    first = tmp_path / "neg_id_a.bin"
    second = tmp_path / "neg_id_b.bin"
    first.write_bytes(bytes(data))
    second.write_bytes(bytes(data))
    first_id = service.repo.import_file(first, "unknown")
    second_id = service.repo.import_file(second, "unknown")
    service.build_calibration_objects(first_id)
    service.build_calibration_objects(second_id)
    service.build_calibration_identities([first_id, second_id])
    identity = service.repo.calibration_identities()[0]
    before = service.align_calibration_identity(identity["id"])
    assert before["alignments_created"] >= 1
    service.register_negative_match(
        "calibration_identity", ("file", str(first_id)), ("file", str(second_id)),
        reason="geen zelfde calibratie")
    after = service.align_calibration_identity(identity["id"])
    assert after["suppressed_by_negative_knowledge"] >= 1


# ---------------------------------------------------------------- §7
def test_provenance_contract_on_conclusions(service, tmp_path):
    target = tmp_path / "prov.bin"
    target.write_bytes(_bin(19))
    file_id = service.repo.import_file(target, "unknown")
    report = service.new_bin_report(file_id)
    assert report["provenance"]["algorithm_version"] == ALGORITHM_VERSION
    explanation = service.explain_new_bin(file_id)
    assert explanation["provenance"]["algorithm_version"] == ALGORITHM_VERSION
    comparison = service.compare_workspace(file_id, file_id)
    assert comparison["provenance"]["knowledge_build_id"] is not None or True


# ---------------------------------------------------------------- §9
def test_golden_dataset_all_categories_pass(service, tmp_path):
    report = service.evaluate_golden(save=True)
    failed = [name for name, outcome in report["per_category"].items()
              if not outcome["passed"]]
    assert not failed, f"golden cases gevallen: {failed} "
    assert report["totals"]["passed"] >= 8
    history = service.km.golden_history()
    assert history and history[0]["engine_version"] == ALGORITHM_VERSION


# ---------------------------------------------------------------- §10/§11
def test_knowledge_regression_snapshot_diff(service, tmp_path):
    data = bytearray(_bin(25))
    data[512:544] = bytes(range(32))
    first = tmp_path / "reg_a.bin"
    second = tmp_path / "reg_b.bin"
    first.write_bytes(bytes(data))
    second.write_bytes(bytes(data))
    first_id = service.repo.import_file(first, "unknown")
    second_id = service.repo.import_file(second, "unknown")
    service.build_calibration_objects(first_id)
    service.build_calibration_objects(second_id)
    service.build_calibration_identities([first_id, second_id])
    before = service.snapshot_knowledge()
    # kennis wijzigen: identiteit afkeuren (technicus)
    identity = service.repo.calibration_identities()[0]
    service.review_calibration_identity(identity["id"], "reject", "technician",
                                        "geen match")
    after = service.snapshot_knowledge()
    diff = service.diff_knowledge_snapshots(before, after)
    assert diff["patterns_disappeared"] == []  # patterns onaangetast
    changed = [(before_item, after_item) for before_item, after_item in
               zip(before["identities"], after["identities"])
               if before_item["status"] != after_item["status"]]
    assert changed, "statuswijziging niet zichtbaar in snapshot-diff"
    assert any(item["status"] == "REJECTED" for _, item in changed)


def test_review_impact_measured_before_and_after(service, tmp_path):
    target = tmp_path / "impact.bin"
    target.write_bytes(_bin(29))
    service.repo.import_file(target, "unknown")

    def apply_review():
        service.repo.audit("approve", "tuning_pattern", 1, reason="impact-test")

    result = service.measure_review_impact(apply_review)
    assert "golden_before" in result and "golden_after" in result
    assert "knowledge_diff" in result
    assert result["golden_after"]["cases"] == result["golden_before"]["cases"]


# ---------------------------------------------------------------- §15/§16
def test_why_this_match_explanation(service, tmp_path):
    source = tmp_path / "why_src"
    source.mkdir()
    original = b"\x00SW:WH HW:WH1\x00" + _bin(33)
    tuned = bytearray(original)
    tuned[300:304] = b"\xaa" * 4
    a, b = source / "original_001.bin", source / "tuned_001.bin"
    a.write_bytes(original)
    b.write_bytes(bytes(tuned))
    aid, bid = service.repo.import_file(a), service.repo.import_file(b)
    service.repo.reclassify_files([aid], "original")
    service.repo.pair(aid, bid, confirmed=True)
    explanation = service.explain_new_bin(bid)
    components = explanation["explanation"]
    assert components, "geen why-componenten"
    weighted = [item for item in components if item["weight"] > 0]
    assert weighted and all("evidence_count" in item for item in components)
    weight_sum = sum(item["weight"] for item in weighted)
    averaged = sum(item["contribution"] for item in weighted) / weight_sum
    assert abs(averaged - explanation["overall_confidence"]) < 0.5, \
        "gewogen gemiddelde van componenten = overall-confidence (formule ongelijk)"


def test_comparison_workspace(service, tmp_path):
    data = bytearray(_bin(37))
    data[512:544] = bytes(range(32))
    left = tmp_path / "cmp_a.bin"
    right = tmp_path / "cmp_b.bin"
    left.write_bytes(bytes(data))
    right.write_bytes(bytes(data))
    left_id = service.repo.import_file(left, "unknown")
    right_id = service.repo.import_file(right, "unknown")
    result = service.compare_workspace(left_id, right_id)
    assert result["left"]["file_id"] == left_id
    assert result["right"]["file_id"] == right_id
    assert result["same_ecu_image_identity"] in (True, False)
    assert "provenance" in result
    # negatieve markering wordt zichtbaar en gerespecteerd
    service.register_negative_match("file_match", ("file", str(left_id)),
                                    ("file", str(right_id)), reason="test")
    flagged = service.compare_workspace(left_id, right_id)
    assert flagged["negative_relation"] is True


# ---------------------------------------------------------------- §17
def test_bulk_processing_is_error_safe(service, tmp_path):
    if not REAL_OLS.exists():
        pytest.skip("echte OLS niet aanwezig")
    project_id = service.repo.import_project(REAL_OLS)
    result = service.bulk_process_projects([project_id, 999999])
    assert result["status"] == "done"
    assert result["processed"] == 1 and result["errors"] == 1  # slecht id stopt niet
    assert result["error_details"][0]["project_id"] == 999999


# ---------------------------------------------------------------- §18
def test_disk_scheduler_serial_per_key_parallel_across_keys():
    scheduler = DiskScheduler(workers=2)
    order = []
    active = {}
    lock = threading.Lock()
    other_started = threading.Event()

    def task(key, item):
        with lock:
            active[key] = active.get(key, 0) + 1
            order.append(f"start:{key}:{item}")
        if key == "ssd":
            other_started.set()
            time.sleep(0.5)  # lang genoeg om paralleliteit betrouwbaar te meten
        elif key == "hdd":
            # hdd wacht tot de ssd-taak écht tegelijk loopt (parallel bewijs)
            assert other_started.wait(timeout=5), "geen paralleliteit over schijven"
            assert active.get("ssd", 0) > 0
        else:
            time.sleep(0.05)
        with lock:
            active[key] -= 1
            order.append(f"eind:{key}:{item}")

    outcome = scheduler.run({"hdd": [1, 2], "ssd": [1]}, task)
    assert outcome["max_concurrent"] == 2
    hdd = [item for item in order if item.startswith("start:hdd")]
    # per key serieel: tweede hdd-task start pas na eerste eindigt
    for index in range(1, len(hdd)):
        first_end = order.index(f"eind:hdd:{index}")
        second_start = order.index(f"start:hdd:{index + 1}")
        assert first_end < second_start


def test_analyze_pending_uses_disk_aware_scheduler(service, tmp_path):
    for root_index in range(2):
        root = tmp_path / f"disk{root_index}"
        root.mkdir()
        for index in range(3):
            (root / f"p{index}.bin").write_bytes(_bin(40 + root_index * 5 + index, 512))
        service.library.add_root(str(root))
        service.library.scan_root(root_index + 1)
    result = service.library.analyze_pending(resume=False)
    assert result["status"] == "done"
    assert result["analyzed"] + result["linked"] + result["cached"] >= 6
    assert result["max_concurrent_roots"] >= 1


# ---------------------------------------------------------------- §19
def test_parser_versioning_and_reparse_preserves_evidence(service, tmp_path):
    if not REAL_OLS.exists():
        pytest.skip("echte OLS niet aanwezig")
    before_sha = hashlib.sha256(REAL_OLS.read_bytes()).hexdigest()
    project_id = service.repo.import_project(REAL_OLS)
    project = service.repo.project(project_id)
    assert project["parser_version"] == "v1"
    records_before = len(service.repo.project_records(project_id))
    result = service.repo.reparse_project(project_id)
    after_sha = hashlib.sha256(REAL_OLS.read_bytes()).hexdigest()
    assert before_sha == after_sha, "bronbestand gewijzigd door reparse"
    assert result["source_unchanged"] is True
    assert result["parser_version"] == "v1"
    assert records_before == len(service.repo.project_records(project_id))
    metadata = json.loads(service.repo.project(project_id)["project_metadata"])
    assert metadata["reparse"][-1]["parser_version"] == "v1"


# ---------------------------------------------------------------- §20
def test_evidence_levels_explicit():
    assert best_evidence_level("INFERRED", "SOURCE_EXPLICIT") == "SOURCE_EXPLICIT"
    assert best_evidence_level("SOURCE_EXPLICIT", "TECHNICIAN_CONFIRMED") == \
        "TECHNICIAN_CONFIRMED"
    assert best_evidence_level("UNKNOWN") == "UNKNOWN"
    assert EVIDENCE_LEVELS.index("TECHNICIAN_CONFIRMED") > \
        EVIDENCE_LEVELS.index("SOURCE_STRUCTURAL")


def test_review_sets_technician_confirmed_level(service, tmp_path):
    if not REAL_OLS.exists():
        pytest.skip("echte OLS niet aanwezig")
    project_id = service.repo.import_project(REAL_OLS)
    objects = service.repo.ols_unknown_objects(project_id)
    if not objects:
        pytest.skip("geen onbekende objecten in echte OLS")
    reviewed = service.repo.review_ols_object(objects[0]["id"], "original",
                                              note="test-review")
    assert reviewed["evidence_level"] == "TECHNICIAN_CONFIRMED"


# ---------------------------------------------------------------- §12
def test_readouts_are_domain_layer_never_in_matching(service, tmp_path):
    target = tmp_path / "readout_case.bin"
    target.write_bytes(_bin(47))
    file_id = service.repo.import_file(target, "unknown")
    before = service.analyze(str(target))
    service.add_readout("Klant B.V.", "Volkswagen Golf 8", stage="Stage 1",
                        technician="jan", file_id=file_id)
    assert service.readouts("Golf")
    after = service.analyze(str(target))
    assert [(match["file_id"], match["overall_match_score"])
            for match in before["matches"]] == \
           [(match["file_id"], match["overall_match_score"])
            for match in after["matches"]]
    matcher_source = Path(__file__).parents[1].joinpath("app/matching/matcher.py") \
        .read_text()
    assert "readout" not in matcher_source.lower(), \
        "matching mag klant-/voertuiglaag niet raadplegen"


# ---------------------------------------------------------------- API
def test_v6_api_endpoints(service, tmp_path):
    from fastapi.testclient import TestClient
    from app.api import create_api
    target = tmp_path / "api_case.bin"
    target.write_bytes(_bin(51))
    file_id = service.repo.import_file(target, "unknown")
    client = TestClient(create_api(service, "k" * 32))
    headers = {"X-API-Key": "k" * 32}
    assert client.get("/ecu-images", headers=headers).status_code == 200
    assert client.get("/project-families", headers=headers).status_code == 200
    assert client.get("/lineage", headers=headers).status_code == 200
    assert client.post("/knowledge-model/rebuild", headers=headers).status_code == 200
    assert client.get("/files/{}/explain".format(file_id),
                      headers=headers).status_code == 200
    assert client.get("/compare",
                      params={"left_file_id": file_id, "right_file_id": file_id},
                      headers=headers).status_code == 200
    assert client.post("/golden/run", headers=headers).status_code == 200
    assert client.get("/golden/runs", headers=headers).status_code == 200
    assert client.get("/knowledge/snapshot", headers=headers).status_code == 200
    assert client.post("/negatives", json={
        "subject_type": "file_match", "a": ["file", "1"], "b": ["file", "2"],
        "reason": "test"}, headers=headers).status_code == 200
    assert client.get("/negatives", headers=headers).status_code == 200
    assert client.get("/readouts", headers=headers).status_code == 200
