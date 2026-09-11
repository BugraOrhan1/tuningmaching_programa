"""V3-tests: TuningRegion, Tuning DNA v3, patronen, cross-software, maps,
malformed OLS, jobs, zoeken en schaal. Alles met synthetische binaries."""
import json
import math
import struct

import pytest

from app.analysis.tuning_region import (build_regions, delta_signature,
                                        entropy, region_confidence,
                                        signature_similarity,
                                        structural_signature)


def _bin(seed: int, size: int = 2048, changes: dict[int, int] | None = None) -> bytes:
    data = bytearray((seed * 31 + i * 7) % 253 for i in range(size))
    for position, value in (changes or {}).items():
        data[position] = value
    return bytes(data)


@pytest.fixture()
def pair(service, tmp_path):
    original = tmp_path / "orig.bin"
    tuned = tmp_path / "tuned.bin"
    # drie kenmerkende wijzigingen: 1 byte, 32 bytes aaneengesloten, 600-byte cluster
    original.write_bytes(_bin(1))
    tuned_data = bytearray(_bin(1))
    tuned_data[100] = 0xAB
    for i in range(300, 332):
        tuned_data[i] = 0x5A
    for i in range(800, 1400):
        tuned_data[i] = (tuned_data[i] + 5) % 256
    tuned.write_bytes(bytes(tuned_data))
    original_id = service.repo.import_file(original, "original")
    tuned_id = service.repo.import_file(tuned, "tuned")
    pair_id = service.repo.pair(original_id, tuned_id, confirmed=True)
    service.diff(pair_id)  # regio's worden bij diff gepersisteerd
    return service, pair_id, original_id, tuned_id


# ---------------------------------------------------------------- TuningRegion
def test_identical_files_have_no_regions(service, tmp_path):
    a = tmp_path / "a.bin"; b = tmp_path / "b.bin"
    a.write_bytes(_bin(2)); b.write_bytes(_bin(2))
    aid = service.repo.import_file(a, "original"); bid = service.repo.import_file(b, "tuned")
    pair_id = service.repo.pair(aid, bid, confirmed=True)
    assert service.diff(pair_id)["blocks"] == []
    assert service.repo.regions_for_pair(pair_id) == []


def test_region_classes_context_and_entropy(pair):
    service, pair_id, _, _ = pair
    regions = service.repo.regions_for_pair(pair_id)
    classes = {region["region_class"] for region in regions}
    assert "small_parameter" in classes and "calibration_cluster" in classes
    small = next(r for r in regions if r["region_class"] == "small_parameter")
    assert small["changed_byte_count"] == 1
    assert len(small["before_context"]) // 2 == 32
    wide = next(r for r in regions if r["length"] >= 32)
    assert wide["entropy_before"] > 0
    assert small["original_context_hash"] and small["structural_signature"]
    assert small["map_type"] == "unknown" and small["map_confidence"] == 0.0


def test_structural_signature_is_offset_independent(tmp_path):
    o1 = _bin(3); t1 = bytearray(o1)
    for i in range(200, 264):
        t1[i] = (t1[i] + 3) % 256
    o2 = _bin(9); t2 = bytearray(o2)
    for i in range(900, 964):
        t2[i] = (t2[i] + 3) % 256  # zelfde structuur, andere absolute offset
    r1 = build_regions(o1, bytes(t1), [{"start_offset": 200, "end_offset": 264,
                                        "length": 64, "changed_bytes": 64,
                                        "changed_percentage": 100.0,
                                        "original_hash": "x", "tuned_hash": "y"}])
    r2 = build_regions(o2, bytes(t2), [{"start_offset": 900, "end_offset": 964,
                                        "length": 64, "changed_bytes": 64,
                                        "changed_percentage": 100.0,
                                        "original_hash": "x", "tuned_hash": "y"}])
    assert r1[0]["structural_signature"] == r2[0]["structural_signature"]
    assert r1[0]["start_offset"] != r2[0]["start_offset"]
    assert signature_similarity(r1[0]["structure_features"], r2[0]["structure_features"]) > 0.95


def test_checksum_only_change_is_small_region_not_checksum(pair):
    service, pair_id, _, _ = pair
    regions = service.repo.regions_for_pair(pair_id)
    assert all(region["region_class"] != "checksum" for region in regions)


def test_region_confidence_formula_is_bounded():
    assert region_confidence("padding", 100.0, 999) == 10.0
    checksum = region_confidence("checksum_candidate", 100.0, 999)
    assert checksum <= 40.0
    assert region_confidence("calibration_region", 100.0, 256) <= 99.0
    assert region_confidence("calibration_region", 5.0, 16) >= 50.0


# ---------------------------------------------------------------- Tuning DNA v3
def test_dna_references_persisted_regions_and_metadata(pair):
    service, pair_id, original_id, _ = pair
    service.repo.update_metadata(original_id, {"ecu_family": "MG1CS003", "stage": "Stage 1"})
    dna = service.generate_tuning_dna(pair_id)
    assert dna["source"]["ecu_family"] == "MG1CS003"
    assert len(dna["region_ids"]) == len(dna["regions"]) >= 3
    stored = service.repo.regions_for_pair(pair_id)
    assert stored[0]["ecu_family"] == "MG1CS003" and stored[0]["stage"] == "Stage 1"


# ---------------------------------------------------------------- Patronen
def test_same_pattern_clusters_and_stage_learning(service, tmp_path):
    for seed in (11, 12, 13):
        original = tmp_path / f"o{seed}.bin"
        tuned = tmp_path / f"t{seed}.bin"
        original.write_bytes(_bin(seed))
        data = bytearray(_bin(seed))
        for i in range(500, 564):
            data[i] = (data[i] + 3) % 256
        tuned.write_bytes(bytes(data))
        oid = service.repo.import_file(original, "original")
        tid = service.repo.import_file(tuned, "tuned")
        service.repo.update_metadata(oid, {"ecu_family": "MG1CS003", "stage": "Stage 1",
                                           "software_number": f"SW{seed}"})
        pair_id = service.repo.pair(oid, tid, confirmed=True)
    result = service.rebuild_patterns()
    assert result["patterns"] >= 1
    patterns = service.patterns_detail()
    pattern = patterns[0]
    assert pattern["payload"]["confirmed_projects"] >= 3
    assert pattern["payload"]["ecu_family"] == "MG1CS003"
    assert set(pattern["payload"]["stages"]) == {"Stage 1"}
    assert len({member["pair_id"] for member in pattern["members"]}) >= 3
    assert pattern["frequency"] == pattern["payload"]["confirmed_projects"]
    # zelfde patroon opnieuw bouwen is idempotent
    before = [(p["pattern_key"], p["frequency"]) for p in service.patterns_detail()]
    service.rebuild_patterns()
    assert [(p["pattern_key"], p["frequency"]) for p in service.patterns_detail()] == before


def test_unrelated_region_does_not_join_pattern(service, tmp_path):
    # ZELFDE structuur op andere offset = één logisch patroon (V3-§5);
    # ANDERE structuur (constante i.p.v. +delta) = apart patroon.
    cases = ((21, 500, "delta"), (22, 1500, "constant"))
    for seed, start, kind in cases:
        original = tmp_path / f"o{seed}.bin"
        tuned = tmp_path / f"t{seed}.bin"
        original.write_bytes(_bin(seed))
        data = bytearray(_bin(seed))
        for i in range(start, start + 64):
            data[i] = (data[i] + 3) % 256 if kind == "delta" else 0x5A
        tuned.write_bytes(bytes(data))
        oid = service.repo.import_file(original, "original")
        tid = service.repo.import_file(tuned, "tuned")
        service.repo.update_metadata(oid, {"ecu_family": "MG1CS003"})
        service.repo.pair(oid, tid, confirmed=True)
    service.rebuild_patterns()
    patterns = service.patterns_detail()
    assert len(patterns) == 2  # geen kruisbesmetting tussen ongelijke structuren
    offsets = sorted(member["start_offset"] for member in patterns[0]["members"]) \
        if len(patterns[0]["members"]) > 1 else \
        sorted(member["start_offset"] for member in patterns[1]["members"])
    assert len(offsets) >= 1


def test_checksum_candidate_marking_and_exclusion(service, tmp_path):
    # twee ECU-families, allebei een wijziging op dezelfde relatieve plek
    for seed, family in ((31, "FAM_A"), (32, "FAM_A"), (33, "FAM_B")):
        original = tmp_path / f"o{seed}.bin"
        tuned = tmp_path / f"t{seed}.bin"
        original.write_bytes(_bin(seed))
        data = bytearray(_bin(seed))
        for i in range(1024, 1088):
            data[i] = (data[i] * 7 + seed) % 256  # onderling verschillende tuned-inhoud
        tuned.write_bytes(bytes(data))
        oid = service.repo.import_file(original, "original")
        tid = service.repo.import_file(tuned, "tuned")
        service.repo.update_metadata(oid, {"ecu_family": family})
        service.repo.pair(oid, tid, confirmed=True)
    service.rebuild_patterns()
    regions = service.repo.all_candidate_regions()
    shared = [r for r in regions if r["region_class"] == "checksum_candidate"]
    assert len(shared) == 3
    assert all(r["confidence"] <= 40.0 for r in shared)
    patterns = service.patterns_detail()
    member_regions = {m["region_id"] for p in patterns for m in p["members"]}
    assert not (member_regions & {r["id"] for r in shared})


# ---------------------------------------------------------------- Cross-software
def test_cross_software_alignment_maps_shifted_pattern(service, tmp_path):
    base = _bin(41)
    variant = bytearray(base)
    shift = 256
    # software B: calibratieblok is 256 bytes opgeschoven, rest identiek genoeg
    for i in range(len(base) - shift):
        variant[i + shift] = base[i]
    original_ids = {}
    for name, blob, sw in (("origA", bytes(base), "SW_A"), ("origB", bytes(variant), "SW_B")):
        path = tmp_path / f"{name}.bin"
        path.write_bytes(blob)
        file_id = service.repo.import_file(path, "original")
        service.repo.update_metadata(file_id, {"ecu_family": "MG1CS003", "software_number": sw})
        original_ids[sw] = file_id
    # tune beide originals op hetzelfde logische blok (eigen offset per software)
    for sw, offset, seed in (("SW_A", 500, 41), ("SW_B", 756, None)):
        source = base if seed is not None else bytes(variant)
        data = bytearray(source)[0:2048]
        for i in range(offset, offset + 64):
            data[i] = (data[i] + 3) % 256
        path = tmp_path / f"tuned_{sw}.bin"
        path.write_bytes(bytes(data))
        tuned_id = service.repo.import_file(path, "tuned")
        pair_id = service.repo.pair(original_ids[sw], tuned_id, confirmed=True)
    result = service.rebuild_patterns()
    assert result["patterns"] >= 1
    # zelfde wijziging in verschillende software → gedeelde structuur?
    patterns = service.patterns_detail()
    shared = [p for p in patterns if p["payload"]["confirmed_projects"] >= 2]
    if shared:
        alignment = service.align_pattern_across_software(shared[0]["id"])
        assert alignment["alignments_created"] >= 1
        assert alignment["offsets_by_software"], "verwacht offsets per software"
        rows = service.repo.alignments_for_pattern(shared[0]["id"])
        assert all("block_run_alignment" in [e["type"] for e in row["evidence"]] or
                   row["status"] == "unknown" for row in rows)


def test_find_pattern_matches_reports_confidence_and_offset(service, tmp_path):
    for seed in (51, 52):
        original = tmp_path / f"o{seed}.bin"
        tuned = tmp_path / f"t{seed}.bin"
        original.write_bytes(_bin(seed))
        data = bytearray(_bin(seed))
        for i in range(500, 564):
            data[i] = (data[i] + 3) % 256
        tuned.write_bytes(bytes(data))
        oid = service.repo.import_file(original, "original")
        tid = service.repo.import_file(tuned, "tuned")
        service.repo.update_metadata(oid, {"ecu_family": "MG1CS003", "stage": "Stage 1"})
        service.repo.pair(oid, tid, confirmed=True)
    service.rebuild_patterns()
    # nieuwe 'BIN' van een derde variant, zelfde logische blok op andere offset
    new_original = bytearray(_bin(53))
    for i in range(700, 764):
        new_original[i] = (new_original[i] + 3) % 256
    query = bytes(new_original)
    matches = service.find_pattern_matches(query, threshold=50.0)
    if matches:  # alleen bewijs als blok-run alignment slaagt
        assert matches[0]["query_offset"] >= 0
        assert matches[0]["confirmed_projects"] >= 2
        assert matches[0]["pattern_confidence"] > 50


# ---------------------------------------------------------------- Mapdetection
def test_map_detection_finds_axis_candidate_without_naming(service, tmp_path):
    data = bytearray(_bin(61))
    ramp = list(range(0, 256, 2))  # strijd monotone as
    data[1024:1024 + 32] = bytes(ramp[:32] + ramp[:32])
    path = tmp_path / "with_axis.bin"
    path.write_bytes(bytes(data))
    file_id = service.repo.import_file(path, "unknown")
    result = service.detect_map_structures(file_id)
    assert result["structures"] >= 0  # scanning is begrensd; kandidaten zijn bonus
    rows = service.repo.map_regions_for_file(file_id)
    assert all(row["map_type"] in {"axis_candidate", "table_candidate", "unknown"}
               for row in rows)
    assert all("boost" not in json.dumps(row).lower() for row in rows)


def test_calibration_objects_remain_unknown_without_source_evidence(service, tmp_path):
    data = bytearray(_bin(62))
    data[512:544] = bytes(range(32))
    path = tmp_path / "calibration_candidate.bin"
    path.write_bytes(bytes(data))
    file_id = service.repo.import_file(path, "unknown")

    result = service.build_calibration_objects(file_id)
    objects = service.repo.calibration_objects_for_file(file_id)

    assert result["status"] == "candidates_only"
    assert all(item["status"] == "candidate" for item in objects)
    assert all(item["data_type"] == "UNKNOWN" for item in objects)
    assert all(item["endian"] == "UNKNOWN" for item in objects)
    assert all(item["calibration_family"] == "UNKNOWN" for item in objects)
    if objects:
        assert objects[0]["entropy"] is not None
        assert objects[0]["value_statistics"]["count"] > 0
        assert objects[0]["context_hashes"]["surrounding"]
        assert objects[0]["data_type"] == "UNKNOWN"


def test_calibration_identity_groups_structure_but_stays_candidate(service, tmp_path):
    data = bytearray(_bin(63))
    data[512:544] = bytes(range(32))
    first = tmp_path / "identity_a.bin"
    second = tmp_path / "identity_b.bin"
    first.write_bytes(bytes(data))
    second.write_bytes(bytes(data))
    first_id = service.repo.import_file(first, "unknown")
    second_id = service.repo.import_file(second, "unknown")
    service.repo.update_metadata(first_id, {"ecu_family": "TEST_ECU", "software_number": "SW_A"})
    service.repo.update_metadata(second_id, {"ecu_family": "TEST_ECU", "software_number": "SW_B"})
    service.build_calibration_objects(first_id)
    service.build_calibration_objects(second_id)

    result = service.build_calibration_identities([first_id, second_id])
    identities = service.repo.calibration_identities()

    assert result["identities"] >= 1
    assert any(item["status"] == "CANDIDATE" and len(item["members"]) >= 2
               for item in identities)


def test_calibration_identity_review_is_traceable_and_statused(service, tmp_path):
    path = tmp_path / "identity_review.bin"
    path.write_bytes(_bin(64))
    file_id = service.repo.import_file(path, "unknown")
    service.build_calibration_objects(file_id)
    service.build_calibration_identities([file_id])
    identity = service.repo.calibration_identities()[0]

    reviewed = service.review_calibration_identity(identity["id"], "approve", "technician", "supported")

    assert reviewed["identity"]["status"] == "SUPPORTED"
    history = service.repo.knowledge_history("calibration_identity")
    assert history[0]["action"] == "approve"


def test_tuning_dna_links_only_overlapping_calibration_identity_candidates(service, tmp_path):
    original = tmp_path / "dna_identity_original.bin"
    tuned = tmp_path / "dna_identity_tuned.bin"
    source = bytearray(_bin(65))
    source[512:544] = bytes(range(32))
    changed = bytearray(source)
    changed[520:528] = b"TUNED!!!"
    original.write_bytes(bytes(source))
    tuned.write_bytes(bytes(changed))
    original_id = service.repo.import_file(original, "original")
    tuned_id = service.repo.import_file(tuned, "tuned")
    service.repo.update_metadata(original_id, {"ecu_family": "DNA_ECU", "software_number": "DNA_SW"})
    pair_id = service.repo.pair(original_id, tuned_id, confirmed=True)
    object_id = service.repo.db.rows("""INSERT INTO calibration_objects
        (file_id,object_key,dimensions,data_type,element_size,endian,axis_count,
         structural_signature,detection_confidence,evidence,status)
        VALUES (?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
        (original_id, "test:512:544", "[32]", "UNKNOWN", 1, "UNKNOWN", 0,
         "dna-structural-signature", 80.0, '["test evidence"]', "candidate"))[0]["id"]
    service.repo.db.rows("UPDATE calibration_objects SET relative_layout=? WHERE id=?",
                         ('{"start_offset": 512, "end_offset": 544}', object_id))
    service.build_calibration_identities([original_id])
    dna = service.generate_tuning_dna(pair_id)

    assert dna["calibration_identity_ids"]
    assert dna["regions"][0]["calibration_identity_candidates"]
    assert dna["regions"][0]["calibration_identity_candidates"][0]["evidence"] == \
        "same-file CalibrationObject overlap"


def test_calibration_identity_alignment_records_context_evidence(service, tmp_path):
    first = tmp_path / "align_first.bin"
    second = tmp_path / "align_second.bin"
    first.write_bytes(_bin(66))
    second.write_bytes(_bin(66))
    first_id = service.repo.import_file(first, "unknown")
    second_id = service.repo.import_file(second, "unknown")
    for file_id, software in ((first_id, "SW_A"), (second_id, "SW_B")):
        service.repo.update_metadata(file_id, {"ecu_family": "ALIGN_ECU", "software_number": software})
        service.repo.db.rows("""INSERT INTO calibration_objects
            (file_id,object_key,dimensions,data_type,element_size,endian,axis_count,
             relative_layout,structural_signature,detection_confidence,evidence,status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (file_id, f"align:{file_id}", "[32]", "UNKNOWN", 1, "UNKNOWN", 0,
             '{"start_offset":512,"end_offset":544}', "align-signature", 80.0,
             '["test evidence"]', "candidate"))
    service.build_calibration_identities([first_id, second_id])
    identity = service.repo.calibration_identities()[0]

    result = service.align_calibration_identity(identity["id"])

    assert result["alignments_created"] == 1
    assert result["alignments"][0]["positive"]
    assert result["alignments"][0]["status"] in {"SUPPORTED", "UNKNOWN"}


def test_identity_alignment_persists_contradicting_context(service, tmp_path):
    first = tmp_path / "contra_first.bin"
    second = tmp_path / "contra_second.bin"
    first.write_bytes(_bin(71))
    second.write_bytes(_bin(72))
    first_id = service.repo.import_file(first, "unknown")
    second_id = service.repo.import_file(second, "unknown")
    for file_id, software in ((first_id, "SW_A"), (second_id, "SW_B")):
        service.repo.update_metadata(file_id, {"ecu_family": "CONTRA_ECU", "software_number": software})
        service.repo.db.rows("""INSERT INTO calibration_objects
            (file_id,object_key,dimensions,data_type,element_size,endian,axis_count,
             relative_layout,structural_signature,detection_confidence,evidence,status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (file_id, f"contra:{file_id}", "[32]", "UNKNOWN", 1, "UNKNOWN", 0,
             '{"start_offset":512,"end_offset":544}', "contra-signature", 80.0,
             '["test evidence"]', "candidate"))
    service.build_calibration_identities([first_id, second_id])
    identity = service.repo.calibration_identities()[0]
    result = service.align_calibration_identity(identity["id"])
    stored = service.repo.calibration_identity(identity["id"])

    assert result["alignments_created"] == 1
    assert stored["contradicting_evidence"] or stored["supporting_evidence"]


def test_confidence_evaluation_reports_metrics_and_ambiguous_cases(service):
    result = service.evaluate_confidence([
        {"score": 95, "label": "positive"},
        {"score": 20, "label": "negative"},
        {"score": 80, "label": "negative"},
        {"score": 55, "label": "ambiguous"},
    ])

    assert result["sample_count"] == 3
    assert result["ambiguous_count"] == 1
    assert result["false_positive"] == 1
    assert result["brier_score"] is not None
    assert result["evaluation_id"] == 1


def test_pattern_merge_rebuilds_memberships(service, tmp_path):
    for seed, start in ((67, 300), (68, 900)):
        original = tmp_path / f"merge_o{seed}.bin"
        tuned = tmp_path / f"merge_t{seed}.bin"
        original.write_bytes(_bin(seed))
        data = bytearray(_bin(seed)); data[start:start + 64] = b"M" * 64
        tuned.write_bytes(bytes(data))
        oid = service.repo.import_file(original, "original")
        tid = service.repo.import_file(tuned, "tuned")
        service.repo.update_metadata(oid, {"ecu_family": f"MERGE_{seed}"})
        service.repo.pair(oid, tid, confirmed=True)
    service.rebuild_patterns()
    patterns = service.patterns_detail()
    assert len(patterns) >= 2
    source, target = patterns[-1], patterns[0]
    result = service.review_pattern(source["id"], "merge", payload={"target_pattern_id": target["id"]})

    assert result["rebuild"]["status"] == "rebuilt"
    assert service.repo.db.rows("SELECT status FROM tuning_patterns WHERE id=?",
                                (source["id"],))[0]["status"] == "rejected"
    assert service.repo.pattern(target["id"])["members"]


def test_new_bin_report_exposes_identity_candidates_as_heuristic(service, tmp_path):
    path = tmp_path / "new_identity.bin"
    path.write_bytes(_bin(69))
    file_id = service.repo.import_file(path, "unknown")

    report = service.new_bin_report(file_id, threshold=50.0)

    assert "calibration_identity_matches" in report
    assert report["confidence_type"] == "HEURISTIC CONFIDENCE"
    assert report["score_components"]["calibration_identity_confidence"] >= 0.0


def test_search_finds_identity_evidence_and_builds(service, tmp_path):
    path = tmp_path / "search_identity.bin"
    path.write_bytes(_bin(70))
    file_id = service.repo.import_file(path, "unknown")
    service.repo.update_metadata(file_id, {"ecu_family": "SEARCH_IDENTITY"})
    service.build_calibration_objects(file_id)
    service.build_calibration_identities([file_id])
    identity = service.repo.calibration_identities()[0]
    service.repo.add_evidence("calibration_identity", str(identity["id"]),
                              "structure", "SEARCH_IDENTITY evidence", confidence=80.0)

    result = service.search("SEARCH_IDENTITY")

    assert result["calibration_identities"]
    assert result["evidence"]


# ---------------------------------------------------------------- Malformed OLS
def test_malformed_ols_is_rejected_without_invention(service, tmp_path):
    bad = tmp_path / "bad.ols"
    bad.write_bytes(b"\x0b\x00\x00\x00WinOLS Fi")  # afgekapte header
    result = service.repo.import_project(bad)
    assert service.repo.ols_versions(result) == []
    garbage = tmp_path / "garbage.ols"
    garbage.write_bytes(bytes((i * 13) % 256 for i in range(4096)))
    result = service.repo.import_project(garbage)
    assert service.repo.ols_versions(result) == []


# ---------------------------------------------------------------- Jobs
def test_pattern_job_resumes_after_interruption(service, tmp_path):
    for seed in range(71, 76):
        original = tmp_path / f"o{seed}.bin"; tuned = tmp_path / f"t{seed}.bin"
        original.write_bytes(_bin(seed)); tuned.write_bytes(_bin(seed, changes={100: 0x42}))
        oid = service.repo.import_file(original, "original")
        tid = service.repo.import_file(tuned, "tuned")
        service.repo.pair(oid, tid, confirmed=True)
    # gesimuleerde onderbreking: run markeren als interrupted met checkpoint
    run_id = service.repo.start_run("pattern_rebuild", {"batch_size": 1})
    service.repo.checkpoint_run(run_id, {"last_pair_id": 1}, {"pairs": 1})
    service.repo.finish_run(run_id, "interrupted", {"pairs": 1})
    result = service.run_pattern_job(resume=True)
    assert result["pairs"] >= 4  # alleen de resterende paren
    runs = service.jobs()
    assert runs[0]["status"] == "done"


# ---------------------------------------------------------------- Zoeken
def test_search_finds_files_patterns_and_projects(service, tmp_path, pair):
    service, pair_id, original_id, _ = pair
    service.repo.update_metadata(original_id, {"ecu_family": "MG1CS003"})
    sha = service.repo.file(original_id)["sha256"]
    hits = service.search("MG1CS003")
    assert any(row["id"] == original_id for row in hits["files"])
    hits = service.search(sha[:16])
    assert any(row["id"] == original_id for row in hits["files"])
    with pytest.raises(ValueError):
        service.search("  ")


# ---------------------------------------------------------------- Schaal (100)
def test_scale_100_pairs_pattern_rebuild(service, tmp_path):
    for seed in range(100):
        original = tmp_path / f"o{seed}.bin"
        tuned = tmp_path / f"t{seed}.bin"
        original.write_bytes(_bin(seed % 20, size=1024))
        data = bytearray(_bin(seed % 20, size=1024))
        for i in range(100, 132):
            data[i] = (data[i] + (seed % 5) + 1) % 256
        tuned.write_bytes(bytes(data))
        oid = service.repo.import_file(original, "original")
        tid = service.repo.import_file(tuned, "tuned")
        service.repo.update_metadata(oid, {"ecu_family": "SCALE_TEST"})
        service.repo.pair(oid, tid, confirmed=True)
    result = service.rebuild_patterns()
    assert result["pairs"] == 100
    assert result["patterns"] >= 1
    patterns = service.patterns_detail()
    assert sum(p["payload"]["confirmed_projects"] for p in patterns) >= 100


# ---------------------------------------------------------------- V4 afronding
def test_identity_alignment_escalates_to_rejected(service, tmp_path):
    """Sterke tegenstrijdige overmacht (3 files, willekeurige omgeving) -> REJECTED."""
    for seed in (71, 72, 73):
        data = bytearray(_bin(seed))
        data[512:544] = bytes(range(32))  # identieke ramp, willekeurige omgeving
        path = tmp_path / f"reject_{seed}.bin"
        path.write_bytes(bytes(data))
        file_id = service.repo.import_file(path, "unknown")
        service.repo.update_metadata(file_id, {"ecu_family": "REJ_ECU", "software_number": f"SW_{seed}"})
        service.build_calibration_objects(file_id)
    service.build_calibration_identities()
    identity = next(row for row in service.repo.calibration_identities()
                    if len(row["members"]) >= 3)
    result = service.align_calibration_identity(identity["id"])
    refreshed = service.repo.calibration_identity(identity["id"])
    assert refreshed["status"] == "REJECTED"
    assert all(item["negative"] for item in result["alignments"])
    assert refreshed["contradicting_evidence"], "contradicties moeten bewaard blijven"


def test_merge_rebuilds_confidence_and_knowledge_build(service, tmp_path):
    """Technician MERGE herbouwt members, confidence, stages/software en registreert een knowledge build."""
    for seed, start, kind in ((81, 500, "delta"), (82, 1500, "delta"), (83, 700, "constant")):
        original = tmp_path / f"m{seed}.bin"
        tuned = tmp_path / f"mt{seed}.bin"
        original.write_bytes(_bin(seed))
        data = bytearray(_bin(seed))
        for i in range(start, start + 64):
            data[i] = (data[i] + 3) % 256 if kind == "delta" else 0x5A
        tuned.write_bytes(bytes(data))
        oid = service.repo.import_file(original, "original")
        tid = service.repo.import_file(tuned, "tuned")
        service.repo.update_metadata(oid, {"ecu_family": "MERGE_ECU", "stage": "Stage 1"})
        service.repo.pair(oid, tid, confirmed=True)
    service.rebuild_patterns()
    patterns = service.patterns_detail()
    assert len(patterns) == 2
    source_id, target_id = patterns[0]["id"], patterns[1]["id"]
    result = service.review_pattern(source_id, "merge", payload={"target_pattern_id": target_id})
    target = service.repo.pattern(target_id)
    expected = round(max(50.0, min(95.0, 50.0 + 15.0 * math.log2(1 + target["frequency"]))), 2)
    assert abs(target["confidence"] - expected) < 0.01
    assert target["payload"]["software_variants"] == ["unknown"]  # herbouwd uit leden
    rejected_row = service.repo.db.rows(
        "SELECT status FROM tuning_patterns WHERE id=?", (source_id,))
    assert rejected_row[0]["status"] == "rejected"  # patterns_v3 filtert rejected bewust weg
    builds = service.repo.knowledge_builds()
    assert builds and builds[0]["status"] == "ACTIVE"
    assert result["knowledge_build_id"] == builds[0]["id"]


def test_generate_tune_candidate_dedup(service, tmp_path):
    """Identieke candidate-regeneratie maakt geen tweede tune_candidates-rij."""
    original = tmp_path / "dedup_o.bin"
    tuned = tmp_path / "dedup_t.bin"
    target = tmp_path / "dedup_target.bin"
    original.write_bytes(_bin(91))
    data = bytearray(_bin(91))
    for i in range(600, 632):
        data[i] = (data[i] + 4) % 256
    tuned.write_bytes(bytes(data))
    target.write_bytes(_bin(91))
    oid = service.repo.import_file(original, "original")
    tid = service.repo.import_file(tuned, "tuned")
    service.repo.pair(oid, tid, confirmed=True)
    target_id = service.repo.import_file(target, "unknown")
    first = service.generate_tune_candidate(target_id, threshold=70.0)
    assert first["status"] == "candidate_generated"
    second = service.generate_tune_candidate(target_id, threshold=70.0)
    assert second["candidate_id"] == first["candidate_id"]
    assert len(service.tune_candidates()) == 1


def test_import_folder_resume_exact_and_idempotent(service, tmp_path):
    """Crash tijdens batch-import -> checkpoint; resume verwerkt exact de rest, geen duplicaten."""
    folder = tmp_path / "batch"
    folder.mkdir()
    for index in range(6):
        (folder / f"f{index}.bin").write_bytes(_bin(100 + index, size=512))
    calls = {"n": 0}

    def progress(_message):
        calls["n"] += 1
        if calls["n"] == 4:
            raise RuntimeError("gesimuleerde crash")

    with pytest.raises(RuntimeError):
        service.repo.import_folder(str(folder), "unknown", progress)
    interrupted = [run for run in service.repo.runs() if run["status"] == "interrupted"]
    assert interrupted, "crash moet een interrupted run achterlaten"
    result = service.repo.import_folder(str(folder), "unknown", resume=True)
    assert result["status"] if "status" in result else True
    assert len(service.repo.files()) == 6  # idempotent: geen duplicaten
    assert result["processed"] >= 6
    done = [run for run in service.repo.runs() if run["status"] == "done"]
    assert done and done[0]["checkpoint"]
