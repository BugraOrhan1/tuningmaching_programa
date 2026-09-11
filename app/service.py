"""Shared application operations for desktop, CLI and local API."""
import json
import os
import shutil
import sqlite3
from datetime import datetime
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
from app.learning.evaluation import evaluate_confidence


class Service(ServiceV3Mixin):
    def __init__(self, config: dict):
        self.repo = Repository(config)
        from app.library import LibraryEngine
        from app.knowledge_model import KnowledgeModelEngine
        self.library = LibraryEngine(self.repo, config, service=self)
        self.km = KnowledgeModelEngine(self)

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
        identity_links = self.calibration_identity_links(pair['original_file_id'], regions)
        for region in regions:
            region['calibration_identity_candidates'] = identity_links.get(region['start_offset'], [])
        payload = {
            'pair_id': pair_id,
            'source': {'original_file_id': pair['original_file_id'], 'tuned_file_id': pair['tuned_file_id'],
                       'original_sha256': report['original_sha256'], 'tuned_sha256': report['tuned_sha256'],
                       'ecu_family': metadata.get('ecu_family'), 'hardware_number': metadata.get('hardware_number'),
                       'software_number': metadata.get('software_number'),
                       'calibration_number': metadata.get('calibration_number'),
                       'stage': metadata.get('stage'), 'project': metadata.get('project')},
            'regions': regions,
            'calibration_identity_ids': sorted({item['identity_id'] for values in identity_links.values()
                                                for item in values}),
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

    def evaluate_confidence(self, records: list[dict], threshold: float = 70.0) -> dict:
        metrics = evaluate_confidence(records, threshold)
        metrics["evaluation_id"] = self.repo.save_confidence_evaluation(metrics)
        return metrics

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

    # ------------------------------------------------------------------
    # Job-manager (§51): pauzeren/hervatten/annuleren van achtergrondtaken
    # ------------------------------------------------------------------
    def job(self, run_id: int) -> dict | None:
        return self.repo.run(run_id)

    def job_pause(self, run_id: int) -> dict:
        with self.repo.db.connect() as db:
            cursor = db.execute("""UPDATE analysis_runs SET status='paused',
                updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='running'""",
                (run_id,))
            if cursor.rowcount == 0:
                raise ValueError("Taak is niet actief (alleen running taken kunnen gepauzeerd)")
        return self.job(run_id)

    def job_resume(self, run_id: int, progress=None) -> dict:
        row = self.job(run_id)
        if row is None:
            raise ValueError("Onbekende taak")
        if row["status"] not in ("paused", "interrupted"):
            raise ValueError("Alleen gepauzeerde/onderbroken taken kunnen hervatten")
        if row["run_type"] == "library_analysis":
            return self.library.analyze_pending(resume=True, progress=progress)
        if row["run_type"] == "pattern_rebuild":
            return self.rebuild_patterns(resume=True, progress=progress)
        raise ValueError(f"Taaktype {row['run_type']} kent geen hervat-padhérecke")

    def job_cancel(self, run_id: int) -> dict:
        row = self.job(run_id)
        if row is None:
            raise ValueError("Onbekende taak")
        if row["status"] not in ("running", "paused"):
            raise ValueError("Alleen running/paused taken kunnen geannuleerd")
        # gepauzeerde taken zijn meteen definitief geannuleerd; een draaiende taak
        # leest 'cancel_requested' tussen batches en sluit zichzelf netjes af
        final = row["status"] == "paused"
        with self.repo.db.connect() as db:
            db.execute("""UPDATE analysis_runs SET status=?,
                updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                       ("cancelled" if final else "cancel_requested", run_id))
        return self.job(run_id)

    # ------------------------------------------------------------------
    # Backup/restore/health (§64): database + kennis + audit; NOOIT de bronbibliotheek
    # ------------------------------------------------------------------
    def backup(self, target_dir: str | None = None) -> dict:
        base = Path(target_dir) if target_dir else self.repo.root / "backups"
        base.mkdir(parents=True, exist_ok=True)
        folder = base / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        folder.mkdir()
        db_target = folder / "tuning.db"
        source = sqlite3.connect(str(self.repo.db.path))
        destination = sqlite3.connect(str(db_target))
        with destination:
            source.backup(destination)
        source.close()
        destination.close()
        for name in ("config.json",):
            candidate = self.repo.root / name
            if candidate.exists():
                shutil.copy2(candidate, folder / name)
        db_digest = hashlib.sha256(db_target.read_bytes()).hexdigest()
        counts = {table: self.repo.db.rows(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]
                  for table in ("files", "file_pairs", "tuning_patterns",
                                "calibration_identities", "audit_log")}
        manifest = {"created_at": datetime.now().isoformat(), "schema_user_version": 10,
                    "database_sha256": db_digest, "row_counts": counts}
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2))
        return {"backup_path": str(folder), "manifest": manifest}

    def restore(self, backup_path: str) -> dict:
        folder = Path(backup_path)
        if not (folder / "manifest.json").exists() or not (folder / "tuning.db").exists():
            raise ValueError("Ongeldige backup: manifest.json of tuning.db ontbreekt")
        manifest = json.loads((folder / "manifest.json").read_text())
        digest = hashlib.sha256((folder / "tuning.db").read_bytes()).hexdigest()
        if digest != manifest.get("database_sha256"):
            raise ValueError("Backup geverifieerd tegen manifest: hash komt NIET overeen")
        safety = self.backup()
        temporary = self.repo.db.path.with_suffix(".restore.tmp")
        shutil.copy2(folder / "tuning.db", temporary)
        os.replace(temporary, self.repo.db.path)
        sanity = self.repo.db.rows("SELECT COUNT(*) AS n FROM files")[0]["n"]
        return {"restored_from": str(folder), "safety_backup": safety["backup_path"],
                "manifest": manifest, "files_after_restore": sanity}

    def health_check(self) -> dict:
        with self.repo.db.connect() as db:
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_key_issues = len(db.execute("PRAGMA foreign_key_check").fetchall())
        counts = {table: self.repo.db.rows(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]
                  for table in ("files", "file_pairs", "tuning_regions", "tuning_patterns",
                                "calibration_identities", "library_roots",
                                "file_locations", "content_objects", "audit_log")}
        orphans = {
            "locations_without_root": self.repo.db.rows(
                "SELECT COUNT(*) AS n FROM file_locations WHERE root_id NOT IN (SELECT id FROM library_roots)")[0]["n"],
            "locations_without_content": self.repo.db.rows(
                "SELECT COUNT(*) AS n FROM file_locations WHERE content_id IS NULL")[0]["n"],
            "regions_without_pair": self.repo.db.rows(
                "SELECT COUNT(*) AS n FROM tuning_regions WHERE pair_id NOT IN (SELECT id FROM file_pairs)")[0]["n"],
        }
        offline_roots = self.repo.db.rows(
            "SELECT COUNT(*) AS n FROM library_roots WHERE status='OFFLINE'")[0]["n"]
        warnings = [name for name, value in orphans.items() if value] + (
            ["offline_roots"] if offline_roots else [])
        return {"status": "OK" if not warnings and integrity == "ok" and not foreign_key_issues
                else "WARNINGS", "integrity": integrity,
                "foreign_key_issues": foreign_key_issues, "row_counts": counts,
                "orphans": orphans, "offline_roots": offline_roots,
                "database_bytes": self.repo.db.path.stat().st_size}

    # ------------------------------------------------------------------
    # New BIN over de library (§40): multi-stage retrieval
    # ------------------------------------------------------------------
    def new_bin_library_report(self, path: str, threshold: float = 70.0) -> dict:
        """Multi-stage New BIN: goedkope filters eerst, dure vergelijking alleen
        op de shortlist. Stage 1 (exacte SHA256) hergebruikt bestaande kennis
        zonder heranalyse (§4/§10)."""
        query = read_binary(path, self.repo.config["max_file_mb"])
        digest = hashlib.sha256(query).hexdigest()
        stages = [{"stage": 1, "name": "exact_sha256", "hits": 0}]
        exact = self.repo.db.rows(
            "SELECT id, sha256, size, file_type, analysis_state FROM content_objects WHERE sha256=?",
            (digest,))
        stages[0]["hits"] = len(exact)
        if exact:
            link = self.library.analysis_link(exact[0]["id"])
            locations = self.library.content_locations(exact[0]["id"])
            return {"stages": stages, "library_hit": exact[0], "locations": locations,
                    "analysis_link": link, "filename": Path(path).name,
                    "note": "Content exact bekend: bestaande kennis hergebruikt, "
                            "geen dubbele deep analysis."}
        size_hits = self.repo.db.rows(
            "SELECT COUNT(DISTINCT c.id) AS n FROM content_objects c WHERE c.size=?",
            (len(query),))
        stages.append({"stage": 2, "name": "size_filter", "hits": size_hits[0]["n"]})
        file_id = self.repo.import_file(Path(path), kind="unknown")
        report = self.new_bin_report(file_id, threshold)
        report["stages"] = stages + [
            {"stage": 3, "name": "fingerprint_prefilter",
             "hits": report.get("related_originals") and len(report["related_originals"]) or 0},
            {"stage": 4, "name": "full_comparison_shortlist",
             "hits": len(report.get("related_originals", []))},
            {"stage": 5, "name": "knowledge_integration", "hits": 1}]
        report["library_file_id"] = file_id
        return report

    # ------------------------------------------------------------------
    # Audit (§63)
    # ------------------------------------------------------------------
    def audit(self, action: str, subject_type: str, subject_id, before=None,
              after=None, reason: str = "", actor: str = "technician") -> None:
        self.repo.audit(action, subject_type, subject_id, actor=actor,
                        before=before, after=after, reason=reason)

    def audit_log(self, limit: int = 200, subject_type: str | None = None) -> list[dict]:
        return self.repo.audit_log(limit=limit, subject_type=subject_type)

    # ------------------------------------------------------------------
    # V6: kennismodel (ECU Image Identity, families, lineage, negatieven)
    # ------------------------------------------------------------------
    def build_knowledge_model(self) -> dict:
        images = self.km.build_ecu_image_identities()
        families = self.km.build_project_families()
        lineage = self.km.build_software_lineage()
        return {"images": images, "families": families, "lineage": lineage}

    def register_negative_match(self, subject_type: str, a, b, reason: str = "",
                                reviewer: str | None = None) -> dict:
        """Technicus: A ≠ B. Permanent negatief bewijs (§8); toekomstige
        rebuilds mogen dit voorstel niet opnieuw doen."""
        return self.km.register_negative(subject_type, a, b, reason=reason,
                                         reviewer=reviewer)

    def negatives(self, subject_type: str | None = None) -> list[dict]:
        return self.km.negatives(subject_type)

    def evaluate_golden(self, save: bool = True) -> dict:
        return self.km.evaluate_golden(save=save)

    def snapshot_knowledge(self) -> dict:
        return self.km.snapshot_knowledge()

    def diff_knowledge_snapshots(self, before: dict, after: dict) -> dict:
        return self.km.diff_knowledge_snapshots(before, after)

    # ------------------------------------------------------------------
    # V6: "Why this match?" (§15) — alle componenten + bewijsaantallen
    # ------------------------------------------------------------------
    def explain_new_bin(self, file_id: int, threshold: float = 70.0) -> dict:
        """Per scorecomponent: waarde, gewicht, bijdrage, bewijsaantallen en
        negatieve aftrekken. Geen zwarte doos: dit is het volledige WHY-rapport."""
        report = self.new_bin_report(file_id, threshold)
        components = report["score_components"]
        weights = report.get("score_weights", {})
        identification = report.get("identification", {})
        evidence_counts = {
            "binary_similarity": len(report.get("related_originals", [])),
            "structural_similarity": len(report.get("related_originals", [])),
            "ecu_confidence": len(identification.get("ecu", [])),
            "hardware_confidence": len(identification.get("hardware", [])),
            "software_confidence": len(identification.get("software", [])),
            "calibration_confidence": len(identification.get("calibration", [])),
            "calibration_identity_confidence": len(report.get("calibration_identity_matches", [])),
            "tuning_pattern_confidence": len(report.get("tuning_dna_matches", [])),
            "cross_software_confidence": 0,
            "evidence_strength": report.get("related_projects", 0),
            "contradiction_penalty": report.get("evidence_summary", {}).get("contradictions", 0),
            "context_alignment": len(report.get("tuning_dna_matches", [])),
        }
        explanation = []
        for name, value in components.items():
            weight = weights.get(name, 0.0)
            explanation.append({
                "component": name, "value": round(value, 2), "weight": round(weight, 3),
                "contribution": round(value * weight, 2),
                "evidence_count": evidence_counts.get(name, 0),
                "role": "negative" if "contradiction" in name or "penalty" in name
                        else ("unused" if weight == 0 else "positive"),
            })
        explanation.sort(key=lambda item: -abs(item["contribution"]))
        return {
            "file_id": file_id, "filename": report["filename"],
            "overall_confidence": report["overall_confidence"],
            "confidence_type": report["confidence_type"],
            "explanation": explanation,
            "why": "Bijdrage = componentwaarde × gewicht; alleen componenten met "
                   "gewicht tellen mee in het gewogen gemiddelde. Bewijsaantallen "
                   "zijn zichtbaar per component; UNKNOWN blijft UNKNOWN.",
            "provenance": self.km.provenance(),
            "note": "ANALYSIS ONLY FOR TECHNICIAN REVIEW.",
        }

    # ------------------------------------------------------------------
    # V6: Comparison Workspace (§16)
    # ------------------------------------------------------------------
    def compare_workspace(self, left_file_id: int, right_file_id: int) -> dict:
        """Twee files/projecten naast elkaar: metadata, ECU-image-identiteit,
        overeenkomstige regio's (identiteiten + structuursignaturen) en de
        Original→Tuned-ketting van beide kanten. ANALYSIS ONLY."""
        def side(file_id):
            row = self.repo.file(file_id)
            links = self.calibration_identity_links(file_id, [])
            regions = self.repo.map_regions_for_file(file_id)
            pairs = [pair for pair in self.repo.pairs()
                     if pair["confirmed"] and (pair["original_file_id"] == file_id
                                               or pair["tuned_file_id"] == file_id)]
            chain = []
            for pair in pairs[:5]:
                try:
                    diff_report = self.diff(pair["id"])
                    chain.append({"pair_id": pair["id"],
                                  "role": "original" if pair["original_file_id"] == file_id
                                          else "tuned",
                                  "regions": len(diff_report["blocks"])})
                except (OSError, ValueError):
                    continue
            images = self.repo.db.rows(
                """SELECT i.id, i.status, i.image_size, i.confidence
                   FROM ecu_image_identities i JOIN ecu_image_members m
                   ON m.image_id=i.id WHERE m.member_type='file' AND m.member_id=?""",
                (file_id,))
            return {"file_id": file_id, "filename": row["filename"],
                    "size": row["file_size"], "ecu": row["ecu_family"],
                    "hardware": row["hardware_number"],
                    "software": row["software_number"],
                    "calibration": row["calibration_number"],
                    "stage": row["stage"],
                    "identity_links": links, "map_regions": len(regions),
                    "confirmed_pairs": chain,
                    "ecu_image_identities": images}

        left, right = side(left_file_id), side(right_file_id)
        # correspondenties: gedeelde structuursignaturen + gedeelde image-identiteit
        def signatures(file_id):
            return {region.get("structural_signature") or region.get("signature")
                    or str(region.get("region_hash") or region.get("id"))
                    for region in self.repo.map_regions_for_file(file_id)}
        left_sig = signatures(left_file_id)
        right_sig = signatures(right_file_id)
        correspondences = sorted(left_sig & right_sig)
        shared_image = bool(set(row["id"] for row in left["ecu_image_identities"])
                            & set(row["id"] for row in right["ecu_image_identities"]))
        negative = self.km.is_negative("file_match",
                                       ("file", str(left_file_id)),
                                       ("file", str(right_file_id)))
        return {
            "left": left, "right": right,
            "corresponding_structural_signatures": correspondences,
            "same_ecu_image_identity": shared_image,
            "negative_relation": negative,
            "note": ("Technicus heeft deze match negatief gemarkeerd" if negative
                     else "Correspondenties zijn kandidaten: identificatie blijft "
                          "review-only."),
            "provenance": self.km.provenance(),
        }

    # ------------------------------------------------------------------
    # V6: bulk-operaties (§17) met veilige taakgrenzen
    # ------------------------------------------------------------------
    def bulk_process_projects(self, project_ids: list[int], progress=None) -> dict:
        """Meerdere OLS-projecten automatisch verwerken in één hervatbare taak;
        fouten stoppen de bulk niet; elke stap checkpoint."""
        if not project_ids:
            raise ValueError("Geen projecten opgegeven")
        run_id = self.repo.start_run("bulk_ols_process", {"count": len(project_ids)})
        stats = {"processed": 0, "errors": 0}
        errors = []
        for index, project_id in enumerate(project_ids):
            try:
                project = self.repo.project(project_id)
                self.auto_process_ols(project["filepath"])
                stats["processed"] += 1
            except Exception as exc:
                stats["errors"] += 1
                errors.append({"project_id": project_id, "error": str(exc)})
            self.repo.checkpoint_run(run_id, {"index": index}, stats)
            if progress:
                progress(f"Bulk {index + 1}/{len(project_ids)}")
        self.repo.finish_run(run_id, "done", stats)
        return {"run_id": run_id, "status": "done", **stats,
                "error_details": errors[:20]}

    # ------------------------------------------------------------------
    # V6: review-impact meten (§11): before/after op de golden benchmark
    # ------------------------------------------------------------------
    def measure_review_impact(self, apply_review, note: str = "") -> dict:
        """Voer een review-actie uit met before/after-kennissnapshot én
        golden-benchmark. resultaat: verbeterde of verslechterde metrics."""
        before_snapshot = self.snapshot_knowledge()
        before_golden = self.evaluate_golden(save=True)
        apply_review()
        after_snapshot = self.snapshot_knowledge()
        after_golden = self.evaluate_golden(save=True)
        return {
            "knowledge_diff": self.diff_knowledge_snapshots(before_snapshot,
                                                            after_snapshot),
            "golden_before": before_golden["totals"],
            "golden_after": after_golden["totals"],
            "note": note or "review-impact gemeten op golden dataset",
            "provenance": self.km.provenance(),
        }

    # ------------------------------------------------------------------
    # V6: readouts — klant/voertuig-domeinlaag (§12), NOOIT in matching
    # ------------------------------------------------------------------
    def add_readout(self, customer: str, vehicle: str, stage: str = "",
                    technician: str | None = None, readout_date: str | None = None,
                    file_id: int | None = None, project_id: int | None = None,
                    note: str = "") -> dict:
        with self.repo.db.connect() as db:
            cursor = db.execute(
                """INSERT INTO readouts(customer,vehicle,stage,technician,
                   readout_date,file_id,project_id,note) VALUES (?,?,?,?,?,?,?,?)""",
                (customer, vehicle, stage, technician, readout_date, file_id,
                 project_id, note))
            readout_id = cursor.lastrowid
        self.repo.audit("add_readout", "readout", readout_id, actor=technician or "system",
                        after={"customer": customer, "vehicle": vehicle})
        return self.repo.db.rows("SELECT * FROM readouts WHERE id=?", (readout_id,))[0]

    def readouts(self, query: str = "") -> list[dict]:
        like = f"%{query}%"
        return self.repo.db.rows(
            """SELECT * FROM readouts WHERE customer LIKE ? OR vehicle LIKE ?
               OR stage LIKE ? ORDER BY id DESC LIMIT 200""", (like, like, like))

    # ------------------------------------------------------------------
    # Rapportexport (§62): JSON/CSV/MD/HTML voor elk kennisrapport
    # ------------------------------------------------------------------
    def export_report(self, kind: str, subject_id: int | None, fmt: str,
                      path: str | None = None) -> dict:
        from app.reporting import export_report
        builders = {
            "new_bin": lambda: self.new_bin_report(int(subject_id)),
            "ols": lambda: self.repo.project_structure_report(int(subject_id)),
            "calibration_object": lambda: {"report": "calibration_object",
                "objects": self.repo.calibration_objects_for_file(int(subject_id))[:200]},
            "calibration_identity": lambda: {"report": "calibration_identity",
                "identity": next((i for i in self.repo.calibration_identities()
                                  if i["id"] == int(subject_id)), None)},
            "tuning_dna": lambda: {"report": "tuning_dna",
                "records": [d for d in self.tuning_dna()
                            if subject_id is None or d["id"] == int(subject_id)][:200]},
            "pattern": lambda: {"report": "tuning_pattern",
                "patterns": [p for p in self.patterns_detail()
                             if subject_id is None or p["id"] == int(subject_id)][:200]},
            "evidence": lambda: {"report": "evidence",
                "records": self.repo.evidence_for("file", str(subject_id))[:200]},
            "library": lambda: {"report": "library_health", **self.library.storage_summary(),
                                "roots": self.library.roots()},
            "knowledge_build": lambda: {"report": "knowledge_build",
                "build": self.repo.active_knowledge_build(),
                "evaluations": self.repo.confidence_evaluations()[:50]},
        }
        if kind not in builders:
            raise ValueError(f"Onbekend rapportsoort: {kind} "
                             f"(kies uit {', '.join(sorted(builders))})")
        report = builders[kind]()
        report.setdefault("report", kind.replace("_", " ").title())
        written = export_report(report, fmt, path)
        return {"path": written, "format": fmt, "kind": kind}
