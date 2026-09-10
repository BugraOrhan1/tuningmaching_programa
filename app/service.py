"""Shared application operations for desktop, CLI and local API."""
import json
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


class Service:
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
                       'original_sha256': report['original_sha256'], 'tuned_sha256': report['tuned_sha256']},
            'regions': regions,
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
        query += ' ORDER BY frequency DESC, confidence DESC, id DESC'
        rows = self.repo.db.rows(query, args)
        for row in rows:
            row['payload'] = json.loads(row['payload'])
        return rows
