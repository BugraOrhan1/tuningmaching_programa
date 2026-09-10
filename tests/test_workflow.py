import json
import pytest
from app.utils.reset import reset_data_dir
from app.database.repository import pair_key
from app.learning.model import LearningIndex
from app.winols.project_export import export_report


def test_import_pair_diff_and_rank(service, pair):
    pair_id, a, b = pair
    before = a.read_bytes()
    assert len(service.repo.files()) == 2
    service.repo.import_file(a)
    assert len(service.repo.files()) == 2
    report = service.diff(pair_id)
    assert report['changed_bytes'] == 7
    assert len(report['blocks']) == 2
    analysis = service.analyze(str(a))
    assert analysis['matches'][0]['match_score'] == 100
    assert analysis['matches'][0]['known_changes'][0]['changed_bytes'] == 7
    assert a.read_bytes() == before
    assert service.hex(pair_id, 96)[0]['changed'] == [4, 5, 6, 7]


@pytest.mark.parametrize('a,b', [('original_001.bin','tuned_001.bin'), ('ABC123_original.bin','ABC123_stage1.bin'), ('ORI_ABC123.bin','MOD_ABC123.bin')])
def test_pair_names(a, b):
    assert pair_key(a) == pair_key(b)


def test_suggestions_require_review(service, tmp_path):
    a, b = tmp_path/'ORI_X.bin', tmp_path/'MOD_X.bin'
    a.write_bytes(b'abc')
    b.write_bytes(b'abd')
    service.repo.import_folder(str(tmp_path))
    assert service.repo.suggest_pairs() == 1
    assert not service.repo.pairs()[0]['confirmed']
    assert service.analyze(str(a))['matches'][0]['known_changes'] == []


def test_integrity_and_search(service, pair):
    row = service.repo.files()[0]
    service.repo.update_metadata(row['id'], {'vehicle_make':'VW', 'vehicle_model':'Golf GTE', 'stage':'Stage 1+'})
    assert len(service.repo.files('GTE')) == 1
    assert len(service.repo.files('Stage 1+')) == 1
    assert service.repo.files('%') == []
    from pathlib import Path
    Path(row['filepath']).write_bytes(b'tampered')
    with pytest.raises(ValueError, match='Integriteitsfout'):
        service.repo.data(row['id'])


def test_learning_clusters_export(service, pair, tmp_path):
    pair_id, a, b = pair
    assert service.clusters()['clusters']
    assert LearningIndex(service.repo).nearest(a.read_bytes())[0]['histogram_distance'] == pytest.approx(0, abs=1e-12)
    report = service.diff(pair_id)
    first = export_report(report, tmp_path / 'reports')
    second = export_report(report, tmp_path / 'reports')
    assert first['json'] != second['json']
    from pathlib import Path
    assert json.loads(Path(first['json']).read_text(encoding='utf-8'))['original_sha256'] == report['original_sha256']
    assert '0x64' in Path(first['csv']).read_text(encoding='utf-8-sig')


def test_invalid_inputs(service, tmp_path):
    (tmp_path/'empty.bin').write_bytes(b'')
    (tmp_path/'bad.hex').write_text(':00')
    for name in ('empty.bin', 'bad.hex'):
        with pytest.raises(ValueError):
            service.repo.import_file(tmp_path/name)
    assert service.repo.import_folder(str(tmp_path))['errors']
    with pytest.raises(ValueError):
        service.repo.pair(999, 999)


def test_reset_moves_data_to_recoverable_backup(tmp_path):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    (data_dir / 'database.sqlite').write_bytes(b'old')
    backup = reset_data_dir(data_dir)
    assert backup.name.startswith('data_backup_')
    assert (backup / 'database.sqlite').read_bytes() == b'old'
    assert data_dir.exists() and not (data_dir / 'database.sqlite').exists()


def test_strategies(service, pair, tmp_path):
    pair_id, a, b = pair
    c = tmp_path/'stage2.bin'
    c.write_bytes(b.read_bytes() + b'additional')
    tuned_id = service.repo.import_file(c, 'tuned')
    other = service.repo.pair(service.repo.pairs()[0]['original_file_id'], tuned_id, True)
    result = service.strategies([pair_id, other])['comparisons'][0]
    assert result['same_original_sha256']
    assert len(result['overlap_regions']) == 2


def test_tuning_dna_requires_confirmed_pair_and_keeps_source(service, pair, tmp_path):
    pair_id, original, tuned = pair
    unconfirmed_tuned = tmp_path / 'unconfirmed_tuned.bin'
    unconfirmed_tuned.write_bytes(tuned.read_bytes())
    unconfirmed_id = service.repo.import_file(unconfirmed_tuned, 'tuned')
    unconfirmed_pair_id = service.repo.pair(service.repo.pairs()[0]['original_file_id'], unconfirmed_id, False)
    with pytest.raises(ValueError, match='bevestigd'):
        service.generate_tuning_dna(unconfirmed_pair_id)

    service.repo.confirm_pair(pair_id)
    dna = service.generate_tuning_dna(pair_id)
    service.generate_tuning_dna(pair_id)
    assert dna['source']['original_sha256'] == service.repo.file(service.repo.pairs()[0]['original_file_id'])['sha256']
    assert dna['regions'][0]['label_status'] == 'unknown'
    assert service.tuning_patterns()[0]['frequency'] == 1


def test_corrupt_tuned_does_not_hide_match(service, pair):
    from pathlib import Path
    tuned_id = service.repo.pairs()[0]['tuned_file_id']
    Path(service.repo.file(tuned_id)['filepath']).write_bytes(b'corrupt')
    report = service.analyze(str(pair[1]))
    assert report['matches'][0]['match_score'] == 100
    assert report['errors'][0]['pair_id'] == pair[0]


def test_nested_export_and_regional_score(service, pair, tmp_path):
    from pathlib import Path
    report = service.analyze(str(pair[1]))
    assert report['matches'][0]['known_changes'][0]['blocks'][0]['query_to_known_original_region_similarity'] == 100
    output = export_report(report, tmp_path/'out')
    assert '0x64' in Path(output['csv']).read_text(encoding='utf-8-sig')


def test_ols_project_import_inspection_and_folder_scan(service, tmp_path):
    project = tmp_path / 'Golf_stage1.ols'
    payload = b'OLS\x00project\x00SW:TEST_SW HW:TEST_HW\x00visible title\x00' + bytes(range(64))
    project.write_bytes(payload)
    project_id = service.repo.import_project(project)
    details = service.repo.inspect_project(project_id)
    assert details['format'].startswith('WinOLS OLS')
    assert details['hashes']['sha256'] == __import__('hashlib').sha256(payload).hexdigest()
    assert details['tagged_metadata'] == {'software_number': 'TEST_SW', 'hardware_number': 'TEST_HW'}
    assert service.repo.projects('Golf')[0]['id'] == project_id
    assert service.repo.import_folder(str(tmp_path))['projects'] == 1
    with pytest.raises(ValueError, match='raw .bin'):
        service.repo.import_file(project)


@pytest.mark.parametrize('name,kind', [
    ('Golf_orig.bin', 'original'), ('OEM_backup.bin', 'original'),
    ('Golf_stage 1.bin', 'tuned'), ('EDC17_stg2.bin', 'tuned'), ('file.bin', 'unknown'),
])
def test_extended_type_inference(name, kind, tmp_path):
    from app.database.repository import infer_type
    assert infer_type(tmp_path / name) == kind


def test_bulk_reclassification_preserves_source_and_enables_pairing(service, tmp_path):
    original, tuned = tmp_path / 'A.bin', tmp_path / 'B.bin'
    original.write_bytes(b'original data')
    tuned.write_bytes(b'tuned data')
    original_id, tuned_id = service.repo.import_file(original), service.repo.import_file(tuned)
    assert service.repo.reclassify_files([original_id], 'original') == 1
    assert service.repo.reclassify_files([tuned_id], 'tuned') == 1
    assert service.repo.file(original_id)['filepath'].endswith('originals\\' + service.repo.file(original_id)['sha256'] + '.bin')
    assert original.read_bytes() == b'original data'
    pair_id = service.repo.pair(original_id, tuned_id, True)
    with pytest.raises(ValueError, match='gekoppeld'):
        service.repo.reclassify_files([original_id], 'unknown')
    assert pair_id


def test_auto_classifies_numeric_duplicate_from_exact_hash(service, tmp_path):
    original, numbered = tmp_path / 'ORI_known.bin', tmp_path / '000123.bin'
    original.write_bytes(b'same ECU content')
    numbered.write_bytes(b'same ECU content')
    known_id = service.repo.import_file(original)
    unknown_id = service.repo.import_file(numbered, 'unknown')
    assert service.repo.file(known_id)['file_type'] == 'original'
    assert service.repo.file(unknown_id)['file_type'] == 'unknown'
    result = service.repo.auto_classify_exact_duplicates()
    assert result['updated'] == [{'id': unknown_id, 'filename': '000123.bin', 'kind': 'original', 'reason': 'exacte SHA256-overeenkomst'}]
    assert service.repo.file(unknown_id)['file_type'] == 'original'


def test_evidence_classifier_keeps_ambiguous_near_match_unknown(service, tmp_path):
    original = tmp_path / 'ORI_base.bin'
    tuned = tmp_path / 'MOD_base.bin'
    unknown = tmp_path / '000999.bin'
    original.write_bytes(b'A' * 1000)
    tuned.write_bytes(b'A' * 990 + b'B' * 10)
    unknown.write_bytes(b'A' * 995 + b'B' * 5)
    service.repo.import_file(original, 'original')
    service.repo.import_file(tuned, 'tuned')
    unknown_id = service.repo.import_file(unknown, 'unknown')

    result = service.repo.auto_classify_evidence()

    assert any(item['id'] == unknown_id for item in result['review'])
    assert service.repo.file(unknown_id)['file_type'] == 'unknown'


def test_ols_visible_project_name_suggests_type(service, tmp_path):
    project = tmp_path / '12345.ols'
    project.write_bytes(b'OLS\x00VW Golf Stage 1 project\x00')
    project_id = service.repo.import_project(project)
    assert service.repo.projects()[0]['suggested_type'] == 'tuned'
    assert service.repo.inspect_project(project_id)['suggestion_reason'] == 'expliciet tuninglabel gevonden'
    assert any(item['confidence'] == 100.0 for item in service.repo.project_objects(project_id))


def test_ols_inventory_keeps_numeric_objects_unknown(service, tmp_path):
    project = tmp_path / '12345.ols'
    project.write_bytes(
        b'OLS' + bytes([0]) + b'123456' + bytes([0]) +
        b'Stage 1 project' + bytes([0])
    )

    project_id = service.repo.import_project(project)
    objects = service.repo.project_objects(project_id)

    assert objects[0]['object_name_raw'] == '123456'
    assert objects[0]['role'] == 'unknown'
    assert objects[0]['detection_method'] == 'no_role_evidence'
    assert any(item['role'] == 'tuned' for item in objects)


def test_ols_object_review_is_explicit_and_auditable(service, tmp_path):
    project = tmp_path / 'opaque.ols'
    project.write_bytes(b'OLS' + bytes([0]) + b'123456' + bytes([0]))
    project_id = service.repo.import_project(project)
    object_id = service.repo.project_objects(project_id)[0]['id']

    assert service.repo.ols_unknown_objects(project_id)[0]['id'] == object_id
    reviewed = service.repo.review_ols_object(object_id, 'original', 'Gecontroleerd in WinOLS', 'technician')

    assert reviewed['role'] == 'original'
    assert reviewed['detection_method'] == 'human_review'
    assert reviewed['note'] == 'Gecontroleerd in WinOLS'
    assert service.repo.ols_unknown_objects(project_id) == []


def test_software_family_candidates_are_scoped_to_ecu(service, tmp_path):
    for index, ecu in enumerate(('MED17.1', 'EDC17.1')):
        for copy in range(2):
            path = tmp_path / f'{index}_{copy}.bin'
            path.write_bytes(f'ECU:{ecu} SW:SAME '.encode() + bytes([65 + index]) * 100)
            service.repo.import_file(path, 'original')

    proposals = [item for item in service.repo.propose_families()['proposals']
                 if item['type'] == 'software_family']

    assert {item['ecu_family'] for item in proposals} == {'MED17.1', 'EDC17.1'}


def test_ols_review_survives_reimport(service, tmp_path):
    project = tmp_path / 'opaque.ols'
    project.write_bytes(b'OLS' + bytes([0]) + b'123456' + bytes([0]))
    project_id = service.repo.import_project(project)
    object_id = service.repo.project_objects(project_id)[0]['id']
    service.repo.review_ols_object(object_id, 'original', 'verified', 'tester')

    assert service.repo.import_project(project) == project_id
    reviewed = service.repo.project_objects(project_id)[0]
    assert reviewed['id'] == object_id
    assert reviewed['role'] == 'original'
    assert reviewed['detection_method'] == 'human_review'


def test_low_base_match_suppresses_known_change_regions(service, tmp_path):
    original = tmp_path / 'ORI_A4.bin'
    tuned = tmp_path / 'MOD_A4.bin'
    unrelated = tmp_path / 'A5_tuned.bin'
    original.write_bytes(b'A' * 4096)
    tuned.write_bytes(b'A' * 2048 + b'B' * 32 + b'A' * 2016)
    unrelated.write_bytes(b'Z' * 4096)
    original_id = service.repo.import_file(original)
    tuned_id = service.repo.import_file(tuned)
    service.repo.pair(original_id, tuned_id, True)
    report = service.analyze(str(unrelated))
    assert report['matches'][0]['compatibility_status'] == 'incompatible_base'
    assert report['matches'][0]['compatibility_confidence'] == 0
    assert report['matches'][0]['known_changes'] == []
    assert 'Niet getoond' in report['matches'][0]['known_changes_suppressed']
    assert report['outlier']


def test_v2_migration_candidates_approval_and_signatures(service, tmp_path):
    a, b, c = tmp_path / 'a.bin', tmp_path / 'b.bin', tmp_path / 'c.bin'
    content = b'\x00ECU:MED17.1.21 SW:04E906016ABC\x00' + b'A' * 512
    a.write_bytes(content)
    b.write_bytes(content)
    c.write_bytes(content)
    first = service.repo.import_file(a, 'original')
    second = service.repo.import_file(b, 'original')
    third = service.repo.import_file(c, 'original')
    tables = {row['name'] for row in service.repo.db.rows("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'ecu_families', 'software_families', 'recognition_results', 'knowledge_candidates'}.issubset(tables)
    proposals = service.repo.propose_families()['proposals']
    ecu = next(item for item in proposals if item['type'] == 'ecu_family')
    candidate = next(item for item in service.repo.candidates() if item['candidate_type'] == 'ecu_family' and item['subject_key'] == ecu['name'])
    family_id = service.repo.approve_candidate(candidate['id'])['ecu_family_id']
    assert service.repo.ecu_families()[0]['file_count'] >= 2
    signature_candidates = service.repo.discover_ecu_signature_candidates(family_id)
    assert signature_candidates['candidates']
    signature_candidate = next(item for item in service.repo.candidates() if item['candidate_type'] == 'ecu_signature')
    signature_id = service.repo.approve_candidate(signature_candidate['id'])['ecu_signature_id']
    assert signature_id
    hierarchy, details = service.repo.hierarchical_originals(service.repo.recognition(first))
    assert details['stage'] == 'verified_ecu_family'
    assert {item['id'] for item in hierarchy} == {first, second, third}
