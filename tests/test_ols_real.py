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
    version_relations = real_service.repo.db.rows('SELECT * FROM ols_version_relations WHERE project_id=?', (project_id,))
    references = real_service.repo.db.rows('SELECT * FROM ols_record_references WHERE project_id=?', (project_id,))

    assert project['sha256'] == before
    assert len(records) >= 100
    assert any(record['record_type'] == 'version_or_role_label' for record in records)
    assert maps and all(item['status'] == 'label_only' for item in maps)
    assert binaries and all(item['status'] in {'boundary_unknown', 'external_reference_missing'} for item in binaries)
    assert version_relations and all(item['relation_type'] == 'target_unknown' for item in version_relations)
    assert references and all(item['reference_type'] == 'binary_target_unknown' for item in references)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


def test_existing_ols_reference_is_indexed_as_unknown(tmp_path, service):
    referenced = tmp_path / 'source.bin'
    referenced.write_bytes(b'raw source')
    project = tmp_path / 'reference.ols'
    value = str(referenced).replace('/', '\\').encode()
    project.write_bytes(b'OLS\x00' + struct.pack('<I', len(value)) + value)
    project_id = service.repo.import_project(project)
    rows = service.repo.db.rows('SELECT * FROM ols_binaries WHERE project_id=?', (project_id,))
    assert rows and rows[-1]['status'] == 'external_file_indexed'
    assert service.repo.file(json.loads(rows[-1]['evidence'])['file_id'])['file_type'] == 'unknown'