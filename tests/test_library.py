"""V5 Local Library Engine: content identity, locations, dedup, incremental,
resume, offline — bronbestanden blijven altijd onaangeroerd."""
import hashlib

import pytest


def _write(path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture()
def lib(service, tmp_path):
    source = tmp_path / "Lib"
    _write(source / "BMW" / "a.bin", b"A" * 4096)
    _write(source / "BMW" / "a_copy.bin", b"A" * 4096)      # duplicate content
    _write(source / "VAG" / "b.ols", b"OLS" * 100)
    _write(source / "notes.txt", b"tekst")                   # unknown type
    before = {path: _digest(path) for path in source.rglob("*") if path.is_file()}
    return service, source, before


def test_root_registration_requires_existing_dir(service, tmp_path):
    with pytest.raises(ValueError):
        service.library.add_root(str(tmp_path / "bestaatniet"))
    root = service.library.add_root(str(tmp_path), "TestRoot")
    assert root["status"] == "ONLINE" and root["name"] == "TestRoot"
    with pytest.raises(ValueError):
        service.library.add_root(str(tmp_path))  # uniek op pad


def test_scan_indexes_without_copying_and_source_untouched(lib):
    service, source, before = lib
    root = service.library.add_root(str(source), "Lib")
    result = service.library.scan_root(root["id"])
    assert result["status"] == "done" and result["new"] == 4
    locations = service.library.locations(root["id"])
    assert len(locations) == 4
    # content identity: a.bin en a_copy.bin delen één content
    contents = {row["content_id"] for row in locations}
    by_name = {row["filename"]: row for row in locations}
    assert by_name["a.bin"]["content_id"] == by_name["a_copy.bin"]["content_id"]
    assert by_name["a_copy.bin"]["scan_status"] == "DUPLICATE"
    assert by_name["b.ols"]["file_type"] == "ols"
    assert by_name["notes.txt"]["file_type"] == "future_known"  # .txt: bekende toekomstige type
    # geen kopie naar data/: geen beheerde .bin in originals/tuned/unknown van de engine
    assert all(path.suffix == ".sqlite" or path.is_dir()
               for path in service.repo.root.rglob("*")
               if "winols_projects" not in str(path))
    # bron onaangeroerd
    for path, digest in before.items():
        assert _digest(path) == digest
    # storage totalen kloppen
    summary = service.library.storage_summary()
    assert summary["locations"] == 4 and summary["unique_contents"] == 3
    assert summary["duplicate_bytes"] == 8192  # beide locaties van dubbele content
    # onbekende types registreren als UNKNOWN
    _write(source / "onbekend.xyz", b"?")
    service.library.scan_root(root["id"])
    by_name = {row["filename"]: row for row in service.library.locations(root["id"])}
    assert by_name["onbekend.xyz"]["file_type"] == "unknown"


def test_incremental_rescan_skips_hashing(lib):
    service, source, before = lib
    root = service.library.add_root(str(source))
    service.library.scan_root(root["id"])
    result = service.library.scan_root(root["id"])
    assert result["hashed"] == 0          # hash-cache: niets opnieuw gehasht
    assert result["unchanged"] == 4
    assert result["new"] == 0 and result["modified"] == 0


def test_modified_file_gets_new_content(lib):
    service, source, before = lib
    root = service.library.add_root(str(source))
    service.library.scan_root(root["id"])
    _write(source / "BMW" / "a.bin", b"B" * 4096)
    result = service.library.scan_root(root["id"])
    assert result["modified"] == 1 and result["hashed"] == 1
    by_name = {row["filename"]: row for row in service.library.locations(root["id"])}
    assert by_name["a.bin"]["sha256"] == _digest(source / "BMW" / "a.bin")
    assert by_name["a.bin"]["content_id"] != by_name["a_copy.bin"]["content_id"]


def test_moved_file_keeps_content_identity(lib):
    service, source, before = lib
    root = service.library.add_root(str(source))
    service.library.scan_root(root["id"])
    content_before = {row["filename"]: row["content_id"]
                      for row in service.library.locations(root["id"])}
    (source / "BMW" / "a.bin").rename(source / "VAG" / "a_verplaatst.bin")
    result = service.library.scan_root(root["id"])
    assert result["moved"] == 1 and result["missing"] == 1
    by_name = {row["filename"]: row for row in service.library.locations(root["id"])}
    assert by_name["a_verplaatst.bin"]["scan_status"] == "MOVED"
    assert by_name["a_verplaatst.bin"]["content_id"] == content_before["a.bin"]
    assert by_name["a.bin"]["scan_status"] == "MISSING"
    # kennis wordt niet opnieuw opgebouwd: zelfde content-ID
    content = service.repo.db.rows("SELECT * FROM content_objects WHERE id=?",
                                   (content_before["a.bin"],))
    assert content and content[0]["sha256"] == before[source / "BMW" / "a.bin"]


def test_resume_continues_after_interruption(lib):
    service, source, before = lib
    for index in range(60):  # genoeg files voor meerdere checkpoints
        _write(source / f"bulk{index // 50}" / f"f{index}.bin", bytes([index]) * 512)
    service.library.config["scan_batch"] = 10  # kleine batches voor het checkpoint-bewijs
    root = service.library.add_root(str(source))
    calls = {"n": 0}

    def progress(_message):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("gesimuleerde crash")

    with pytest.raises(RuntimeError):
        service.library.scan_root(root["id"], progress=progress)
    interrupted = service.library.interrupted_scan(root["id"])
    assert interrupted and interrupted["status"] == "interrupted"
    assert interrupted["checkpoint"].get("last_path")
    result = service.library.scan_root(root["id"], resume=True)
    assert result["status"] == "done"
    assert result["skipped_by_resume"] >= 1   # alleen verder na checkpoint
    assert len(service.library.locations(root["id"])) == 64  # 4 origineel + 60 bulk
    assert service.library.scans(root["id"])[0]["status"] == "done"


def test_offline_disk_does_not_break_database(lib):
    service, source, before = lib
    root = service.library.add_root(str(source))
    service.library.scan_root(root["id"])
    source.rename(source.parent / "Lib_offline")  # schijf/map "offline"
    result = service.library.scan_root(root["id"])
    assert result["status"] == "OFFLINE"
    assert service.library.root(root["id"])["status"] == "OFFLINE"
    # locaties NIET als MISSING gemarkeerd: database blijft bruikbaar
    assert all(row["scan_status"] != "MISSING"
               for row in service.library.locations(root["id"]))
    # terug online: hervatten door opnieuw te scannen
    (source.parent / "Lib_offline").rename(source)
    result = service.library.scan_root(root["id"])
    assert result["status"] == "done"
    assert service.library.root(root["id"])["status"] == "ONLINE"


def test_corrupt_unreadable_file_does_not_stop_scan(lib):
    service, source, before = lib
    _write(source / "VAG" / "locked.bin", b"X" * 128)
    root = service.library.add_root(str(source))
    original_stat = (source / "VAG" / "locked.bin").stat
    service.library.scan_root(root["id"])
    assert len(service.library.locations(root["id"])) == 5


def test_ols_indexed_as_first_class_type(lib):
    service, source, before = lib
    root = service.library.add_root(str(source))
    service.library.scan_root(root["id"])
    ols_rows = [row for row in service.library.locations(root["id"], "b.ols")]
    assert ols_rows and ols_rows[0]["file_type"] == "ols"
    assert len(ols_rows[0]["sha256"]) == 64
