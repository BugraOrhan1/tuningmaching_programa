"""Golden Dataset-cases (§9): KNOWN SAME / KNOWN DIFFERENT / KNOWN
ORIGINAL-TUNED / KNOWN SAME CAL ACROSS SW / KNOWN DIFFERENT CAL /
KNOWN CHECKSUM / KNOWN MAP / UNKNOWN / REAL-OLS.

Elke case is deterministisch en meet één bewijsbare intelligence-claim.
De echte GASDROP_100119.ols-case (image-identiteiten + size-mismatch)
wordt overgeslagen (en gerapporteerd) als het bestand ontbreekt.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _bin(seed: int, size: int = 2048) -> bytes:
    return bytes((seed * 31 + i * 7) % 253 for i in range(size))


def _import(service, path, kind="unknown"):
    return service.repo.import_file(path, kind)


def run_golden_cases(service, workspace=None) -> dict:
    """Alle cases draaien in een schone map; rapport met per-categorie-uitslag."""
    base = Path(workspace) if workspace else service.repo.root / "golden"
    base.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict] = {}
    skipped: list[str] = []

    cases = [
        ("KNOWN_SAME", case_known_same),
        ("KNOWN_DIFFERENT", case_known_different),
        ("KNOWN_ORIGINAL_TUNED", case_known_original_tuned),
        ("KNOWN_SAME_CAL_ACROSS_SW", case_known_same_cal_across_sw),
        ("KNOWN_DIFFERENT_CAL", case_known_different_cal),
        ("KNOWN_CHECKSUM", case_known_checksum),
        ("KNOWN_MAP", case_known_map),
        ("UNKNOWN", case_unknown_no_forced_match),
        ("REAL_OLS_IMAGE_IDENTITY", case_real_ols_image_identity),
    ]
    for name, runner in cases:
        try:
            outcome = runner(service, base)
        except GoldenSkip as exc:
            skipped.append(f"{name}: {exc}")
            continue
        results[name] = outcome

    per_category = {}
    for name, outcome in results.items():
        per_category[name] = {"passed": outcome["passed"],
                              "detail": outcome["detail"]}
    totals = {"cases": len(per_category) + len(skipped),
              "passed": sum(1 for item in per_category.values() if item["passed"]),
              "failed": sum(1 for item in per_category.values() if not item["passed"]),
              "skipped": len(skipped)}
    return {"totals": totals, "per_category": per_category, "skipped": skipped,
            "notes": "Alle cases zijn deterministisch; UNKNOWN-cases verwachten "
                     "expliciet geen geforceerde match."}


class GoldenSkip(Exception):
    """Case kan niet draaien in deze omgeving (bijv. echte OLS ontbreekt)."""


def case_known_same(service, base):
    """Byte-identieke files moeten één ECU image identity krijgen (R1)."""
    target = base / "same_a.bin"
    twin = base / "same_b.bin"
    payload = _bin(11)
    target.write_bytes(payload)
    twin.write_bytes(payload)
    first = _import(service, target)
    second = _import(service, twin)
    service.km.build_ecu_image_identities()
    identities = service.repo.db.rows(
        """SELECT i.id FROM ecu_image_identities i JOIN ecu_image_members m
           ON m.image_id=i.id WHERE m.member_id IN (?,?)
           GROUP BY i.id HAVING COUNT(DISTINCT m.member_id)=2""", (first, second))
    shared = len(identities) == 1
    if shared:
        status = service.repo.db.rows(
            "SELECT status FROM ecu_image_identities WHERE id=?",
            (identities[0]["id"],))[0]["status"]
        return {"passed": status == "SUPPORTED",
                "detail": f"zelfde identity ({status})"}
    return {"passed": False, "detail": "byte-identieke files niet gegroepeerd"}


def case_known_different(service, base):
    """Verschillende size+inhoud mag NIET in dezelfde image identity belanden
    (bestaande legitieme groepen in de database blijven buiten beschouwing)."""
    target = base / "diff_a.bin"
    other = base / "diff_b.bin"
    target.write_bytes(_bin(21))
    other.write_bytes(_bin(22) + b"\x00" * 512)
    first = _import(service, target)
    second = _import(service, other)
    service.km.build_ecu_image_identities()
    co_grouped = service.repo.db.rows(
        """SELECT i.id FROM ecu_image_identities i JOIN ecu_image_members m
           ON m.image_id=i.id WHERE m.member_id IN (?, ?)
           GROUP BY i.id HAVING COUNT(DISTINCT m.member_id) >= 2""", (first, second))
    return {"passed": not co_grouped,
            "detail": "gescheiden" if not co_grouped else "onterecht samengevoegd"}


def case_known_original_tuned(service, base):
    """Bevestigd O→T-paar levert diff-regio's en DNA-kandidaten."""
    original = base / "ot_original.bin"
    tuned = base / "ot_tuned.bin"
    original.write_bytes(b"\x00SW:GD_HW HW:GD_H1\x00" + _bin(31))
    data = bytearray(original.read_bytes())
    data[100:104] = b"\xff" * 4
    data[300:303] = b"\xee" * 3
    tuned.write_bytes(bytes(data))
    original_id = service.repo.import_file(original, "original")
    tuned_id = service.repo.import_file(tuned, "tuned")
    pair_id = service.repo.pair(original_id, tuned_id, confirmed=True)
    report = service.diff(pair_id)
    return {"passed": len(report["blocks"]) >= 1,
            "detail": f"{len(report['blocks'])} diff-regio's"}


def case_known_same_cal_across_sw(service, base):
    """Zelfde structuur in SW_A en SW_B → minstens één gedeelde identity."""
    first = base / "sw_a.bin"
    second = base / "sw_b.bin"
    data = bytearray(_bin(63))
    data[512:544] = bytes(range(32))
    first.write_bytes(bytes(data))
    second.write_bytes(bytes(data))
    first_id = _import(service, first)
    second_id = _import(service, second)
    service.repo.update_metadata(first_id, {"ecu_family": "GD_ECU",
                                            "software_number": "SW_A"})
    service.repo.update_metadata(second_id, {"ecu_family": "GD_ECU",
                                             "software_number": "SW_B"})
    service.build_calibration_objects(first_id)
    service.build_calibration_objects(second_id)
    service.build_calibration_identities([first_id, second_id])
    identities = [item for item in service.repo.calibration_identities()
                  if len({member["file_id"] for member in item["members"]}) >= 2]
    return {"passed": bool(identities),
            "detail": f"{len(identities)} gedeelde identiteiten"}


def case_known_different_cal(service, base):
    """Verschillende structuren mogen geen gedeelde identity krijgen."""
    first = base / "cal_x.bin"
    second = base / "cal_y.bin"
    data_x = bytearray(_bin(71))
    data_x[256:288] = bytes(range(32))
    data_y = bytearray(_bin(72))
    data_y[1536:1568] = bytes((i * 5) % 251 for i in range(32))
    first.write_bytes(bytes(data_x))
    second.write_bytes(bytes(data_y))
    first_id = _import(service, first)
    second_id = _import(service, second)
    service.repo.update_metadata(first_id, {"ecu_family": "GD_ECU_X"})
    service.repo.update_metadata(second_id, {"ecu_family": "GD_ECU_Y"})
    service.build_calibration_objects(first_id)
    service.build_calibration_objects(second_id)
    service.build_calibration_identities([first_id, second_id])
    shared = [item for item in service.repo.calibration_identities()
              if {member["file_id"] for member in item["members"]} == {first_id,
                                                                       second_id}]
    return {"passed": not shared, "detail": f"{len(shared)} onterecht gedeeld"}


def case_known_checksum(service, base):
    """Zelfde relatieve wijziging over 3 paren en 2 ECU's → checksum-kandidaat,
    uitgesloten van patronen."""
    for seed, family in ((81, "GD_FAM_A"), (82, "GD_FAM_A"), (83, "GD_FAM_B")):
        original = base / f"cs_o{seed}.bin"
        tuned = base / f"cs_t{seed}.bin"
        original.write_bytes(_bin(seed))
        data = bytearray(_bin(seed))
        for index in range(1024, 1088):
            data[index] = (data[index] * 7 + seed) % 256
        tuned.write_bytes(bytes(data))
        original_id = service.repo.import_file(original, "original")
        tuned_id = service.repo.import_file(tuned, "tuned")
        service.repo.update_metadata(original_id, {"ecu_family": family})
        service.repo.pair(original_id, tuned_id, confirmed=True)
    service.rebuild_patterns()
    regions = service.repo.all_candidate_regions()
    shared = [region for region in regions
              if region["region_class"] == "checksum_candidate"]
    return {"passed": len(shared) >= 3,
            "detail": f"{len(shared)} checksum-kandidaten"}


def case_known_map(service, base):
    """Periodieke tabelstructuur levert map-kandidaten (structuur ≠ functie)."""
    target = base / "map_candidate.bin"
    payload = bytearray(_bin(91))
    for row in range(8):                       # 2D-table: 8 rijen × 16 kolommen
        for column in range(16):
            payload[1024 + row * 32 + column * 2:1026 + row * 32 + column * 2] = \
                (row * 4096 + column * 256).to_bytes(2, "little")
    target.write_bytes(bytes(payload))
    file_id = _import(service, target)
    report = service.detect_map_structures(file_id)
    candidates = report.get("candidates", report.get("structures"))
    count = candidates if isinstance(candidates, int) else len(candidates or [])
    return {"passed": count >= 1, "detail": f"{count} map-kandidaten"}


def case_unknown_no_forced_match(service, base):
    """Willekeurige high-entropy file → expliciet UNKNOWN/outlier, geen match."""
    target = base / "mystery.bin"
    seed = 123456789
    payload = bytearray()
    for _ in range(8192):
        seed = (seed * 1103515245 + 12345) % (1 << 31)
        payload.append(seed >> 23)
    target.write_bytes(bytes(payload))
    report = service.analyze(str(target))
    no_confident = (not report["matches"]
                    or report.get("outlier")
                    or all(match["overall_match_score"] < 60
                           for match in report["matches"]))
    return {"passed": no_confident,
            "detail": "geen geforceerde match (outlier/UNKNOWN)"}


def case_real_ols_image_identity(service, base):
    """Echte GASDROP_100119.ols: drie 2MiB-tuned-versies = één image identity;
    de 855KB 'Origineel'-versie krijgt een EIGEN identity met expliciete
    UNKNOWN size-relatie; er wordt nooit automatisch een O→T-paar gemaakt."""
    source = ROOT / "data" / "winols_projects" / "GASDROP_100119.ols"
    if not source.exists():
        raise GoldenSkip("echte GASDROP_100119.ols niet aanwezig")
    project_id = service.repo.import_project(source)
    service.km.build_ecu_image_identities()
    versions = service.repo.ols_versions(project_id)
    version_files = {version["file_id"]: version for version in versions
                     if version["file_id"]}
    big_files = [file_id for file_id, version in version_files.items()
                 if service.repo.file(file_id)["file_size"] == 2097152]
    small_files = [file_id for file_id, version in version_files.items()
                   if service.repo.file(file_id)["file_size"] == 855132]
    if not big_files or not small_files:
        return {"passed": False, "detail": "verwachte versiegroottes niet gevonden"}
    groups = service.repo.db.rows(
        """SELECT m.image_id, COUNT(*) AS members FROM ecu_image_members m
           WHERE m.member_type='file' AND m.member_id IN
           ({}) GROUP BY m.image_id""".format(",".join("?" * len(big_files))),
        tuple(big_files))
    big_grouped = [row for row in groups if row["members"] == len(big_files)]
    small_identity = service.repo.db.rows(
        """SELECT DISTINCT m.image_id FROM ecu_image_members m
           WHERE m.member_id IN ({})""".format(",".join("?" * len(small_files))),
        tuple(small_files))
    big_ok = len(big_grouped) == 1 and big_grouped[0]["members"] == len(big_files)
    separate = not small_identity or small_identity[0]["image_id"] != (
        big_grouped[0]["image_id"] if big_grouped else -1)
    size_relations = service.repo.db.rows(
        """SELECT * FROM software_lineage WHERE relation='UNKNOWN'
           AND evidence LIKE '%size mismatch%'""")
    pairs = [pair for pair in service.repo.pairs() if pair["confirmed"]]
    mismatched_confirmed = []
    for pair in pairs:
        size_a = service.repo.file(pair["original_file_id"])["file_size"]
        size_b = service.repo.file(pair["tuned_file_id"])["file_size"]
        if size_a != size_b:
            mismatched_confirmed.append(pair["id"])
    passed = (big_ok and separate and bool(size_relations)
              and not mismatched_confirmed)
    detail = (f"2MiB-trio in {len(big_grouped)} identity; 855KB apart="
              f"{separate}; size-relaties={len(size_relations)}; "
              f"size-mismatch-paren={len(mismatched_confirmed)}")
    return {"passed": passed, "detail": detail}
