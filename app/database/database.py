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
 version_id TEXT, internal_id TEXT, offset INTEGER, length INTEGER, sha256 TEXT,
 content_available INTEGER NOT NULL DEFAULT 0, source_reference TEXT,
 confidence REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'unknown',
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
"""

SCHEMA_VERSION = 3


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
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
