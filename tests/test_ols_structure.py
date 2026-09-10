"""Tests voor de evidence-based OLS-structuurreconstructie en automatische pipeline.

De synthetische OLS is een miniatuur van de bevestigde echte WinOLS 5-structuur:
lengte-geprefixede ASCII-records, een import-header met bestandsnaam gevolgd door
een ruwe binary, en versie-pages met een identiteitsheader op vaste stride.
"""
import struct
from pathlib import Path

import pytest

from app.service import Service
from app.winols.ols_structure import parse_ols_structure


IDENTITY = b'53/1/TESTECU/11/TESTECU_BOX_SWAP01//SW01///'
SOFTWARE = b'FuSi_Test_043.001.0'


def _page(payload_seed: int, size: int = 2048) -> bytes:
    header = IDENTITY + b'\x00' + SOFTWARE + b'\x00'
    body = bytes((payload_seed + i) % 251 for i in range(size - len(header) - 16))
    return header + body + b'\x00' * 16  # echte pages eindigen op nulregio's


def build_ols() -> bytes:
    parts = [b'\x0b\x00\x00\x00WinOLS File\x00']
    parts.append(struct.pack('<I', 3) + b'BMW')
    parts.append(struct.pack('<I', 8) + b'1: 080100-0F6F9F')
    # versielijst: naam-record + importpad in tekstblob + NOCS
    for name, path in ((b'Origineel', b'C:\\src\\orig_test.bin'),
                       (b'Test Stage 1', b'C:\\src\\stage1_test.bin'),
                       (b'Test Stage 1', b'C:\\src\\stage1_v3.bin')):
        parts.append(struct.pack('<I', len(name)) + name)
        blob = b'Ge\xefmporteerd uit bestand:\r\n' + path + b'\x00\x00\x00\x00'
        parts.append(blob)
        parts.append(struct.pack('<I', 4) + b'NOCS')
    # maprecord met naam + adres
    parts.append(struct.pack('<I', 17) + b'Kaart "Test Map A"')
    parts.append(struct.pack('<I', 12) + struct.pack('<I', 0x081046) + struct.pack('<I', 0x200000))
    # binary 1: import-header + ruwe inhoud (compact, zoals in het echte bestand)
    filename = b'orig_test.bin'
    path = b'C:\\src'
    blob1 = bytes((7 * i) % 253 for i in range(1200))
    parts.append(struct.pack('<I', len(filename)) + filename)
    parts.append(struct.pack('<I', len(path)) + path + b'\x00' * 8)
    parts.append(blob1)
    parts.append(b'\x00' * 16)      # nul-padding vóór elke page (zoals echt)
    parts.append(_page(11))          # versie 2
    parts.append(b'\x00' * 16)
    parts.append(_page(11))          # versie 3: identiek aan versie 2
    parts.append(b'\x00' * 16)
    parts.append(_page(77)[:1024])   # versie 4: afgebroken page
    return b''.join(parts)


@pytest.fixture
def ols_file(tmp_path):
    target = tmp_path / 'TEST_001.ols'
    target.write_bytes(build_ols())
    return target


def test_structure_parser_proves_versions_and_binaries(ols_file):
    structure = parse_ols_structure(ols_file.read_bytes())
    assert structure['format_signature'] == 'WinOLS File'
    assert structure['project']['binary_stride'] == 2064  # page 2048 + 16 nul-gap

    roles = {item['name']: item['role'] for item in structure['versions']}
    assert roles == {'Origineel': 'original', 'Test Stage 1': 'tuned'}

    binaries = structure['binaries']
    assert len(binaries) == 4
    assert binaries[0]['extraction_method'] == 'explicit_import_header'
    assert binaries[0]['filename'] == 'orig_test.bin'
    complete_pages = [item for item in binaries[1:] if item['complete']]
    assert len(complete_pages) == 2
    assert complete_pages[0]['sha256'] == complete_pages[1]['sha256']
    assert binaries[3]['complete'] is False

    by_relation = {item['relation_type'] for item in structure['version_binaries']}
    assert 'version_to_binary_explicit' in by_relation
    assert 'version_to_binary_order_inferred' in by_relation
    assert sum(1 for item in structure['version_binaries'] if item['name'] is None) == 1


def test_auto_process_ols_extracts_files_roles_and_pairs(service, ols_file):
    result = service.auto_process_ols(str(ols_file))
    assert result['files_extracted'] == 4
    roles = {item['name']: item['role'] for item in result['versions'] if item['name']}
    assert roles == {'Origineel': 'original', 'Test Stage 1': 'tuned'}
    # de niet-gekoppelde pages blijven bewust 'unknown'
    assert any(item['name'] is None and item['role'] == 'unknown' for item in result['versions'])

    files = service.repo.files()
    assert len(files) == 4
    by_type = {row['file_type'] for row in files}
    assert by_type == {'original', 'tuned', 'unknown'}
    original = next(row for row in files if row['file_type'] == 'original')
    assert original['filename'] == 'orig_test.bin'
    assert original['file_size'] == 1216  # blob 1200 + trailing zero-gap (zelfde gedrag als echte OLS)
    # identieke pages → zelfde sha256 → dezelfde inhoud, maar twee versieregels
    tuned = [row for row in files if row['file_type'] == 'tuned']
    assert len(tuned) == 2 and tuned[0]['sha256'] == tuned[1]['sha256']

    # Original en tuned versie zijn hier gelijk van grootte (1200 vs 2048 → geen paar)
    assert all(item['status'] == 'size_mismatch_not_paired' for item in result['pairs'])


def test_auto_process_pairs_and_dna_for_equal_sizes(service, tmp_path):
    ols = tmp_path / 'PAIR_001.ols'
    # page-inhoud gelijk aan de original-lengte: page = identity-header + body
    body_size = 2048
    page = _page(5, body_size + len(IDENTITY) + 1 + len(SOFTWARE) + 1)
    parts = [b'\x0b\x00\x00\x00WinOLS File\x00']
    for name, path in ((b'Origineel', b'C:\\s\\o.bin'), (b'Test Stage 1', b'C:\\s\\t.bin')):
        parts.append(struct.pack('<I', len(name)) + name)
        parts.append(b'Ge\xefmporteerd uit bestand:\r\n' + path + b'\x00\x00\x00\x00')
        parts.append(struct.pack('<I', 4) + b'NOCS')
    parts.append(b'\x00' * 16)  # nul-padding vóór de eerste page (zoals echt; telt niet mee in de stride)
    parts.append(page)                                             # page eindigt op 16 nulbytes
    parts.append(bytearray(page[:-1] + bytes([page[-1] ^ 0xFF])))  # tuned: 1 byte anders
    ols.write_bytes(b''.join(parts))

    result = service.auto_process_ols(str(ols))
    confirmed = [item for item in result['pairs'] if item.get('confirmed')]
    assert len(confirmed) == 1
    assert result['tuning_dna'] and result['tuning_dna'][0]['regions'] >= 1
    dna = service.tuning_dna()
    assert dna and dna[0]['status'] == 'candidate'


def test_generate_tune_candidate_applies_known_regions(service, tmp_path):
    base = b'ECU:MED17.1 SW:CAND ' + bytes(range(256)) * 8
    original, tuned = tmp_path / 'cand_ori.bin', tmp_path / 'cand_mod.bin'
    original.write_bytes(base)
    tuned.write_bytes(base[:400] + b'\xcd' * 32 + base[432:])
    oid = service.repo.import_file(original, 'original')
    tid = service.repo.import_file(tuned, 'tuned')
    pair_id = service.repo.pair(oid, tid, True)
    service.generate_tuning_dna(pair_id)

    query = bytearray(base)
    query[1000:1004] = b'\x11\x22\x33\x44'
    query_path = tmp_path / 'new_upload.bin'
    query_path.write_bytes(bytes(query))
    query_id = service.repo.import_file(query_path, 'unknown')

    report = service.generate_tune_candidate(query_id, threshold=70.0)
    assert report['status'] == 'candidate_generated'
    assert report['match_score'] >= 70.0
    output = Path(report['output_path']).read_bytes()
    assert output[400:432] == b'\xcd' * 32          # bekende tuned-regio toegepast
    assert output[1000:1004] == bytes(query[1000:1004])  # eigenlijke inhoud behouden
    assert service.repo.data(query_id) == bytes(query)   # target nooit gewijzigd
    candidates = service.tune_candidates()
    assert candidates and candidates[0]['status'] == 'candidate'
    assert 'checksums' in ' '.join(candidates[0]['payload']['warnings']).lower()


def test_generate_tune_candidate_refuses_low_and_unconfirmed(service, tmp_path):
    base = b'ECU:MED17.1 SW:REFF ' + bytes(range(256)) * 4
    original, tuned = tmp_path / 'ref_ori.bin', tmp_path / 'ref_mod.bin'
    original.write_bytes(base)
    tuned.write_bytes(base[:100] + b'\xfe' * 16 + base[116:])
    oid = service.repo.import_file(original, 'original')
    tid = service.repo.import_file(tuned, 'tuned')
    service.repo.pair(oid, tid, False)  # bewust onbevestigd

    other = tmp_path / 'other.bin'
    other.write_bytes(b'heel iets anders ' * 40)
    other_id = service.repo.import_file(other, 'unknown')
    assert service.generate_tune_candidate(other_id, threshold=70.0)['status'] == 'no_match_above_threshold'

    near = bytearray(base)
    near[50:54] = b'\x99\x88\x77\x66'
    near_path = tmp_path / 'near.bin'
    near_path.write_bytes(bytes(near))
    near_id = service.repo.import_file(near_path, 'unknown')
    assert service.generate_tune_candidate(near_id, threshold=70.0)['status'] == 'no_confirmed_pair'
    with pytest.raises(ValueError):
        service.generate_tune_candidate(near_id, threshold=10.0)
