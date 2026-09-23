from pathlib import Path
import hashlib
import json
import struct
import pytest
from app.service import Service


def test_real_ols_structure_is_observed_without_inventing_links(service):
    root = Path(__file__).parents[1]
    candidates = [root / 'data' / 'winols_projects' / 'GASDROP_100119.ols']
    candidates.extend(sorted(root.glob('data_backup_*/winols_projects/GASDROP_100119.ols'), reverse=True))
    source = next((path for path in candidates if path.exists()), None)
    if source is None:
        pytest.skip('Echte GASDROP_100119.ols is niet aanwezig in workspace of backup')
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    real_service = Service({**service.repo.config, 'max_file_mb': 16})
    project_id = real_service.repo.import_project(source)

    project = real_service.repo.project(project_id)
    records = real_service.repo.project_records(project_id)
    maps = real_service.repo.db.rows('SELECT * FROM ols_map_objects WHERE project_id=?', (project_id,))
    binaries = real_service.repo.db.rows('SELECT * FROM ols_binaries WHERE project_id=?', (project_id,))
    versions = real_service.repo.ols_versions(project_id)

    assert project['sha256'] == before
    assert len(records) >= 100

    # bewezen binaries: 4 volledige + 1 afgekapte versiepage
    extracted_rows = [row for row in binaries if row['internal_id'].startswith('binary@')]
    assert len(extracted_rows) == 5
    assert all(row['content_available'] == 1 and row['sha256'] for row in extracted_rows)
    complete = [row for row in extracted_rows if row['status'] == 'extracted']
    incomplete = [row for row in extracted_rows if row['status'] == 'extracted_incomplete']
    assert len(complete) == 4 and len(incomplete) == 1
    assert {row['length'] for row in complete if row['offset'] > 1000000} == {2097152}
    # de twee identieke stage-binaries delen één sha256
    page_hashes = [row['sha256'] for row in complete if row['length'] == 2097152]
    assert len(page_hashes) == 3 and len(set(page_hashes)) == 2
    # de externe padverwijzing naar het bronbestand blijft apart als evidence bestaan
    assert any(row['status'] == 'external_reference_missing' for row in binaries)

    # mapkandidaten: adressen binnen het gelezen adresbereik
    assert len(maps) >= 200
    addressed = [row for row in maps if row['address']]
    assert len(addressed) >= 200
    assert all(row['status'] == 'address_observed' for row in addressed)

    # versies: Origineel = original op expliciet label; stages = tuned
    assert len(versions) == 5
    by_name = {row['version_name']: row for row in versions}
    original = by_name['Origineel']
    assert original['role'] == 'original' and original['role_confidence'] == 100.0
    assert original['relation_type'] == 'version_to_binary_explicit'
    assert original['complete'] == 1 and original['file_id']
    tuned = [row for row in versions if row['role'] == 'tuned']
    assert len(tuned) == 3
    assert all(row['file_id'] and row['complete'] == 1 for row in tuned)
    assert all(row['relation_confidence'] == 75.0 for row in tuned)

    # geëxtraheerde bestanden staan in Files met bewaarde rol
    files = {row['id']: row for row in real_service.repo.files()}
    assert len(files) == 5
    assert files[original['file_id']]['file_type'] == 'original'
    assert files[original['file_id']]['file_size'] == 855132
    assert all(files[row['file_id']]['file_type'] == 'tuned' for row in tuned)
    assert hashlib.sha256(real_service.repo.data(original['file_id'])).hexdigest() == original['binary_sha256']

    # herimport: geen duplicaten, reviews blijven behouden
    assert real_service.repo.import_project(source) == project_id
    assert len(real_service.repo.files()) == 5
    assert len(real_service.repo.ols_versions(project_id)) == 5

    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


def test_existing_ols_reference_is_indexed_as_unknown(tmp_path, service):
    referenced = tmp_path / 'source.bin'
    referenced.write_bytes(b'raw source')
    project = tmp_path / 'reference.ols'
    project.write_bytes(b'OLS\x00' + struct.pack('<I', len(str(referenced))) + str(referenced).encode())
    project_id = service.repo.import_project(project)
    rows = service.repo.db.rows('SELECT * FROM ols_binaries WHERE project_id=?', (project_id,))
    assert rows and rows[-1]['status'] == 'external_file_indexed'
    assert service.repo.file(json.loads(rows[-1]['evidence'])['file_id'])['file_type'] == 'unknown'

def test_real_ols_binary_boundaries_are_proven(service):
    """REAL DATA VERIFIED: payload-grenzen van elke binary in de echte OLS."""
    from app.winols.ols_structure import parse_ols_structure
    root = Path(__file__).parents[1]
    candidates = [root / 'data' / 'winols_projects' / 'GASDROP_100119.ols']
    source = next((path for path in candidates if path.exists()), None)
    if source is None:
        pytest.skip('Echte GASDROP_100119.ols is niet aanwezig')
    data = source.read_bytes()
    structure = parse_ols_structure(data)
    binaries = structure['binaries']
    assert len(binaries) == 5
    for binary in binaries:
        assert binary['payload_offset'] == binary['start']
        assert binary['payload_length'] == binary['length']
        assert binary['end_boundary'] == binary['start'] + binary['length']
        assert binary['boundary_status'] in {'COMPLETE', 'PARTIAL'}
        assert binary['payload_length'] <= len(data) - binary['payload_offset']
    complete = [b for b in binaries if b['boundary_status'] == 'COMPLETE']
    partial = [b for b in binaries if b['boundary_status'] == 'PARTIAL']
    assert len(complete) == 4 and len(partial) == 1
    pages = [b for b in complete if b['length'] == 2097152]
    assert len(pages) == 3
    assert partial[0]['end_boundary'] <= len(data)
    # source_offset/source_length aanwezig: de brongrens is expliciet bewaard
    assert all('source_offset' in b and 'source_length' in b for b in binaries)
