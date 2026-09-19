"""V7 Tune Bouwer: origineel erin → getunede KANDIDAAT terug, met stage-
en add-onkeuze. Bewijsregels: alleen bevestigde paren, regionaal bewijs
(≥98%), checksum-waarschuwing, bronbestanden nooit gewijzigd, intensiteiten
alleen als er kennis is (UNKNOWN otherwise)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.service import Service
from app.tune_builder import parse_recipe_label


@pytest.fixture()
def service(tmp_path):
    return Service(dict(data_dir=str(tmp_path / "managed"), max_file_mb=8,
                        top_matches=10, block_size=64, diff_merge_gap=2))


_PAIR_COUNTER = iter(range(1000))


def _make_pair(service, tmp_path, index, tuned_changes, stage, name_suffix="",
               confirm=True):
    """Original + tuned met expliciete stage-metadata en label."""
    import itertools
    unique = next(_PAIR_COUNTER)
    source = tmp_path / f"src{index}_{unique}"
    source.mkdir()
    original = b"\x00SW:TB" + str(index).encode() + b" HW:TBH\x00" + \
        bytes((i * 13 + index) % 251 for i in range(4096))
    tuned = bytearray(original)
    for start, value in tuned_changes.items():
        tuned[start:start + 4] = bytes([value]) * 4
    original_path = source / f"original_00{index}.bin"
    tuned_path = source / f"tuned_00{index}{name_suffix}.bin"
    original_path.write_bytes(original)
    tuned_path.write_bytes(bytes(tuned))
    original_id = service.repo.import_file(original_path, "original")
    tuned_id = service.repo.import_file(tuned_path, "tuned")
    service.repo.update_metadata(tuned_id, {"stage": stage})
    pair_id = service.repo.pair(original_id, tuned_id)
    if confirm:
        service.repo.confirm_pair(pair_id)
    return {"pair_id": pair_id, "original_id": original_id, "tuned_id": tuned_id,
            "original_bytes": original, "tuned_bytes": bytes(tuned)}


def test_parse_recipe_label_extracts_stage_addons_intensity():
    parsed = parse_recipe_label("BMW 4 Serie (Stage1 + vmax + pops and bang -30)")
    assert parsed["stage"] == "stage1"
    assert "pops_bang" in parsed["addons"] and "vmax" in parsed["addons"]
    assert parsed["intensity"] == 30
    assert parse_recipe_label("Stock / Original")["stage"] is None


def test_recipes_come_only_from_confirmed_pairs(service, tmp_path):
    confirmed = _make_pair(service, tmp_path, 1, {300: 0xAA}, "stage1")
    _make_pair(service, tmp_path, 2, {400: 0xBB}, "stage2", confirm=False)
    options = service.tune_recipes()
    pair_ids = {recipe["pair_id"] for recipe in options["recipes"]}
    assert confirmed["pair_id"] in pair_ids
    assert all(recipe["stage"] in ("stage1", "stage2") for recipe in options["recipes"]
               if recipe["pair_id"] == confirmed["pair_id"])
    # het onbevestigde paar levert geen recept
    assert len([r for r in options["recipes"] if r["stage"] == "stage2"]) == 0


def test_build_identical_original_returns_tuned_bytes(service, tmp_path):
    pair = _make_pair(service, tmp_path, 3, {300: 0xCC, 900: 0xDD}, "stage1")
    original_path = tmp_path / "klant_origineel.bin"
    original_path.write_bytes(pair["original_bytes"])
    before = original_path.read_bytes()
    result = service.build_tune(original_path=str(original_path), stage="stage1",
                                dry_run=False)
    assert result["status"] == "candidate_generated"
    output = Path(result["output_path"]).read_bytes()
    assert output == pair["tuned_bytes"]
    # bronbestand onaangeroerd
    assert original_path.read_bytes() == before
    assert any("checksums" in warning.lower() for warning in result["warnings"])
    assert any("review" in warning.lower() for warning in result["warnings"])
    # rapportsidecar bestaat
    assert Path(result["report_path"]).exists()


def test_build_dry_run_writes_nothing(service, tmp_path):
    pair = _make_pair(service, tmp_path, 4, {310: 0xEE}, "stage1")
    original_path = tmp_path / "dry_origineel.bin"
    original_path.write_bytes(pair["original_bytes"])
    result = service.build_tune(original_path=str(original_path), stage="stage1",
                                dry_run=True)
    assert result["status"] == "dry_run"
    assert "output_path" not in result
    candidates = list((service.repo.root / "exports" / "candidates").glob("*")) \
        if (service.repo.root / "exports" / "candidates").exists() else []
    assert candidates == []


def test_regional_proof_skips_diverging_regions(service, tmp_path):
    pair = _make_pair(service, tmp_path, 5, {300: 0x11, 2000: 0x22}, "stage1")
    # klant-original wijkt substantieel af in de tweede regio
    customer = bytearray(pair["original_bytes"])
    customer[2000:2004] = b"\x99" * 4
    customer[2400:2448] = bytes((i * 71) % 253 for i in range(48))
    customer_path = tmp_path / "klant_afwijkend.bin"
    customer_path.write_bytes(bytes(customer))
    result = service.build_tune(original_path=str(customer_path), stage="stage1",
                                dry_run=False)
    assert result["status"] == "candidate_generated"
    applied_starts = {region["start_offset"] for region in result["applied_regions"]}
    assert 300 in applied_starts and 2000 not in applied_starts
    output = Path(result["output_path"]).read_bytes()
    # afwijkende regio is onaangeroerd gebleven
    assert output[2400:2448] == bytes(customer[2400:2448])


def test_stage_selection_between_two_recipes(service, tmp_path):
    """Eén original, twee getunede varianten (stage1/stage2): het gekozen
    recept bepaalt de output; beide delen dezelfde original-bytes."""
    import itertools
    shared = next(_PAIR_COUNTER)
    source = tmp_path / f"shared_{shared}"
    source.mkdir()
    original = b"\x00SW:SS HW:SSH\x00" + bytes((i * 17 + 3) % 251 for i in range(4096))
    variants = {}
    for label, changes in (("stage1", {300: 0x21}),
                           ("stage2", {300: 0x22, 1200: 0x23})):
        tuned = bytearray(original)
        for start, value in changes.items():
            tuned[start:start + 4] = bytes([value]) * 4
        original_path = source / f"original_{label}.bin"
        tuned_path = source / f"tuned_{label}.bin"
        original_path.write_bytes(original)
        tuned_path.write_bytes(bytes(tuned))
        original_id = service.repo.import_file(original_path, "original")
        tuned_id = service.repo.import_file(tuned_path, "tuned")
        service.repo.update_metadata(tuned_id, {"stage": label})
        pair_id = service.repo.pair(original_id, tuned_id)
        service.repo.confirm_pair(pair_id)
        variants[label] = bytes(tuned)
    original_path = source / "klant.bin"
    original_path.write_bytes(original)
    result = service.build_tune(original_path=str(original_path), stage="stage2",
                                dry_run=False)
    assert result["status"] == "candidate_generated", result
    assert Path(result["output_path"]).read_bytes() == variants["stage2"]
    result1 = service.build_tune(original_path=str(original_path), stage="stage1",
                                 dry_run=False)
    assert Path(result1["output_path"]).read_bytes() == variants["stage1"]


def test_addon_chain_composes_stage_plus_pop(service, tmp_path):
    """Stage1 en Stage1+pops&bang van hetzelfde original: de add-on wordt
    gecomponeerd via de bewezen keten (O→T1, delta T1→T2)."""
    base = _make_pair(service, tmp_path, 8, {300: 0x31}, "stage1")
    pair2 = _make_pair(service, tmp_path, 8, {300: 0x31, 1500: 0x44},
                       "stage1", name_suffix="_pops_and_bang")
    # zelfde original-bytes: tweede import is byte-identiek → zelfde content
    assert pair2["original_bytes"] == base["original_bytes"]
    original_path = tmp_path / "add_on_origineel.bin"
    original_path.write_bytes(base["original_bytes"])
    result = service.build_tune(original_path=str(original_path), stage="stage1",
                                addons=["pops_bang"], dry_run=False)
    assert result["status"] == "candidate_generated", result
    output = Path(result["output_path"]).read_bytes()
    # pops-regio is toegepast (0x44 op 1500) en stage-regio ook (0x31 op 300)
    assert output[1500:1504] == b"\x44" * 4
    assert output[300:304] == b"\x31" * 4


def test_unknown_intensity_returns_available_without_writing(service, tmp_path):
    pair = _make_pair(service, tmp_path, 9, {300: 0x55}, "stage1")
    original_path = tmp_path / "intensiteit_origineel.bin"
    original_path.write_bytes(pair["original_bytes"])
    result = service.build_tune(original_path=str(original_path), stage="stage1",
                                intensity=45, dry_run=False)
    assert result["status"] == "UNKNOWN_NO_RECIPE"
    assert 45 not in result["available"]["intensities"]
    candidates = list((service.repo.root / "exports" / "candidates").glob("*")) \
        if (service.repo.root / "exports" / "candidates").exists() else []
    assert candidates == []


def test_size_mismatch_is_refused(service, tmp_path):
    pair = _make_pair(service, tmp_path, 10, {300: 0x66}, "stage1")
    other = tmp_path / "ander_formaat.bin"
    other.write_bytes(pair["original_bytes"] + b"\x00" * 256)
    result = service.build_tune(original_path=str(other), stage="stage1",
                                dry_run=False)
    assert result["status"] in ("no_match_above_threshold", "no_regions_applied",
                                "UNKNOWN_NO_RECIPE")
    assert "output_path" not in result


def test_unconfirmed_pair_never_builds(service, tmp_path):
    pair = _make_pair(service, tmp_path, 11, {300: 0x77}, "stage1", confirm=False)
    original_path = tmp_path / "niet_bevestigd.bin"
    original_path.write_bytes(pair["original_bytes"])
    result = service.build_tune(original_path=str(original_path), stage="stage1",
                                dry_run=False)
    assert result["status"] in ("UNKNOWN_NO_RECIPE", "no_regions_applied")
    assert "output_path" not in result


def test_duplicate_candidate_gets_same_id(service, tmp_path):
    pair = _make_pair(service, tmp_path, 12, {300: 0x88}, "stage1")
    original_path = tmp_path / "dup_origineel.bin"
    original_path.write_bytes(pair["original_bytes"])
    first = service.build_tune(original_path=str(original_path), stage="stage1",
                               dry_run=False)
    second = service.build_tune(original_path=str(original_path), stage="stage1",
                                dry_run=False)
    assert first["status"] == second["status"] == "candidate_generated"
    assert first["candidate_id"] == second["candidate_id"]
    assert first["output_path"] == second["output_path"]


def test_tune_builder_api(service, tmp_path):
    from fastapi.testclient import TestClient
    from app.api import create_api
    pair = _make_pair(service, tmp_path, 13, {300: 0x99}, "stage1")
    original_path = tmp_path / "api_origineel.bin"
    original_path.write_bytes(pair["original_bytes"])
    client = TestClient(create_api(service, "k" * 32))
    headers = {"X-API-Key": "k" * 32}
    recipes = client.get("/tune-recipes", headers=headers).json()
    assert recipes["stages"] == ["stage1"]
    build = client.post("/tune-build", headers=headers, json={
        "original_path": str(original_path), "stage": "stage1", "dry_run": False})
    assert build.status_code == 200
    assert build.json()["status"] == "candidate_generated"


def test_parse_recipe_labels_expanded():
    """Stage 1-5 + de nieuwe add-ons (decat, antilag, launch control, e85,
    swirl off, cold start off)."""
    cases = [
        ("bmw stage4 decat", "stage4", ["decat"]),
        ("rs3 stage 5 antilag", "stage5", ["antilag"]),
        ("golf launch control", None, ["launch_control"]),
        ("audi e85 flex fuel", None, ["e85"]),
        ("vw swirl off", None, ["swirl_off"]),
        ("bmw coldstart off", None, ["cold_start_off"]),
        ("a3 stage2 + pops&bang 50", "stage2", ["pops_bang"]),
    ]
    for label, stage, addons in cases:
        parsed = parse_recipe_label(label)
        assert parsed["stage"] == stage, (label, parsed)
        for addon in addons:
            assert addon in parsed["addons"], (label, parsed)


def test_build_chains_multiple_addons(service, tmp_path):
    """MEERDERE add-ons die in aparte recepten zitten: de planner ketent
    stage1+pops en stage1+vmax — beide regio's komen in de output, de
    overlappende stage-regio wordt één keer toegepast."""
    base = _make_pair(service, tmp_path, 9, {300: 0x51, 1500: 0x44}, "stage1",
                      name_suffix="_pops_and_bang")
    pair2 = _make_pair(service, tmp_path, 9, {300: 0x51, 900: 0x62},
                       "stage1", name_suffix="_vmax")
    assert base["original_bytes"] == pair2["original_bytes"]
    original_path = tmp_path / "multi_addon_origineel.bin"
    original_path.write_bytes(base["original_bytes"])
    result = service.build_tune(original_path=str(original_path), stage="stage1",
                                addons=["pops_bang", "vmax"], dry_run=False)
    assert result["status"] == "candidate_generated", result
    assert len(result["chain"]) == 2, result["chain"]
    assert result["recipe"]["selected"].count("+") >= 1
    output = Path(result["output_path"]).read_bytes()
    assert output[300:304] == b"\x51" * 4       # stage-regio (één keer)
    assert output[900:904] == b"\x62" * 4       # vmax-regio (recept 2)
    assert output[1500:1504] == b"\x44" * 4     # pops-regio (recept 1)
    skipped_reasons = " ".join(item.get("reason", "") for item in result["skipped_regions"])
    assert "eerder recept" in skipped_reasons    # overlap (300) netjes overgeslagen


def test_apply_pair_skips_overlapping_regions(service, tmp_path):
    """Regio's die al door een eerder recept in de keten zijn toegepast
    worden overgeslagen met duidelijke reden — nooit dubbel wijzigen."""
    builder = service.tune_builder
    base = _make_pair(service, tmp_path, 9, {300: 0x51}, "stage1")
    result = bytearray(base["original_bytes"])
    outcome, applied, skipped = builder._apply_pair(
        result, bytes(base["original_bytes"]), base["pair_id"], [(0, 4096)])
    assert outcome == "ok"
    assert applied == []
    assert skipped and "eerder recept" in skipped[0]["reason"]
    # zonder ranges: regio wordt gewoon toegepast (oude gedrag intact)
    result2 = bytearray(base["original_bytes"])
    outcome2, applied2, _skipped2 = builder._apply_pair(
        result2, bytes(base["original_bytes"]), base["pair_id"])
    assert outcome2 == "ok" and applied2


def _family_original(service, tmp_path, tag, ecu="MED17.1.21", sw="FAM_SW",
                     delta=None):
    """Eigen original binnen een familie (metadata expliciet gezet)."""
    import itertools
    unique = next(_PAIR_COUNTER)
    source = tmp_path / f"fam_{tag}_{unique}"
    source.mkdir()
    original = (b"\x00SW:" + sw.encode() + b" HW:FAMH\x00"
                + bytes((i * 7 + unique) % 251 for i in range(4096)))
    original_path = source / f"orig_{tag}.bin"
    original_path.write_bytes(original)
    original_id = service.repo.import_file(original_path, "original")
    service.repo.update_metadata(original_id, {"ecu_family": ecu,
                                               "software_number": sw})
    if delta:
        tuned = bytearray(original)
        for start, value in delta.items():
            tuned[start:start + 4] = bytes([value]) * 4
        tuned_path = source / f"tuned_{tag}_stage1.bin"
        tuned_path.write_bytes(bytes(tuned))
        tuned_id = service.repo.import_file(tuned_path, "tuned")
        service.repo.update_metadata(tuned_id, {"stage": "stage1"})
        pair_id = service.repo.pair(original_id, tuned_id)
        service.repo.confirm_pair(pair_id)
        return {"original_id": original_id, "original_bytes": original,
                "pair_id": pair_id, "tuned_id": tuned_id}
    return {"original_id": original_id, "original_bytes": original}


def test_transfer_applies_consistent_family_deltas(service, tmp_path):
    """Kern-scenario van de gebruiker: géén tuned-bestand van deze auto, maar
    ≥2 bevestigde paren in dezelfde familie met IDENTIEKE wijziging op
    offset 300 → die delta wordt overgedragen. Inconsistente regio (800:
    verschillende waarden) en eenmalige regio (900) worden NIET toegepast."""
    a = _family_original(service, tmp_path, "A", delta={300: 0xAA, 800: 0x11})
    b = _family_original(service, tmp_path, "B", delta={300: 0xAA, 800: 0x22, 900: 0x33})
    assert a["original_bytes"] != b["original_bytes"]
    # doel: derde auto uit dezelfde familie, zonder eigen pair
    target = _family_original(service, tmp_path, "C")
    result = service.build_tune(
        original_file_id=target["original_id"], stage="stage1",
        addons=["pops_bang"], dry_run=False, allow_transfer=True)
    assert result["status"] == "candidate_generated", result
    assert result["transfer"] is True
    applied_starts = {region["start_offset"]: region for region in result["applied_regions"]}
    assert 300 in applied_starts
    assert bytes.fromhex(applied_starts[300]["tuned_bytes"]) == b"\xAA" * 4
    assert 800 not in applied_starts and 900 not in applied_starts
    assert applied_starts[300]["confirmed_pairs"] == [a["pair_id"], b["pair_id"]]
    assert any("OVERDRACHTSMODUS" in warning for warning in result["warnings"])
    output = Path(result["output_path"]).read_bytes()
    assert output[300:304] == b"\xAA" * 4
    assert output[800:804] == target["original_bytes"][800:804]  # onaangetast


def test_transfer_refuses_without_consistent_knowledge(service, tmp_path):
    """Eén paar (min_pairs=2 niet gehaald) → UNKNOWN_NO_TRANSFER_KNOWLEDGE,
    ook al is er een bevestigd paar in de familie."""
    _family_original(service, tmp_path, "X", delta={300: 0xAA})
    target = _family_original(service, tmp_path, "Y")
    result = service.build_tune(
        original_file_id=target["original_id"], dry_run=False, allow_transfer=True)
    assert result["status"] == "UNKNOWN_NO_TRANSFER_KNOWLEDGE"


def test_transfer_refused_without_family_match(service, tmp_path):
    """Doel lijkt op niets bekends (andere familie/metadata) → geen overdracht."""
    _family_original(service, tmp_path, "A", delta={300: 0xAA})
    _family_original(service, tmp_path, "B", delta={300: 0xAA})
    vreemd = _family_original(service, tmp_path, "Z", ecu="SIM2K", sw="ANDERE_SW")
    result = service.build_tune(
        original_file_id=vreemd["original_id"], dry_run=False, allow_transfer=True)
    assert result["status"] in ("no_match_for_transfer",
                                "UNKNOWN_NO_TRANSFER_KNOWLEDGE")
