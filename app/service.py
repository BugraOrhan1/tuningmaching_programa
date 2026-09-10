"""Shared application operations for desktop, CLI and local API."""
import json
from pathlib import Path
import hashlib
from app.database.repository import Repository
from app.analysis.diff_engine import diff_blocks, hex_rows
from app.analysis.clustering import feature, cluster_changes, compare_strategies
from app.matching.matcher import find_matches
from app.analysis.binary_reader import read_binary
from app.analysis.similarity import compare
from app.analysis.recognition import recognize
from app.analysis.ecu_fingerprint import ecu_family_fingerprint
from app.analysis.alignment import align_regions
from app.intelligence import ServiceV3Mixin
from app.analysis.tuning_region import build_regions


class Service(ServiceV3Mixin):
    def __init__(self, config: dict):
        self.repo = Repository(config)

    def analyze(self, path: str, progress=None) -> dict:
        query = read_binary(path, self.repo.config['max_file_mb'])
        report = find_matches(self.repo, path, progress, query_data=query)
        for match in report['matches']:
            match['known_changes'] = []
            if match['compatibility_status'] == 'incompatible_base':
                match['known_changes_suppressed'] = (
                    'Niet getoond: de softwarebasis komt minder dan 60% overeen. '
                    'Een gelijk bytegebied is geen bewijs dat de tuning naar deze BIN past.')
                continue
            for pair in match['pairs']:
                if not pair['confirmed']:
                    continue
                try:
                    known = self.diff(pair['id'])
                    original = self.repo.data(pair['original_file_id'])
                    for block in known['blocks']:
                        start, end = block['start_offset'], block['end_offset']
                        regional = compare(query[start:end], original[start:end], {}, {})
                        block['query_to_known_original_region_similarity'] = regional['match_score']
                        block['compatibility_confidence'] = match['compatibility_confidence']
                    match['known_changes'].append(known)
                except (OSError, ValueError) as exc:
                    report['errors'].append({'pair_id': pair['id'], 'error': str(exc)})
        return report

    def identify(self, path: str) -> dict:
        data = read_binary(path, self.repo.config['max_file_mb'])
        return {"filename": str(path), "file_size": len(data), "identification": recognize(data),
                "ecu_family_fingerprint": ecu_family_fingerprint(data)}

    def align_files(self, source_file_id: int, target_file_id: int) -> dict:
        source, target = self.repo.data(source_file_id), self.repo.data(target_file_id)
        regions = align_regions(source, target)
        with self.repo.db.connect() as db:
            for region in regions:
                db.execute("INSERT INTO calibration_alignments(source_file_id,target_file_id,source_start,source_end,target_start,target_end,confidence,method) VALUES (?,?,?,?,?,?,?,?)",
                           (source_file_id, target_file_id, region['source_start'], region['source_end'], region['target_start'], region['target_end'], region['confidence'], region['method']))
        return {"source_file_id": source_file_id, "target_file_id": target_file_id, "regions": regions,
                "note": "Uitlijning toont alleen exact gedeelde structuur en verandert geen BIN."}

    def diff(self, pair_id: int) -> dict:
        pairs = [p for p in self.repo.pairs() if p['id'] == pair_id]
        if not pairs:
            raise ValueError("Onbekend pair-ID")
        pair = pairs[0]
        a, b = self.repo.data(pair['original_file_id']), self.repo.data(pair['tuned_file_id'])
        blocks = diff_blocks(a, b, self.repo.config['diff_merge_gap'])
        with self.repo.db.connect() as db:
            db.execute("DELETE FROM diffs WHERE pair_id=?", (pair_id,))
            for block in blocks:
                cursor = db.execute(f"INSERT INTO diffs (pair_id,{','.join(block)}) VALUES ({','.join('?' for _ in range(len(block)+1))})", (pair_id, *block.values()))
                db.execute("INSERT INTO diff_features(diff_id,feature_type,feature_data,confidence) VALUES (?,?,?,?)",
                           (cursor.lastrowid, 'relative-region-v1', json.dumps(feature(block, len(a))), 0))
        metadata = self.repo.file(pair['original_file_id'])
        regions = build_regions(a, b, blocks, stage=metadata.get('stage'), file_metadata=metadata)
        self.repo.replace_pair_regions(pair_id, regions)
        return {"pair": pair, "original_sha256": self.repo.file(pair['original_file_id'])['sha256'],
                "tuned_sha256": self.repo.file(pair['tuned_file_id'])['sha256'],
                "original_size": len(a), "tuned_size": len(b), "blocks": blocks,
                "changed_bytes": sum(x['changed_bytes'] for x in blocks),
                "offset_convention": "[start_offset, end_offset), end exclusive",
                "note": "Bekende wijzigingen uit dit paar; niet gevalideerd voor toepassing op een andere BIN."}

    def hex(self, pair_id: int, start: int = 0, count: int = 256) -> list[dict]:
        pair = next((p for p in self.repo.pairs() if p['id'] == pair_id), None)
        if pair is None or start < 0 or not 1 <= count <= 4096:
            raise ValueError("Ongeldige pair, offset of paginagrootte")
        return hex_rows(self.repo.data(pair['original_file_id']), self.repo.data(pair['tuned_file_id']), start, count)

    def clusters(self, progress=None) -> dict:
        records = []
        pairs = [p for p in self.repo.pairs() if p['confirmed']]
        for index, pair in enumerate(pairs):
            report = self.diff(pair['id'])
            for block in report['blocks']:
                records.append({"pair_id": pair['id'], **block, "features": feature(block, report['original_size'])})
            if progress:
                progress(f"Clustering {index+1}/{len(pairs)}")
        return {"clusters": cluster_changes(records), "confirmed_pairs": len(pairs)}

    def strategies(self, pair_ids: list[int]) -> dict:
        if len(set(pair_ids)) < 2:
            raise ValueError("Selecteer minimaal twee verschillende paren")
        return compare_strategies([self.diff(i) for i in dict.fromkeys(pair_ids)])

    def generate_tuning_dna(self, pair_id: int) -> dict:
        """Create candidate, traceable change knowledge from a confirmed pair."""
        pair = next((item for item in self.repo.pairs() if item['id'] == pair_id), None)
        if pair is None:
            raise ValueError('Onbekend pair-ID')
        if not pair['confirmed']:
            raise ValueError('Tuning DNA vereist een bevestigd Original → Tuned-paar')
        report = self.diff(pair_id)
        stored_regions = self.repo.regions_for_pair(pair_id)
        metadata = self.repo.file(pair['original_file_id'])
        original = self.repo.data(pair['original_file_id'])
        tuned = self.repo.data(pair['tuned_file_id'])
        regions = []
        for block in report['blocks']:
            start, end = block['start_offset'], block['end_offset']
            context_start, context_end = max(0, start - 32), min(len(original), end + 32)
            regions.append({
                **block,
                'relative_start': round(start / max(len(original), 1), 8),
                'relative_end': round(end / max(len(original), 1), 8),
                'original_context_hash': hashlib.sha256(original[context_start:context_end]).hexdigest(),
                'tuned_context_hash': hashlib.sha256(tuned[context_start:context_end]).hexdigest(),
                'label_status': 'unknown',
            })
        payload = {
            'pair_id': pair_id,
            'source': {'original_file_id': pair['original_file_id'], 'tuned_file_id': pair['tuned_file_id'],
                       'original_sha256': report['original_sha256'], 'tuned_sha256': report['tuned_sha256'],
                       'ecu_family': metadata.get('ecu_family'), 'hardware_number': metadata.get('hardware_number'),
                       'software_number': metadata.get('software_number'),
                       'calibration_number': metadata.get('calibration_number'),
                       'stage': metadata.get('stage'), 'project': metadata.get('project')},
            'regions': regions,
            'region_ids': [row['id'] for row in stored_regions],
            'note': 'Structurele diff-evidence; geen mapnaam of tuningfunctie gegokt.',
        }
        confidence = round(min(99.0, max(20.0, float(pair['confidence']))), 2)
        with self.repo.db.connect() as db:
            db.execute('''INSERT INTO tuning_dna(pair_id,original_file_id,tuned_file_id,payload,confidence)
                          VALUES (?,?,?,?,?) ON CONFLICT(pair_id) DO UPDATE SET payload=excluded.payload,
                          confidence=excluded.confidence, updated_at=CURRENT_TIMESTAMP''',
                       (pair_id, pair['original_file_id'], pair['tuned_file_id'], json.dumps(payload, ensure_ascii=False), confidence))
            for region in regions:
                pattern_key = json.dumps({'relative_start': round(region['relative_start'], 3),
                                          'length': region['length'],
                                          'density': round(region['change_percentage'], 1)}, sort_keys=True)
                existing = db.execute("SELECT payload FROM tuning_patterns WHERE pattern_key=?",
                                      (pattern_key,)).fetchone()
                if existing:
                    pattern_payload = json.loads(existing[0])
                    source_pair_ids = set(pattern_payload.get('source_pair_ids', []))
                    source_pair_ids.add(pair_id)
                    pattern_payload['source_pair_ids'] = sorted(source_pair_ids)
                    frequency = len(source_pair_ids)
                    db.execute('''UPDATE tuning_patterns SET payload=?, frequency=?,
                                  confidence=?, updated_at=CURRENT_TIMESTAMP WHERE pattern_key=?''',
                               (json.dumps(pattern_payload, ensure_ascii=False), frequency,
                                min(99.0, 55.0 + frequency * 4), pattern_key))
                else:
                    pattern_payload = {'pattern_key': pattern_key, 'source_pair_ids': [pair_id],
                                       'region': {key: region[key] for key in ('relative_start', 'length', 'change_percentage', 'original_hash', 'tuned_hash')}}
                    db.execute('''INSERT INTO tuning_patterns(pattern_key,payload,frequency,confidence)
                                  VALUES (?,?,1,?)''',
                               (pattern_key, json.dumps(pattern_payload, ensure_ascii=False), 59.0))
        return {**payload, 'confidence': confidence, 'status': 'candidate'}

    def tuning_dna(self, status: str | None = None) -> list[dict]:
        query = 'SELECT * FROM tuning_dna'
        args = ()
        if status is not None:
            if status not in {'candidate', 'verified', 'rejected'}:
                raise ValueError('Ongeldige Tuning DNA-status')
            query += ' WHERE status=?'
            args = (status,)
        else:
            query += " WHERE status <> 'rejected'"
        query += ' ORDER BY confidence DESC, id DESC'
        rows = self.repo.db.rows(query, args)
        for row in rows:
            row['payload'] = json.loads(row['payload'])
        return rows

    def tuning_patterns(self, status: str | None = None) -> list[dict]:
        query = 'SELECT * FROM tuning_patterns'
        args = ()
        if status is not None:
            query += ' WHERE status=?'
            args = (status,)
        else:
            query += " WHERE status <> 'rejected'"
        query += ' ORDER BY frequency DESC, confidence DESC, id DESC'
        rows = self.repo.db.rows(query, args)
        for row in rows:
            row['payload'] = json.loads(row['payload'])
        return rows

    def auto_process_ols(self, path: str) -> dict:
        """One-call OLS workflow: import, extract, classify, pair and learn.

        Every step stays evidence-based: binaries come from proven record
        boundaries, roles from explicit WinOLS version labels and Tuning DNA
        remains candidate knowledge that never modifies a BIN.
        """
        project_id = self.repo.import_project(Path(path))
        versions = self.repo.ols_versions(project_id)
        pairs = self.repo.suggest_ols_project_pairs(project_id)
        dna = []
        for pair in pairs:
            if pair.get('confirmed') and pair.get('pair_id'):
                try:
                    report = self.generate_tuning_dna(pair['pair_id'])
                    dna.append({'pair_id': pair['pair_id'], 'regions': len(report['regions']),
                                'confidence': report['confidence']})
                except (ValueError, OSError) as exc:
                    pairs[pairs.index(pair)]['dna_error'] = str(exc)
        files = [row for row in self.repo.files() if str(row.get('source_path', '')).startswith('ols://')]
        return {
            'project_id': project_id,
            'versions': [{'version_index': v['version_index'], 'name': v['version_name'], 'role': v['role'],
                          'role_confidence': v['role_confidence'], 'complete': bool(v['complete']),
                          'file_id': v['file_id'], 'sha256': v['binary_sha256'],
                          'relation_type': v['relation_type']} for v in versions],
            'files_extracted': len(files),
            'pairs': pairs,
            'tuning_dna': dna,
            'note': 'Binaries zijn gextraheerd op bewezen grenzen; rollen komen uit expliciete '
                    'WinOLS-versielabels. Geen enkele BIN is gewijzigd.',
        }

    def generate_tune_candidate(self, target_file_id: int, threshold: float = 70.0) -> dict:
        """Generate a candidate tune for a matched original when evidence allows.

        The target file is never modified. Changed regions of the best
        confirmed Original → Tuned pair are copied onto a fresh candidate file
        only where the target byte-matches the known original almost exactly.
        The output is an unverified candidate: checksums must be corrected and
        verified before such a file is ever written to an ECU.
        """
        if not 50 <= threshold <= 100:
            raise ValueError('Drempel moet tussen 50 en 100 liggen')
        target = self.repo.file(target_file_id)
        query = self.repo.data(target_file_id)
        report = self.analyze(target['filepath'])
        matches = [match for match in report['matches']
                   if match['match_score'] >= threshold and match['compatibility_status'] != 'incompatible_base']
        if not matches:
            best = report['matches'][0] if report['matches'] else None
            return {'status': 'no_match_above_threshold', 'threshold': threshold,
                    'target_file_id': target_file_id,
                    'best_score': best['match_score'] if best else None,
                    'note': 'Geen bekende original met voldoende bewezen overeenkomst; '
                            'er wordt niets gegenereerd.'}
        best = matches[0]
        confirmed = [pair for pair in best['pairs'] if pair['confirmed']]
        if not confirmed:
            return {'status': 'no_confirmed_pair', 'threshold': threshold,
                    'target_file_id': target_file_id, 'match_score': best['match_score'],
                    'filename': best['filename'],
                    'note': 'Match gevonden maar het paar is niet bevestigd; bevestig het paar eerst.'}
        result = bytearray(query)
        applied, skipped = [], []
        for pair in confirmed:
            known = self.diff(pair['id'])
            original = self.repo.data(pair['original_file_id'])
            tuned = self.repo.data(pair['tuned_file_id'])
            if len(tuned) != len(query) or len(original) != len(query):
                skipped.append({'pair_id': pair['id'], 'reason': 'bestandsgrootte verschilt van target'})
                continue
            for block in known['blocks']:
                start, end = block['start_offset'], block['end_offset']
                if end > len(result):
                    skipped.append({'pair_id': pair['id'], 'start_offset': start, 'end_offset': end,
                                    'reason': 'regio valt buiten target'})
                    continue
                regional = compare(query[start:end], original[start:end], {}, {})['match_score']
                if regional >= 98.0:
                    result[start:end] = tuned[start:end]
                    applied.append({**block, 'region_similarity': round(regional, 3),
                                    'pair_id': pair['id']})
                else:
                    skipped.append({'pair_id': pair['id'], 'start_offset': start, 'end_offset': end,
                                    'reason': f'target wijkt af van bekende original in deze regio '
                                              f'(similarity {regional:.2f}%)'})
        if not applied:
            return {'status': 'no_regions_applied', 'threshold': threshold, 'skipped': skipped,
                    'match_score': best['match_score'],
                    'note': 'Geen enkele regio voldeed aan het regionaal-bewijs; niets gegenereerd.'}
        output = bytes(result)
        output_hashes = hashlib.sha256(output).hexdigest()
        candidate_dir = self.repo.root / 'reports' / 'candidates'
        candidate_dir.mkdir(parents=True, exist_ok=True)
        output_path = candidate_dir / (output_hashes + '.bin')
        try:
            with output_path.open('xb') as stream:
                stream.write(output)
        except FileExistsError:
            pass  # identieke kandidaat bestaat al; sha256 is de bestandsnaam
        payload = {'target': {'id': target_file_id, 'filename': target['filename'], 'sha256': target['sha256']},
                   'match': {'file_id': best['file_id'], 'filename': best['filename'],
                             'match_score': best['match_score']},
                   'applied_regions': applied, 'skipped_regions': skipped,
                   'warnings': ['KANDIDAAT: niet getest en niet gecontroleerd.',
                                'ECU-checksums zijn NIET gecorrigeerd.',
                                'Controleer de diff in WinOLS vóór enig gebruik.']}
        candidate_id = self.repo.add_tune_candidate(
            target_file_id, confirmed[0]['id'], threshold, best['match_score'],
            len(applied), len(skipped), payload, str(output_path),
            {'sha256': output_hashes}, len(output))
        return {'status': 'candidate_generated', 'candidate_id': candidate_id,
                'output_path': str(output_path), 'sha256': output_hashes, 'size': len(output),
                'applied_regions': applied, 'skipped_regions': skipped,
                'match_score': best['match_score'], 'threshold': threshold,
                'pair_id': confirmed[0]['id'], 'warnings': payload['warnings']}

    def tune_candidates(self) -> list[dict]:
        return self.repo.tune_candidates()
