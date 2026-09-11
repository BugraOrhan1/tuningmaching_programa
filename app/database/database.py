"""SQLite schema; each operation owns its connection for worker safety."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
 id INTEGER PRIMARY KEY, filename TEXT NOT NULL, filepath TEXT NOT NULL,
 source_path TEXT NOT NULL, file_type TEXT NOT NULL CHECK(file_type IN ('original','tuned','unknown')),
 file_size INTEGER NOT NULL, sha256 TEXT NOT NULL, md5 TEXT NOT NULL, crc32 TEXT NOT NULL,
 ecu_family TEXT, ecu_manufacturer TEXT, hardware_number TEXT, software_number TEXT,
 calibration_number TEXT, vehicle_make TEXT, vehicle_model TEXT, engine_code TEXT,
 transmission TEXT, stage TEXT, customer TEXT, project TEXT,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(source_path,sha256,file_type));
CREATE INDEX IF NOT EXISTS files_hash ON files(sha256);
CREATE INDEX IF NOT EXISTS files_type_size ON files(file_type,file_size);
CREATE TABLE IF NOT EXISTS file_pairs (
 id INTEGER PRIMARY KEY, original_file_id INTEGER NOT NULL REFERENCES files(id),
 tuned_file_id INTEGER NOT NULL REFERENCES files(id), pair_name TEXT NOT NULL,
 confidence REAL NOT NULL, confirmed INTEGER NOT NULL DEFAULT 0,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(original_file_id,tuned_file_id));
CREATE TABLE IF NOT EXISTS fingerprints (
 id INTEGER PRIMARY KEY, file_id INTEGER UNIQUE NOT NULL REFERENCES files(id),
 fingerprint_type TEXT NOT NULL, fingerprint_data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS diffs (
 id INTEGER PRIMARY KEY, pair_id INTEGER NOT NULL REFERENCES file_pairs(id),
 start_offset INTEGER, end_offset INTEGER, length INTEGER, changed_bytes INTEGER,
 original_hash TEXT, tuned_hash TEXT, change_percentage REAL);
CREATE TABLE IF NOT EXISTS diff_features (
 id INTEGER PRIMARY KEY, diff_id INTEGER NOT NULL REFERENCES diffs(id) ON DELETE CASCADE,
 feature_type TEXT, feature_data TEXT, confidence REAL);
CREATE TABLE IF NOT EXISTS winols_projects (
 id INTEGER PRIMARY KEY, filename TEXT NOT NULL, filepath TEXT NOT NULL,
 source_path TEXT NOT NULL, file_size INTEGER NOT NULL, sha256 TEXT NOT NULL,
 md5 TEXT NOT NULL, crc32 TEXT NOT NULL, project_metadata TEXT NOT NULL,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(source_path, sha256));
CREATE INDEX IF NOT EXISTS winols_projects_hash ON winols_projects(sha256);
CREATE TABLE IF NOT EXISTS ols_objects (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES winols_projects(id) ON DELETE CASCADE,
 internal_id TEXT NOT NULL, object_name_raw TEXT, object_type TEXT NOT NULL,
 offset INTEGER, size INTEGER, binary_available INTEGER NOT NULL DEFAULT 0,
 role TEXT NOT NULL DEFAULT 'unknown', confidence REAL NOT NULL DEFAULT 0,
 detection_method TEXT NOT NULL, evidence TEXT NOT NULL DEFAULT '[]',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(project_id, internal_id));
CREATE INDEX IF NOT EXISTS ols_objects_project ON ols_objects(project_id);
CREATE INDEX IF NOT EXISTS ols_objects_role ON ols_objects(role, confidence);
CREATE TABLE IF NOT EXISTS ols_records (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES winols_projects(id) ON DELETE CASCADE,
 record_id TEXT NOT NULL, offset INTEGER NOT NULL, length INTEGER NOT NULL,
 record_type TEXT NOT NULL, value_raw TEXT NOT NULL, confidence REAL NOT NULL,
 evidence TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(project_id, record_id));
CREATE INDEX IF NOT EXISTS ols_records_project_type ON ols_records(project_id, record_type);
CREATE TABLE IF NOT EXISTS ols_record_references (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES winols_projects(id) ON DELETE CASCADE,
 source_record_id INTEGER NOT NULL REFERENCES ols_records(id) ON DELETE CASCADE,
 target_record_id INTEGER REFERENCES ols_records(id) ON DELETE SET NULL,
 reference_type TEXT NOT NULL, confidence REAL NOT NULL, evidence TEXT NOT NULL,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS ols_binaries (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES winols_projects(id) ON DELETE CASCADE,
 version_id TEXT, internal_id TEXT, offset INTEGER, length INTEGER, payload_offset INTEGER,
 payload_length INTEGER, end_boundary INTEGER, source_offset INTEGER, source_length INTEGER,
 sha256 TEXT, md5 TEXT,
 content_available INTEGER NOT NULL DEFAULT 0, source_reference TEXT,
 confidence REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'unknown',
 boundary_status TEXT NOT NULL DEFAULT 'UNKNOWN',
 evidence TEXT NOT NULL DEFAULT '[]', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ols_binaries_project ON ols_binaries(project_id);
CREATE TABLE IF NOT EXISTS ols_version_relations (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES winols_projects(id) ON DELETE CASCADE,
 source_record_id INTEGER NOT NULL REFERENCES ols_records(id) ON DELETE CASCADE,
 target_record_id INTEGER REFERENCES ols_records(id) ON DELETE SET NULL,
 relation_type TEXT NOT NULL, confidence REAL NOT NULL, evidence TEXT NOT NULL,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS ols_map_objects (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES winols_projects(id) ON DELETE CASCADE,
 record_id INTEGER NOT NULL REFERENCES ols_records(id) ON DELETE CASCADE,
 map_name_raw TEXT NOT NULL, address INTEGER, size INTEGER, dimensions TEXT,
 axis_information TEXT, data_type TEXT, factor REAL, value_offset REAL, unit TEXT,
 confidence REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'label_only',
 evidence TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ols_map_objects_project ON ols_map_objects(project_id);
CREATE TABLE IF NOT EXISTS ols_evidence (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES winols_projects(id) ON DELETE CASCADE,
 evidence_type TEXT NOT NULL, subject_type TEXT NOT NULL, subject_id TEXT,
 value TEXT NOT NULL, offset INTEGER, confidence REAL NOT NULL, status TEXT NOT NULL,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ols_evidence_project ON ols_evidence(project_id, evidence_type);
CREATE TABLE IF NOT EXISTS ols_object_reviews (
 id INTEGER PRIMARY KEY, object_id INTEGER NOT NULL REFERENCES ols_objects(id) ON DELETE CASCADE,
 role TEXT NOT NULL CHECK(role IN ('original','tuned','other','unknown')),
 note TEXT NOT NULL DEFAULT '', reviewer TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(object_id));
CREATE TABLE IF NOT EXISTS schema_migrations (
 version INTEGER PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP NOT NULL);
CREATE TABLE IF NOT EXISTS ecu_families (
 id INTEGER PRIMARY KEY, manufacturer TEXT, family_name TEXT NOT NULL, ecu_type TEXT,
 description TEXT, verified INTEGER NOT NULL DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(manufacturer, family_name, ecu_type));
CREATE TABLE IF NOT EXISTS ecu_signatures (
 id INTEGER PRIMARY KEY, ecu_family_id INTEGER NOT NULL REFERENCES ecu_families(id),
 offset INTEGER NOT NULL, length INTEGER NOT NULL, signature_data TEXT NOT NULL, mask_data TEXT NOT NULL,
 confidence REAL NOT NULL, status TEXT NOT NULL DEFAULT 'candidate', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS software_families (
 id INTEGER PRIMARY KEY, ecu_family_id INTEGER REFERENCES ecu_families(id), family_name TEXT NOT NULL,
 hardware_pattern TEXT, software_pattern TEXT, file_size INTEGER, verified INTEGER NOT NULL DEFAULT 0,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(ecu_family_id, family_name, file_size));
CREATE TABLE IF NOT EXISTS software_signatures (
 id INTEGER PRIMARY KEY, software_family_id INTEGER NOT NULL REFERENCES software_families(id),
 offset INTEGER NOT NULL, length INTEGER NOT NULL, signature_data TEXT NOT NULL, mask_data TEXT NOT NULL,
 confidence REAL NOT NULL, status TEXT NOT NULL DEFAULT 'candidate', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS calibration_families (
 id INTEGER PRIMARY KEY, software_family_id INTEGER NOT NULL REFERENCES software_families(id),
 name TEXT NOT NULL, description TEXT, verified INTEGER NOT NULL DEFAULT 0,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(software_family_id, name));
CREATE TABLE IF NOT EXISTS recognition_results (
 id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL REFERENCES files(id), ecu_family_id INTEGER REFERENCES ecu_families(id),
 software_family_id INTEGER REFERENCES software_families(id), calibration_family_id INTEGER REFERENCES calibration_families(id),
 confidence REAL NOT NULL, detection_method TEXT NOT NULL, details TEXT NOT NULL DEFAULT '{}',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS recognition_results_file ON recognition_results(file_id, created_at DESC);
CREATE TABLE IF NOT EXISTS knowledge_candidates (
 id INTEGER PRIMARY KEY, candidate_type TEXT NOT NULL, subject_key TEXT NOT NULL, payload TEXT NOT NULL,
 confidence REAL NOT NULL, status TEXT NOT NULL DEFAULT 'candidate', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 reviewed_at TEXT, review_note TEXT, UNIQUE(candidate_type, subject_key, status));
CREATE TABLE IF NOT EXISTS calibration_alignments (
 id INTEGER PRIMARY KEY, source_file_id INTEGER NOT NULL REFERENCES files(id), target_file_id INTEGER NOT NULL REFERENCES files(id),
 source_start INTEGER NOT NULL, source_end INTEGER NOT NULL, target_start INTEGER NOT NULL, target_end INTEGER NOT NULL,
 confidence REAL NOT NULL, method TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS calibration_alignments_files ON calibration_alignments(source_file_id, target_file_id);
CREATE TABLE IF NOT EXISTS tuning_dna (
 id INTEGER PRIMARY KEY, pair_id INTEGER NOT NULL UNIQUE REFERENCES file_pairs(id) ON DELETE CASCADE,
 original_file_id INTEGER NOT NULL REFERENCES files(id), tuned_file_id INTEGER NOT NULL REFERENCES files(id),
 payload TEXT NOT NULL, confidence REAL NOT NULL, status TEXT NOT NULL DEFAULT 'candidate',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS tuning_dna_status ON tuning_dna(status, confidence);
CREATE TABLE IF NOT EXISTS tuning_patterns (
 id INTEGER PRIMARY KEY, pattern_key TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
 frequency INTEGER NOT NULL DEFAULT 1, confidence REAL NOT NULL, status TEXT NOT NULL DEFAULT 'candidate',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS tuning_patterns_status ON tuning_patterns(status, frequency DESC);
CREATE TABLE IF NOT EXISTS ols_version_binaries (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES winols_projects(id) ON DELETE CASCADE,
 version_index INTEGER, version_name TEXT, role TEXT NOT NULL DEFAULT 'unknown',
 role_confidence REAL NOT NULL DEFAULT 0, role_evidence TEXT NOT NULL DEFAULT '',
 source_path TEXT, binary_offset INTEGER, binary_length INTEGER, binary_sha256 TEXT,
 complete INTEGER NOT NULL DEFAULT 0, file_id INTEGER REFERENCES files(id),
 relation_type TEXT NOT NULL DEFAULT 'target_unknown', relation_confidence REAL NOT NULL DEFAULT 0,
 relation_evidence TEXT NOT NULL DEFAULT '', evidence TEXT NOT NULL DEFAULT '[]',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(project_id, version_index));
CREATE INDEX IF NOT EXISTS ols_version_binaries_project ON ols_version_binaries(project_id);
CREATE TABLE IF NOT EXISTS tune_candidates (
 id INTEGER PRIMARY KEY, target_file_id INTEGER NOT NULL REFERENCES files(id),
 pair_id INTEGER REFERENCES file_pairs(id), threshold REAL NOT NULL,
 match_score REAL NOT NULL, applied_regions INTEGER NOT NULL DEFAULT 0,
 skipped_regions INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL,
 output_path TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
 status TEXT NOT NULL DEFAULT 'candidate', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS tune_candidates_target ON tune_candidates(target_file_id);
CREATE UNIQUE INDEX IF NOT EXISTS tune_candidates_identity
 ON tune_candidates(target_file_id, IFNULL(pair_id, 0), sha256, status);
"""

SCHEMA_VERSION = 10


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
            db.executescript(V3_SCHEMA)
            db.executescript(LIBRARY_SCHEMA)
            try:
                db.executescript(FTS_DDL)
            except sqlite3.OperationalError:
                pass  # geen FTS5 in deze SQLite-build: zoekfunctie gebruikt LIKE
            # additieve kolommigrale veiligheid voor reeds aangemaakte V3-tabellen
            expected = {
                "tuning_regions": {"original_region_context_hash", "checksum_status"},
                "ols_binaries": {"payload_offset", "payload_length", "end_boundary",
                                 "source_offset", "source_length", "md5", "boundary_status"},
            }
            for table, columns in expected.items():
                present = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
                for column in columns - present:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
            current = db.execute("PRAGMA user_version").fetchone()[0]
            if current < 2:
                db.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (2)")
            if current < SCHEMA_VERSION:
                # The schema is additive and idempotent; executescript above
                # creates every missing V2/V3 table before recording success.
                db.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (SCHEMA_VERSION,))
                db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def rows(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, args)]

V3_SCHEMA = """
CREATE TABLE IF NOT EXISTS tuning_regions (
 id INTEGER PRIMARY KEY, pair_id INTEGER NOT NULL REFERENCES file_pairs(id) ON DELETE CASCADE,
 seq INTEGER NOT NULL DEFAULT 0,
 start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL, length INTEGER NOT NULL,
 changed_byte_count INTEGER NOT NULL, changed_percentage REAL NOT NULL,
 original_bytes_hash TEXT NOT NULL, tuned_bytes_hash TEXT NOT NULL,
 before_context TEXT NOT NULL DEFAULT '', after_context TEXT NOT NULL DEFAULT '',
 original_context_hash TEXT, original_region_context_hash TEXT, tuned_context_hash TEXT,
 relative_start REAL NOT NULL, relative_end REAL NOT NULL,
 structural_signature TEXT NOT NULL, delta_signature TEXT NOT NULL,
 structure_features TEXT NOT NULL DEFAULT '{}',
 entropy_before REAL NOT NULL, entropy_after REAL NOT NULL,
 region_class TEXT NOT NULL DEFAULT 'unknown', checksum_status TEXT NOT NULL DEFAULT 'UNKNOWN',
 cross_pair_shared INTEGER NOT NULL DEFAULT 0,
 alignment_confidence REAL NOT NULL DEFAULT 100.0,
 map_confidence REAL NOT NULL DEFAULT 0.0, map_type TEXT NOT NULL DEFAULT 'unknown',
 stage TEXT, ecu_family TEXT, software_number TEXT, calibration_number TEXT,
 hardware_number TEXT, project TEXT,
 evidence TEXT NOT NULL DEFAULT '[]',
 confidence REAL NOT NULL DEFAULT 0.0, status TEXT NOT NULL DEFAULT 'candidate',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(pair_id, start_offset, end_offset));
CREATE INDEX IF NOT EXISTS tuning_regions_pair ON tuning_regions(pair_id);
CREATE INDEX IF NOT EXISTS tuning_regions_signature ON tuning_regions(structural_signature);
CREATE INDEX IF NOT EXISTS tuning_regions_class ON tuning_regions(region_class, status);
CREATE TABLE IF NOT EXISTS tuning_pattern_members (
 id INTEGER PRIMARY KEY, pattern_id INTEGER NOT NULL REFERENCES tuning_patterns(id) ON DELETE CASCADE,
 region_id INTEGER NOT NULL REFERENCES tuning_regions(id) ON DELETE CASCADE,
 pair_id INTEGER NOT NULL REFERENCES file_pairs(id) ON DELETE CASCADE,
 similarity REAL NOT NULL DEFAULT 100.0, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(pattern_id, region_id));
CREATE INDEX IF NOT EXISTS pattern_members_pattern ON tuning_pattern_members(pattern_id);
CREATE INDEX IF NOT EXISTS pattern_members_region ON tuning_pattern_members(region_id);
CREATE TABLE IF NOT EXISTS software_alignments (
 id INTEGER PRIMARY KEY, pattern_id INTEGER REFERENCES tuning_patterns(id) ON DELETE SET NULL,
 source_file_id INTEGER REFERENCES files(id), target_file_id INTEGER REFERENCES files(id),
 source_software TEXT, target_software TEXT,
 source_start INTEGER, source_end INTEGER, target_start INTEGER, target_end INTEGER,
 structural_similarity REAL NOT NULL DEFAULT 0.0, alignment_confidence REAL NOT NULL DEFAULT 0.0,
 evidence_count INTEGER NOT NULL DEFAULT 0, supporting_projects INTEGER NOT NULL DEFAULT 0,
 supporting_signatures INTEGER NOT NULL DEFAULT 0, contradicting_evidence INTEGER NOT NULL DEFAULT 0,
 method TEXT NOT NULL DEFAULT 'structural_signature', evidence TEXT NOT NULL DEFAULT '[]',
 status TEXT NOT NULL DEFAULT 'candidate', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS software_alignments_pattern ON software_alignments(pattern_id);
CREATE TABLE IF NOT EXISTS map_regions (
 id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
 start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL,
 map_type TEXT NOT NULL DEFAULT 'unknown', map_confidence REAL NOT NULL DEFAULT 0.0,
 dimensions TEXT, element_size INTEGER, payload TEXT NOT NULL DEFAULT '{}',
 status TEXT NOT NULL DEFAULT 'candidate', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(file_id, start_offset, end_offset));
CREATE INDEX IF NOT EXISTS map_regions_file ON map_regions(file_id);
CREATE TABLE IF NOT EXISTS calibration_objects (
 id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
 map_region_id INTEGER REFERENCES map_regions(id) ON DELETE SET NULL,
 object_key TEXT NOT NULL, ecu_family TEXT, hardware TEXT, software_family TEXT,
 calibration_family TEXT, dimensions TEXT, data_type TEXT, element_size INTEGER,
 endian TEXT, row_count INTEGER, column_count INTEGER, axis_count INTEGER,
 axis_signature TEXT, surrounding_signature TEXT, internal_pattern_signature TEXT,
 neighboring_regions TEXT NOT NULL DEFAULT '[]', value_statistics TEXT NOT NULL DEFAULT '{}',
 entropy REAL, context_hashes TEXT NOT NULL DEFAULT '{}', relative_layout TEXT NOT NULL DEFAULT '{}',
 structural_signature TEXT NOT NULL, detection_confidence REAL NOT NULL DEFAULT 0.0,
 evidence TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'candidate',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(file_id, object_key));
CREATE INDEX IF NOT EXISTS calibration_objects_file ON calibration_objects(file_id);
CREATE INDEX IF NOT EXISTS calibration_objects_signature ON calibration_objects(structural_signature);
CREATE TABLE IF NOT EXISTS calibration_identities (
 id INTEGER PRIMARY KEY, identity_key TEXT NOT NULL UNIQUE, ecu_family TEXT,
 structural_signature TEXT NOT NULL, software_variants TEXT NOT NULL DEFAULT '[]',
 project_count INTEGER NOT NULL DEFAULT 0, region_count INTEGER NOT NULL DEFAULT 0,
 supporting_evidence TEXT NOT NULL DEFAULT '[]', contradicting_evidence TEXT NOT NULL DEFAULT '[]',
 confidence REAL NOT NULL DEFAULT 0.0, status TEXT NOT NULL DEFAULT 'CANDIDATE',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS calibration_identities_signature ON calibration_identities(structural_signature);
CREATE TABLE IF NOT EXISTS calibration_identity_members (
 id INTEGER PRIMARY KEY, identity_id INTEGER NOT NULL REFERENCES calibration_identities(id) ON DELETE CASCADE,
 calibration_object_id INTEGER NOT NULL REFERENCES calibration_objects(id) ON DELETE CASCADE,
 file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
 source_start INTEGER, source_end INTEGER, software TEXT,
 relation_confidence REAL NOT NULL DEFAULT 0.0, evidence TEXT NOT NULL DEFAULT '[]',
 status TEXT NOT NULL DEFAULT 'CANDIDATE', UNIQUE(identity_id, calibration_object_id));
CREATE INDEX IF NOT EXISTS calibration_identity_members_identity ON calibration_identity_members(identity_id);
CREATE TABLE IF NOT EXISTS evidence (
 id INTEGER PRIMARY KEY, subject_type TEXT NOT NULL, subject_id TEXT NOT NULL,
 evidence_type TEXT NOT NULL, value TEXT NOT NULL,
 offset INTEGER, confidence REAL NOT NULL DEFAULT 0.0, status TEXT NOT NULL DEFAULT 'observed',
 source TEXT NOT NULL DEFAULT 'analysis', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS evidence_subject ON evidence(subject_type, subject_id);
CREATE TABLE IF NOT EXISTS evidence_relations (
 id INTEGER PRIMARY KEY, evidence_id INTEGER NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
 relation_type TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT,
 confidence REAL NOT NULL DEFAULT 100.0, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS evidence_relations_evidence ON evidence_relations(evidence_id);
CREATE TABLE IF NOT EXISTS analysis_runs (
 id INTEGER PRIMARY KEY, run_type TEXT NOT NULL, config TEXT NOT NULL DEFAULT '{}',
 status TEXT NOT NULL DEFAULT 'running', checkpoint TEXT NOT NULL DEFAULT '{}',
 stats TEXT NOT NULL DEFAULT '{}', started_at TEXT DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS analysis_runs_type ON analysis_runs(run_type, status);
CREATE TABLE IF NOT EXISTS knowledge_builds (
 id INTEGER PRIMARY KEY, status TEXT NOT NULL DEFAULT 'ACTIVE',
 source_projects INTEGER NOT NULL DEFAULT 0, pattern_count INTEGER NOT NULL DEFAULT 0,
 calibration_identity_count INTEGER NOT NULL DEFAULT 0, config_version TEXT NOT NULL DEFAULT 'v1',
 source_run_id INTEGER REFERENCES analysis_runs(id), notes TEXT NOT NULL DEFAULT '',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, completed_at TEXT);
CREATE INDEX IF NOT EXISTS knowledge_builds_status ON knowledge_builds(status, id DESC);
CREATE TABLE IF NOT EXISTS confidence_evaluations (
 id INTEGER PRIMARY KEY, threshold REAL NOT NULL, sample_count INTEGER NOT NULL,
 ambiguous_count INTEGER NOT NULL DEFAULT 0, precision REAL, recall REAL, f1 REAL,
 false_positive_rate REAL, false_negative_rate REAL, brier_score REAL,
 metrics TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS knowledge_reviews (
 id INTEGER PRIMARY KEY, subject_type TEXT NOT NULL, subject_id TEXT NOT NULL,
 action TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}',
 reviewer TEXT, note TEXT NOT NULL DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS knowledge_reviews_subject ON knowledge_reviews(subject_type, subject_id);
"""


LIBRARY_SCHEMA = """
CREATE TABLE IF NOT EXISTS library_roots (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL UNIQUE,
 status TEXT NOT NULL DEFAULT 'ONLINE', last_scan_at TEXT,
 file_count INTEGER NOT NULL DEFAULT 0, content_count INTEGER NOT NULL DEFAULT 0,
 health TEXT NOT NULL DEFAULT 'OK', config TEXT NOT NULL DEFAULT '{}',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS content_objects (
 id INTEGER PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, md5 TEXT, crc32 TEXT,
 size INTEGER NOT NULL, file_type TEXT NOT NULL DEFAULT 'unknown',
 analysis_state TEXT NOT NULL DEFAULT 'NEW', metadata TEXT NOT NULL DEFAULT '{}',
 first_seen TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS content_objects_sha ON content_objects(sha256);
CREATE INDEX IF NOT EXISTS content_objects_type_size ON content_objects(file_type, size);
CREATE TABLE IF NOT EXISTS file_locations (
 id INTEGER PRIMARY KEY, root_id INTEGER NOT NULL REFERENCES library_roots(id),
 content_id INTEGER REFERENCES content_objects(id),
 path TEXT NOT NULL, normalized_path TEXT NOT NULL, filename TEXT NOT NULL,
 extension TEXT NOT NULL, size INTEGER NOT NULL, mtime REAL, ctime REAL,
 scan_status TEXT NOT NULL DEFAULT 'NEW', analysis_state TEXT NOT NULL DEFAULT 'NEW',
 metadata TEXT NOT NULL DEFAULT '{}', last_seen_scan_id INTEGER,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(root_id, normalized_path));
CREATE INDEX IF NOT EXISTS file_locations_content ON file_locations(content_id);
CREATE INDEX IF NOT EXISTS file_locations_root_status ON file_locations(root_id, scan_status);
CREATE INDEX IF NOT EXISTS file_locations_filename ON file_locations(filename);
CREATE TABLE IF NOT EXISTS library_scans (
 id INTEGER PRIMARY KEY, root_id INTEGER NOT NULL REFERENCES library_roots(id),
 started_at TEXT DEFAULT CURRENT_TIMESTAMP, finished_at TEXT, updated_at TEXT,
 status TEXT NOT NULL DEFAULT 'running', checkpoint TEXT NOT NULL DEFAULT '{}',
 stats TEXT NOT NULL DEFAULT '{}', config TEXT NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS library_scans_root ON library_scans(root_id, status);
CREATE TABLE IF NOT EXISTS content_files (
 id INTEGER PRIMARY KEY, content_id INTEGER NOT NULL REFERENCES content_objects(id),
 file_id INTEGER REFERENCES files(id), kind TEXT NOT NULL DEFAULT 'binary',
 project_id INTEGER, analysis_run_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(content_id, file_id));
CREATE INDEX IF NOT EXISTS content_files_content ON content_files(content_id);
CREATE INDEX IF NOT EXISTS content_files_file ON content_files(file_id);
CREATE TABLE IF NOT EXISTS audit_log (
 id INTEGER PRIMARY KEY, actor TEXT NOT NULL DEFAULT 'system',
 action TEXT NOT NULL, subject_type TEXT NOT NULL, subject_id TEXT NOT NULL,
 before_state TEXT NOT NULL DEFAULT '{}', after_state TEXT NOT NULL DEFAULT '{}',
 reason TEXT NOT NULL DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS audit_log_subject ON audit_log(subject_type, subject_id);
CREATE INDEX IF NOT EXISTS audit_log_time ON audit_log(created_at);
"""
V10_SCHEMA = """
-- FTS5-versnellingsindex voor bibliotheekzoekopdrachten (optioneel: alleen
-- aangemaakt als SQLite met FTS5 is gebouwd; zoekfunctie valt terug op LIKE).
"""
FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS library_fts USING fts5(filename, path, sha256, content='file_locations', content_rowid='id');
"""

