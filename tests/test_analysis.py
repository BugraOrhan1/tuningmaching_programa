import hashlib
import random
import pytest
from app.analysis.fingerprint import hashes, fingerprint
from app.analysis.diff_engine import diff_blocks
from app.analysis.similarity import compare
from app.analysis.metadata import extract_metadata
from app.analysis.ecu_fingerprint import ecu_family_fingerprint, structural_similarity
from app.analysis.recognition import recognize
from app.analysis.signatures import matches_signature, discover_candidate_signatures
from app.analysis.alignment import align_regions


def test_hashes():
    assert hashes(b'abc')['sha256'] == hashlib.sha256(b'abc').hexdigest()
    assert hashes(b'abc')['md5'] == '900150983cd24fb0d6963f7d28e17f72'
    assert hashes(b'abc')['crc32'] == '352441c2'
    assert sum(fingerprint(b'abc')['histogram']) == pytest.approx(1)


def test_diff_gap_and_tail():
    blocks = diff_blocks(b'abcdef', b'axcyez!', 1)
    assert len(blocks) == 1
    assert blocks[0]['start_offset'] == 1
    assert blocks[0]['end_offset'] == 7
    assert blocks[0]['changed_bytes'] == 4
    assert diff_blocks(b'abc', b'abc') == []
    assert diff_blocks(b'abc', b'a')[0]['changed_bytes'] == 2


def test_diff_random_oracle():
    rng = random.Random(42)
    for _ in range(100):
        a, b = rng.randbytes(rng.randrange(200)), rng.randbytes(rng.randrange(200))
        expected = {i for i in range(max(len(a), len(b))) if a[i:i+1] != b[i:i+1]}
        blocks = diff_blocks(a, b, 3)
        assert sum(x['changed_bytes'] for x in blocks) == len(expected)
        assert all(any(x['start_offset'] <= i < x['end_offset'] for x in blocks) for i in expected)
        assert all(x['end_offset'] <= y['start_offset'] for x, y in zip(blocks, blocks[1:]))


def test_score_and_confidence():
    score = compare(b'abc', b'abx', {}, {})
    assert score['match_score'] == pytest.approx(66.6667)
    assert score['longest_identical_range'] == 2
    assert compare(b'abc', b'abc', {}, {})['compatibility_confidence'] == 100
    assert compare(b'abc', b'abc', {'software_number':'A'}, {'software_number':'B'})['compatibility_confidence'] <= 10
    assert compare(b'abc', b'abcx', {}, {})['compatibility_confidence'] <= 20
    incompatible = compare(b'abc', b'xyz', {}, {})
    assert incompatible['compatibility_confidence'] == 0
    assert incompatible['compatibility_status'] == 'incompatible_base'


def test_metadata_conservative():
    assert extract_metadata(b'\x00HW:123 SW:ABC\x00') == {'hardware_number':'123', 'software_number':'ABC'}
    assert extract_metadata(b'SW:ABC SW:DEF\x00') == {}
    assert extract_metadata(b'random MED17 Bosch strings') == {}


def test_v2_fingerprint_recognition_signatures_and_alignment():
    left = b'\x00ECU:MED17.1.21 HW:04E 907 309 SW:04E906016ABC\x00' + b'A' * 256
    right = b'\x00' * 64 + left
    fingerprint = ecu_family_fingerprint(left, 64)
    assert fingerprint['file_size'] == len(left)
    assert fingerprint['entropy_profile']
    assert structural_similarity(fingerprint, ecu_family_fingerprint(left, 64)) == 100
    identification = recognize(left)
    assert identification['ecu'][0]['value'] == 'MED17.1.21'
    assert identification['ecu'][0]['state'] == 'DETECTED'
    assert matches_signature(left, 1, b'ECU', b'\xff\xff\xff')
    assert not matches_signature(left, 1, b'ECU', b'\xff\x00')
    candidates = discover_candidate_signatures([left, left, left], min_length=16)
    assert candidates and candidates[0]['length'] <= 64
    regions = align_regions(left, right, 64, 2)
    assert any(region['source_start'] == 0 and region['target_start'] == 64 for region in regions)
