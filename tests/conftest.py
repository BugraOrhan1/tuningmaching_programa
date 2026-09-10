import pytest
from app.service import Service


@pytest.fixture
def service(tmp_path):
    return Service(dict(data_dir=str(tmp_path / 'managed'), max_file_mb=2,
                        top_matches=10, block_size=64, diff_merge_gap=2))


@pytest.fixture
def pair(service, tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    original = b'\x00SW:TEST_SW HW:TEST_HW\x00' + bytes(range(256)) * 8
    tuned = bytearray(original)
    tuned[100:104] = b'\xff' * 4
    tuned[200:203] = b'\xee' * 3
    a, b = source / 'original_001.bin', source / 'tuned_001.bin'
    a.write_bytes(original)
    b.write_bytes(tuned)
    aid, bid = service.repo.import_file(a), service.repo.import_file(b)
    return service.repo.pair(aid, bid, True), a, b
