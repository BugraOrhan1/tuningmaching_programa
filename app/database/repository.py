"""Managed immutable snapshots, searchable metadata, explicit pair review."""
import json
import logging
import re
from pathlib import Path
from app.database.database import Database
from app.analysis.binary_reader import read_binary
from app.analysis.fingerprint import hashes, fingerprint
from app.analysis.metadata import FIELDS, extract_metadata
from app.analysis.classification import infer_path_type
from app.analysis.recognition import recognize
from app.analysis.similarity import compare
from app.analysis.diff_engine import diff_blocks
from app.analysis.signatures import discover_candidate_signatures
from app.analysis.signatures import matches_signature
from app.winols.ols_reader import read_ols, inspect_ols
from app.winols.ols_importer import OlsImporter
from app.winols.ols_structure import parse_ols_structure
from app.database.knowledge_repo import RepositoryV3Mixin

LOG = logging.getLogger(__name__)


def infer_type(path: Path) -> str:
    return infer_path_type(path)


def pair_key(filename: str) -> str:
    stem = Path(filename).stem.lower()
    stem = re.sub(r"(?:^|[_\s.-])(original|ori|stock|tuned|mod|stage[123]\+?)(?=$|[_\s.-])", "_", stem)
    return re.sub(r"[^a-z0-9]", "", stem)


class Repository(RepositoryV3Mixin):
    def __init__(self, config: dict):
        self.config = config
        self.root = Path(config["data_dir"])
        self.db = Database(self.root / "database.sqlite")
        self.ols_importer = OlsImporter()
        for name in ("originals", "tuned", "unknown", "winols_projects", "reports"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def files(self, query: str = "") -> list[dict]:
        columns = ("filename", "file_type", *FIELDS)
        where = " OR ".join(f"coalesce({c},'') LIKE ? ESCAPE '\\'" for c in columns)
        term = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        return self.db.rows(f"SELECT * FROM files WHERE {where} ORDER BY id DESC", (term,) * len(columns))

    def file(self, file_id: int) -> dict:
        rows = self.db.rows("SELECT * FROM files WHERE id=?", (file_id,))
        if not rows:
            raise ValueError(f"Onbekend bestand-ID {file_id}")
        return rows[0]

    def data(self, file_id: int) -> bytes:
        row = self.file(file_id)
        data = read_binary(row["filepath"], self.config["max_file_mb"])
        if hashes(data)["sha256"] != row["sha256"]:
            raise ValueError(f"Integriteitsfout in beheerde kopie: {row['filename']}")
        return data

    def projects(self, query: str = "") -> list[dict]:
        term = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        projects = self.db.rows("SELECT * FROM winols_projects WHERE filename LIKE ? ESCAPE '\\' OR source_path LIKE ? ESCAPE '\\' ORDER BY id DESC", (term, term))
        for project in projects:
            metadata = json.loads(project["project_metadata"])
            project["suggested_type"] = metadata.get("suggested_type", "unknown")
            project["suggestion_reason"] = metadata.get("suggestion_reason") or "geen expliciet label gevonden"
        return projects

    def project(self, project_id: int) -> dict:
        rows = self.db.rows("SELECT * FROM winols_projects WHERE id=?", (project_id,))
        if not rows:
            raise ValueError(f"Onbekend WinOLS-project-ID {project_id}")
        return rows[0]

    def inspect_project(self, project_id: int) -> dict:
        row = self.project(project_id)
        data = read_ols(row["filepath"], self.config["max_file_mb"])
        if hashes(data)["sha256"] != row["sha256"]:
            raise ValueError(f"Integriteitsfout in beheerde WinOLS-kopie: {row['filename']}")
        return inspect_ols(data)

    def ols_structure(self, project_id: int) -> dict:
        row = self.project(project_id)
        return self.ols_importer.extract_project_structure(row["filepath"], self.config["max_file_mb"])

    def import_project(self, path: Path) -> int:
        path = path.resolve()
        data = read_ols(path, self.config["max_file_mb"])
        details = inspect_ols(data)
        structure = parse_ols_structure(data)
        maps_by_offset = {item["offset"]: item for item in structure.get("maps", [])}
        digest = details.pop("hashes")
        target = self.root / "winols_projects" / (digest["sha256"] + ".ols")
        try:
            with target.open("xb") as stream:
                stream.write(data)
        except FileExistsError:
            if hashes(target.read_bytes())["sha256"] != digest["sha256"]:
                raise ValueError("Bestaande beheerde WinOLS-kopie heeft onjuiste hash")
        row = dict(filename=path.name, filepath=str(target.resolve()), source_path=str(path),
                   file_size=len(data), **digest, project_metadata=json.dumps(details, ensure_ascii=False))
        with self.db.connect() as db:
            db.execute(f"INSERT OR IGNORE INTO winols_projects ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
            project_id = db.execute("SELECT id FROM winols_projects WHERE source_path=? AND sha256=?", (str(path), digest["sha256"])).fetchone()[0]
            for obj in details.get("objects", []):
                    db.execute(
                    """INSERT INTO ols_objects
                    (project_id, internal_id, object_name_raw, object_type, offset, size,
                     binary_available, role, confidence, detection_method, evidence)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(project_id, internal_id) DO UPDATE SET
                    object_name_raw=excluded.object_name_raw,
                    object_type=excluded.object_type,
                    offset=excluded.offset,
                    size=excluded.size,
                    binary_available=excluded.binary_available,
                    role=CASE WHEN ols_objects.detection_method='human_review' THEN ols_objects.role ELSE excluded.role END,
                    confidence=CASE WHEN ols_objects.detection_method='human_review' THEN ols_objects.confidence ELSE excluded.confidence END,
                    detection_method=CASE WHEN ols_objects.detection_method='human_review' THEN ols_objects.detection_method ELSE excluded.detection_method END,
                    evidence=CASE WHEN ols_objects.detection_method='human_review' THEN ols_objects.evidence ELSE excluded.evidence END""",
                    (project_id, obj["internal_id"], obj.get("object_name_raw"), obj["object_type"],
                     obj.get("offset"), obj.get("size"), int(obj.get("binary_available", False)),
                     obj.get("role", "unknown"), obj.get("confidence", 0.0),
                     obj["detection_method"], json.dumps(obj.get("evidence", []), ensure_ascii=False)),
                )
            forensic = details.get("forensic", {})
            db.execute("DELETE FROM ols_evidence WHERE project_id=?", (project_id,))
            db.execute("DELETE FROM ols_map_objects WHERE project_id=?", (project_id,))
            db.execute("DELETE FROM ols_binaries WHERE project_id=?", (project_id,))
            db.execute("DELETE FROM ols_version_relations WHERE project_id=?", (project_id,))
            db.execute("DELETE FROM ols_record_references WHERE project_id=?", (project_id,))
            db.execute("DELETE FROM ols_records WHERE project_id=?", (project_id,))
            record_db_ids = {}
            for record in details.get("records", []):
                cursor = db.execute(
                    """INSERT INTO ols_records
                    (project_id, record_id, offset, length, record_type, value_raw, confidence, evidence)
                    VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(project_id, record_id) DO UPDATE SET
                    offset=excluded.offset, length=excluded.length, record_type=excluded.record_type,
                    value_raw=excluded.value_raw, confidence=excluded.confidence, evidence=excluded.evidence""",
                    (project_id, record["record_id"], record["offset"], record["length"], record["record_type"],
                     record["value_raw"], record["confidence"], record["evidence"]),
                )
                record_db_ids[record["record_id"]] = db.execute(
                    "SELECT id FROM ols_records WHERE project_id=? AND record_id=?",
                    (project_id, record["record_id"])).fetchone()[0]
            for record in details.get("records", []):
                if record["record_type"] == "map_label":
                    parsed = maps_by_offset.get(record["offset"])
                    if parsed:
                        db.execute("""INSERT INTO ols_map_objects
                            (project_id, record_id, map_name_raw, address, dimensions, factor,
                             axis_information, confidence, status, evidence)
                            VALUES (?,?,?,?,?,?,?,?,?,?)""",
                                   (project_id, record_db_ids[record["record_id"]], record["value_raw"],
                                    parsed.get("address"),
                                    json.dumps(parsed["dimension_candidates"]) if parsed.get("dimension_candidates") else None,
                                    parsed["factor_candidates"][0] if parsed.get("factor_candidates") else None,
                                    json.dumps({"address_candidates": parsed.get("address_candidates", []),
                                                "factor_candidates": parsed.get("factor_candidates", [])}),
                                    parsed["confidence"], parsed["status"],
                                    json.dumps(parsed["evidence"], ensure_ascii=False)))
                    else:
                        db.execute("""INSERT INTO ols_map_objects
                            (project_id, record_id, map_name_raw, confidence, status, evidence)
                            VALUES (?,?,?,?,?,?)""",
                                   (project_id, record_db_ids[record["record_id"]], record["value_raw"],
                                    record["confidence"], "label_only", record["evidence"]))
                if record["record_type"] == "version_or_role_label":
                    db.execute("""INSERT INTO ols_version_relations
                        (project_id, source_record_id, relation_type, confidence, evidence)
                        VALUES (?,?,?,?,?)""",
                               (project_id, record_db_ids[record["record_id"]], "target_unknown",
                                0.0, "Label observed; linked binary/version object not decoded."))
                if record["record_type"] == "binary_reference":
                    db.execute("""INSERT INTO ols_record_references
                        (project_id, source_record_id, reference_type, confidence, evidence)
                        VALUES (?,?,?,?,?)""",
                               (project_id, record_db_ids[record["record_id"]], "binary_target_unknown",
                                0.0, "Reference text observed; target binary boundary not decoded."))
                if record["record_type"] in {"binary_reference", "project_metadata"}:
                    db.execute("""INSERT INTO ols_evidence
                        (project_id, evidence_type, subject_type, subject_id, value, offset, confidence, status)
                        VALUES (?,?,?,?,?,?,?,?)""",
                               (project_id, record["record_type"], "record", record["record_id"],
                                record["value_raw"], record["offset"], record["confidence"], "observed"))
            for item in forensic.get("binary_evidence", []):
                db.execute("""INSERT INTO ols_binaries
                    (project_id, internal_id, content_available, source_reference, confidence, status, evidence)
                    VALUES (?,?,?,?,?,?,?)""",
                           (project_id, item["record_id"], 0, item.get("value"), 0.0, item["status"],
                            json.dumps(item, ensure_ascii=False)))
        self._index_external_ols_references(project_id, details.get("records", []))
        LOG.info("Import WinOLS project=%s sha256=%s id=%s", path, digest["sha256"], project_id)
        self._store_ols_structure(project_id, data, structure)
        return project_id

    def _store_ols_structure(self, project_id: int, data: bytes, structure: dict) -> None:
        """Persist proven version binaries, extract them into Files and link evidence."""
        with self.db.connect() as db:
            db.execute("DELETE FROM ols_version_binaries WHERE project_id=?", (project_id,))
        extras = 0
        for item in structure["version_binaries"]:
            binary = item.get("binary")
            version_index = item.get("version_index")
            display_index = version_index
            if version_index is None:
                extras += 1
                display_index = 100 + extras
            file_id = None
            filename = item.get("source_filename") or f"OLS_versie_{display_index}.bin"
            evidence = []
            if binary:
                blob = data[binary["start"]:binary["end"]]
                role = item.get("role", "unknown")
                kind = role if role in {"original", "tuned"} else "unknown"
                suffix = "" if binary["complete"] else "_ONVOLLEDIG"
                stem = Path(filename).stem or f"OLS_versie_{display_index}"
                filename = f"{stem}{suffix}.bin"
                source_path = f"ols://{structure['sha256']}/v{display_index}"
                evidence = [e for e in [item.get("relation_evidence", ""), *binary.get("evidence", [])] if e]
                file_id = self.upsert_ols_file(
                    source_path, filename, blob, kind,
                    "ols_version_label" if kind != "unknown" else "ols_binary_extract",
                    float(item.get("role_confidence", item.get("confidence") or 0.0)),
                    evidence, project_id)
            with self.db.connect() as db:
                db.execute("""INSERT INTO ols_version_binaries
                    (project_id, version_index, version_name, role, role_confidence, role_evidence,
                     source_path, binary_offset, binary_length, binary_sha256, complete, file_id,
                     relation_type, relation_confidence, relation_evidence, evidence)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                           (project_id, display_index, item.get("name"), item.get("role", "unknown"),
                            float(item.get("role_confidence", item.get("confidence") or 0.0)),
                            item.get("reason", ""),
                            item.get("path"), binary["start"] if binary else None,
                            binary["length"] if binary else None,
                            binary["sha256"] if binary else None,
                            int(bool(binary and binary["complete"])), file_id,
                            item.get("relation_type", "target_unknown"),
                            float(item.get("relation_confidence", item.get("confidence") or 0.0)),
                            item.get("relation_evidence", ""),
                            json.dumps(evidence, ensure_ascii=False)))
        for binary in structure["binaries"]:
            with self.db.connect() as db:
                db.execute("""INSERT INTO ols_binaries
                    (project_id, internal_id, offset, length, sha256, content_available,
                     source_reference, confidence, status, evidence)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                           (project_id, f"binary@{binary['start']}", binary["start"], binary["length"],
                            binary["sha256"], 1, binary.get("filename") or binary.get("identity_header"),
                            binary["confidence"],
                            "extracted" if binary["complete"] else "extracted_incomplete",
                            json.dumps(binary["evidence"], ensure_ascii=False)))

    def upsert_ols_file(self, source_path: str, filename: str, data: bytes, kind: str,
                        detection_method: str, confidence: float, evidence: list,
                        project_id: int | None = None) -> int:
        """Register an extracted OLS binary in Files without duplicating on reimport.

        An existing row for the same OLS source and hash is reused so a human
        reclassification always survives a reimport.
        """
        digest = hashes(data)
        existing = self.db.rows("SELECT id FROM files WHERE source_path=? AND sha256=?",
                                (source_path, digest["sha256"]))
        if existing:
            return existing[0]["id"]
        if kind not in {"original", "tuned", "unknown"}:
            kind = "unknown"
        folder = "originals" if kind == "original" else ("tuned" if kind == "tuned" else "unknown")
        target = self.root / folder / (digest["sha256"] + ".bin")
        try:
            with target.open("xb") as stream:
                stream.write(data)
        except FileExistsError:
            if hashes(target.read_bytes())["sha256"] != digest["sha256"]:
                raise ValueError("Bestaande beheerde kopie heeft onjuiste hash")
        row = dict(filename=filename, filepath=str(target.resolve()), source_path=source_path,
                   file_type=kind, file_size=len(data), **digest, **extract_metadata(data))
        with self.db.connect() as db:
            db.execute(f"INSERT OR IGNORE INTO files ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
                       tuple(row.values()))
            file_id = db.execute("SELECT id FROM files WHERE source_path=? AND sha256=? AND file_type=?",
                                 (source_path, digest["sha256"], kind)).fetchone()[0]
            db.execute("INSERT OR IGNORE INTO fingerprints(file_id,fingerprint_type,fingerprint_data) VALUES (?,?,?)",
                       (file_id, "blocks-histogram-v1", json.dumps(fingerprint(data, self.config["block_size"]))))
            if project_id is not None:
                db.execute("""INSERT INTO ols_evidence
                    (project_id, evidence_type, subject_type, subject_id, value, offset, confidence, status)
                    VALUES (?,?,?,?,?,?,?,?)""",
                           (project_id, "extracted_binary", "file", str(file_id),
                            json.dumps(evidence, ensure_ascii=False), None, confidence, "extracted"))
        LOG.info("OLS binary gextraheerd file=%s kind=%s sha256=%s", filename, kind, digest["sha256"])
        self.recognize_file(file_id, data)
        return file_id

    def _index_external_ols_references(self, project_id: int, records: list[dict]) -> None:
        """Index referenced raw files only when their source path exists.

        The source filename is never used to assign Original/Tuned. Missing
        paths remain evidence in the OLS project and are not fabricated.
        """
        for record in records:
            if record["record_type"] != "binary_reference":
                continue
            source = Path(record["value_raw"])
            status = "external_reference_missing"
            file_id = None
            source_reference = str(source)
            if source.is_file() and source.suffix.lower() in {".bin", ".ori"}:
                try:
                    file_id = self.import_file(source, "unknown")
                    status = "external_file_indexed"
                except (OSError, ValueError) as exc:
                    LOG.warning("OLS external reference not indexed path=%s error=%s", source, exc)
            with self.db.connect() as db:
                evidence = {"record_id": record["record_id"], "source_reference": source_reference,
                            "file_id": file_id, "status": status}
                existing = db.execute("SELECT id FROM ols_binaries WHERE project_id=? AND internal_id=?",
                                      (project_id, record["record_id"])).fetchone()
                if existing:
                    db.execute("""UPDATE ols_binaries SET content_available=?, source_reference=?,
                        confidence=?, status=?, evidence=? WHERE id=?""",
                               (int(file_id is not None), source_reference,
                                100.0 if file_id is not None else 0.0, status,
                                json.dumps(evidence, ensure_ascii=False), existing[0]))
                    continue
                db.execute("""INSERT INTO ols_binaries
                    (project_id, internal_id, content_available, source_reference, confidence, status, evidence)
                    VALUES (?,?,?,?,?,?,?)""",
                           (project_id, record["record_id"], int(file_id is not None), source_reference,
                            100.0 if file_id is not None else 0.0, status,
                            json.dumps(evidence, ensure_ascii=False)))

    def project_objects(self, project_id: int) -> list[dict]:
        """Return observable OLS objects without claiming opaque objects are binaries."""
        self.project(project_id)
        rows = self.db.rows("SELECT * FROM ols_objects WHERE project_id=? ORDER BY id", (project_id,))
        for row in rows:
            row["evidence"] = json.loads(row["evidence"])
        return rows

    def project_records(self, project_id: int) -> list[dict]:
        self.project(project_id)
        return self.db.rows("SELECT * FROM ols_records WHERE project_id=? ORDER BY offset, id", (project_id,))

    def project_structure_report(self, project_id: int) -> dict:
        project = self.project(project_id)
        metadata = json.loads(project["project_metadata"])
        records = self.project_records(project_id)
        maps = self.db.rows("SELECT * FROM ols_map_objects WHERE project_id=? ORDER BY id", (project_id,))
        binaries = self.db.rows("SELECT * FROM ols_binaries WHERE project_id=? ORDER BY id", (project_id,))
        return {"project": project, "metadata": metadata, "records": records, "maps": maps,
                "binaries": binaries, "relationships": [],
                "unknown_structures": ["binary_boundaries", "version_tree", "record_pointers", "map_addresses"]}

    def review_ols_object(self, object_id: int, role: str, note: str = "", reviewer: str | None = None) -> dict:
        if role not in {"original", "tuned", "other", "unknown"}:
            raise ValueError("Ongeldige OLS-objectrol")
        with self.db.connect() as db:
            row = db.execute("SELECT * FROM ols_objects WHERE id=?", (object_id,)).fetchone()
            if not row:
                raise ValueError("Onbekend OLS-object-ID")
            db.execute("""INSERT INTO ols_object_reviews(object_id,role,note,reviewer)
                         VALUES (?,?,?,?) ON CONFLICT(object_id) DO UPDATE SET
                         role=excluded.role, note=excluded.note, reviewer=excluded.reviewer,
                         created_at=CURRENT_TIMESTAMP""", (object_id, role, note, reviewer))
            db.execute("UPDATE ols_objects SET role=?, confidence=?, detection_method=? WHERE id=?",
                       (role, 100.0 if role != "unknown" else 0.0, "human_review", object_id))
        return self.db.rows("SELECT o.*, r.note, r.reviewer, r.created_at AS reviewed_at FROM ols_objects o JOIN ols_object_reviews r ON r.object_id=o.id WHERE o.id=?", (object_id,))[0]

    def ols_versions(self, project_id: int) -> list[dict]:
        """Version records with their proven binary, extracted file and evidence."""
        self.project(project_id)
        rows = self.db.rows("SELECT * FROM ols_version_binaries WHERE project_id=? ORDER BY version_index, id",
                            (project_id,))
        for row in rows:
            row["evidence"] = json.loads(row["evidence"])
        return rows

    def suggest_ols_project_pairs(self, project_id: int) -> list[dict]:
        """Pair Original → Tuned versions of one OLS project on explicit evidence.

        A pair is created only for equal-size complete binaries. It is
        auto-confirmed only when both roles come from explicit WinOLS version
        labels; anything weaker stays unconfirmed for human review.
        """
        self.project(project_id)
        rows = [row for row in self.ols_versions(project_id) if row["file_id"] and row["complete"]]
        originals = [row for row in rows if row["role"] == "original"]
        tuned = [row for row in rows if row["role"] == "tuned"]
        results = []
        for original in originals:
            for candidate in tuned:
                if candidate["binary_length"] != original["binary_length"]:
                    results.append({"original_file_id": original["file_id"],
                                    "tuned_file_id": candidate["file_id"],
                                    "status": "size_mismatch_not_paired",
                                    "reason": f"Versiegrootte {original['binary_length']} ≠ "
                                              f"{candidate['binary_length']}; diff is niet betrouwbaar."})
                    continue
                explicit = min(original["role_confidence"], candidate["role_confidence"]) >= 95.0
                pair_id = self.pair(original["file_id"], candidate["file_id"], explicit, 90.0)
                results.append({"pair_id": pair_id, "original_file_id": original["file_id"],
                                "tuned_file_id": candidate["file_id"], "confirmed": bool(explicit),
                                "status": "confirmed" if explicit else "suggested"})
        return results

    def add_tune_candidate(self, target_file_id: int, pair_id: int | None, threshold: float,
                           match_score: float, applied: int, skipped: int, payload: dict,
                           output_path: str, sha: dict, size: int) -> int:
        with self.db.connect() as db:
            cursor = db.execute("""INSERT INTO tune_candidates
                (target_file_id, pair_id, threshold, match_score, applied_regions, skipped_regions,
                 payload, output_path, sha256, size)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                               (target_file_id, pair_id, threshold, match_score, applied, skipped,
                                json.dumps(payload, ensure_ascii=False), output_path,
                                sha["sha256"], size))
            return cursor.lastrowid

    def tune_candidates(self) -> list[dict]:
        rows = self.db.rows("SELECT * FROM tune_candidates ORDER BY id DESC")
        for row in rows:
            row["payload"] = json.loads(row["payload"])
        return rows

    def ols_unknown_objects(self, project_id: int | None = None) -> list[dict]:
        if project_id is None:
            return self.db.rows("SELECT * FROM ols_objects WHERE role='unknown' ORDER BY confidence DESC, id")
        self.project(project_id)
        return self.db.rows("SELECT * FROM ols_objects WHERE project_id=? AND role='unknown' ORDER BY confidence DESC, id", (project_id,))

    def import_file(self, path: Path, kind: str = "auto") -> int:
        path = path.resolve()
        data = read_binary(path, self.config["max_file_mb"])
        digest = hashes(data)
        if kind == "auto":
            kind = infer_type(path)
            if kind == "unknown":
                existing = self.db.rows("SELECT DISTINCT file_type FROM files WHERE sha256=? AND file_type IN ('original','tuned')", (digest["sha256"],))
                if len(existing) == 1:
                    kind = existing[0]["file_type"]
        if kind not in {"original", "tuned", "unknown"}:
            raise ValueError("Ongeldig bestandstype")
        folder = "originals" if kind == "original" else kind
        target = self.root / folder / (digest["sha256"] + ".bin")
        try:
            with target.open("xb") as stream:
                stream.write(data)
        except FileExistsError:
            if hashes(target.read_bytes())["sha256"] != digest["sha256"]:
                raise ValueError("Bestaande beheerde kopie heeft onjuiste hash")
        row = dict(filename=path.name, filepath=str(target.resolve()), source_path=str(path),
                   file_type=kind, file_size=len(data), **digest, **extract_metadata(data))
        with self.db.connect() as db:
            db.execute(f"INSERT OR IGNORE INTO files ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
            file_id = db.execute("SELECT id FROM files WHERE source_path=? AND sha256=? AND file_type=?",
                                 (str(path), digest["sha256"], kind)).fetchone()[0]
            db.execute("INSERT OR IGNORE INTO fingerprints(file_id,fingerprint_type,fingerprint_data) VALUES (?,?,?)",
                       (file_id, "blocks-histogram-v1", json.dumps(fingerprint(data, self.config["block_size"]))))
        LOG.info("Import file=%s sha256=%s id=%s", path, digest["sha256"], file_id)
        self.recognize_file(file_id, data)
        return file_id

    def recognize_file(self, file_id: int, data: bytes | None = None) -> dict:
        """Persist reproducible binary evidence; never overwrites user metadata."""
        data = self.data(file_id) if data is None else data
        details = recognize(data)
        evidence = [item for values in details.values() if isinstance(values, list) for item in values]
        confidence = max((item["confidence"] for item in evidence), default=0.0)
        with self.db.connect() as db:
            db.execute("INSERT INTO recognition_results(file_id,confidence,detection_method,details) VALUES (?,?,?,?)",
                       (file_id, confidence, "binary-evidence-v1", json.dumps(details, ensure_ascii=False)))
        return details

    def recognition(self, file_id: int) -> dict:
        rows = self.db.rows("SELECT * FROM recognition_results WHERE file_id=? ORDER BY id DESC LIMIT 1", (file_id,))
        return json.loads(rows[0]["details"]) if rows else self.recognize_file(file_id)

    def candidates(self, status: str = "candidate") -> list[dict]:
        allowed = {"candidate", "approved", "rejected"}
        if status not in allowed:
            raise ValueError("Ongeldige candidate status")
        rows = self.db.rows("SELECT * FROM knowledge_candidates WHERE status=? ORDER BY confidence DESC, id DESC", (status,))
        for row in rows:
            row["payload"] = json.loads(row["payload"])
        return rows

    def _candidate(self, candidate_type: str, subject_key: str, payload: dict, confidence: float) -> None:
        with self.db.connect() as db:
            db.execute("INSERT OR IGNORE INTO knowledge_candidates(candidate_type,subject_key,payload,confidence) VALUES (?,?,?,?)",
                       (candidate_type, subject_key, json.dumps(payload, ensure_ascii=False), confidence))

    def propose_families(self) -> dict:
        """Propose only repeated observed identifiers; technician approval is required."""
        grouped: dict[tuple[str, str, str | None], list[int]] = {}
        for row in self.files():
            evidence = self.recognition(row["id"])
            ecu_items = [item for item in evidence.get("ecu", []) if item["confidence"] >= 70]
            ecu_name = ecu_items[0]["value"] if ecu_items else None
            for group, candidate_type in (("ecu", "ecu_family"), ("software", "software_family")):
                items = [item for item in evidence.get(group, []) if item["confidence"] >= 70]
                if items:
                    key = (candidate_type, items[0]["value"], None if candidate_type == "ecu_family" else ecu_name)
                    grouped.setdefault(key, []).append(row["id"])
        proposed = []
        for (candidate_type, value, ecu_name), file_ids in grouped.items():
            if len(file_ids) < 2:
                continue
            confidence = min(95.0, 55.0 + len(file_ids) * 5)
            subject_key = value if ecu_name is None else f"{ecu_name}:{value}"
            payload = {"name": value, "file_ids": file_ids, "evidence_count": len(file_ids),
                       "ecu_family_name": ecu_name}
            self._candidate(candidate_type, subject_key, payload, confidence)
            proposed.append({"type": candidate_type, "name": value, "ecu_family": ecu_name,
                             "file_count": len(file_ids), "confidence": confidence})
        return {"proposals": proposed, "note": "Voorstellen zijn geen geverifieerde databasekennis tot goedkeuring."}

    def approve_candidate(self, candidate_id: int, note: str = "") -> dict:
        rows = self.db.rows("SELECT * FROM knowledge_candidates WHERE id=? AND status='candidate'", (candidate_id,))
        if not rows:
            raise ValueError("Candidate bestaat niet of is al beoordeeld")
        row, payload = rows[0], json.loads(rows[0]["payload"])
        with self.db.connect() as db:
            if row["candidate_type"] == "ecu_family":
                db.execute("INSERT OR IGNORE INTO ecu_families(manufacturer,family_name,ecu_type,description,verified) VALUES (?,?,?,?,1)",
                           (None, payload["name"], payload["name"], "Approved from repeated binary evidence"))
                family_id = db.execute("SELECT id FROM ecu_families WHERE family_name=?", (payload["name"],)).fetchone()[0]
                for file_id in payload["file_ids"]:
                    db.execute("UPDATE recognition_results SET ecu_family_id=? WHERE file_id=?", (family_id, file_id))
                result = {"ecu_family_id": family_id}
            elif row["candidate_type"] == "software_family":
                ecu_family_id = None
                if payload.get("ecu_family_name"):
                    match = db.execute("SELECT id FROM ecu_families WHERE family_name=? AND verified=1",
                                       (payload["ecu_family_name"],)).fetchone()
                    ecu_family_id = match[0] if match else None
                file_size = self.file(payload["file_ids"][0])["file_size"]
                db.execute("INSERT OR IGNORE INTO software_families(ecu_family_id,family_name,software_pattern,file_size,verified) VALUES (?,?,?,?,1)",
                           (ecu_family_id, payload["name"], payload["name"], file_size))
                family_id = db.execute("SELECT id FROM software_families WHERE ecu_family_id IS ? AND family_name=? AND file_size=?",
                                       (ecu_family_id, payload["name"], file_size)).fetchone()[0]
                for file_id in payload["file_ids"]:
                    db.execute("UPDATE recognition_results SET software_family_id=? WHERE file_id=?", (family_id, file_id))
                result = {"software_family_id": family_id}
            elif row["candidate_type"] == "ecu_signature":
                db.execute("INSERT INTO ecu_signatures(ecu_family_id,offset,length,signature_data,mask_data,confidence,status) VALUES (?,?,?,?,?,?, 'verified')",
                           (payload["ecu_family_id"], payload["offset"], payload["length"], payload["signature_data"], payload["mask_data"], row["confidence"]))
                result = {"ecu_signature_id": db.execute("SELECT last_insert_rowid()").fetchone()[0]}
            elif row["candidate_type"] == "software_signature":
                db.execute("INSERT INTO software_signatures(software_family_id,offset,length,signature_data,mask_data,confidence,status) VALUES (?,?,?,?,?,?, 'verified')",
                           (payload["software_family_id"], payload["offset"], payload["length"], payload["signature_data"], payload["mask_data"], row["confidence"]))
                result = {"software_signature_id": db.execute("SELECT last_insert_rowid()").fetchone()[0]}
            else:
                raise ValueError("Dit candidate-type kan niet automatisch worden goedgekeurd")
            db.execute("UPDATE knowledge_candidates SET status='approved', reviewed_at=CURRENT_TIMESTAMP, review_note=? WHERE id=?", (note, candidate_id))
        LOG.info("Candidate approved id=%s type=%s", candidate_id, row["candidate_type"])
        return result

    def reject_candidate(self, candidate_id: int, note: str = "") -> None:
        with self.db.connect() as db:
            if not db.execute("UPDATE knowledge_candidates SET status='rejected', reviewed_at=CURRENT_TIMESTAMP, review_note=? WHERE id=? AND status='candidate'", (note, candidate_id)).rowcount:
                raise ValueError("Candidate bestaat niet of is al beoordeeld")
        LOG.info("Candidate rejected id=%s", candidate_id)

    def discover_ecu_signature_candidates(self, ecu_family_id: int) -> dict:
        rows = self.db.rows("SELECT DISTINCT f.id FROM files f JOIN recognition_results r ON r.file_id=f.id WHERE r.ecu_family_id=?", (ecu_family_id,))
        data = [self.data(row["id"]) for row in rows]
        candidates = discover_candidate_signatures(data)
        for candidate in candidates:
            payload = {**candidate, "ecu_family_id": ecu_family_id, "file_ids": [row["id"] for row in rows]}
            self._candidate("ecu_signature", candidate["digest"], payload, candidate["confidence"])
        return {"ecu_family_id": ecu_family_id, "sample_count": len(data), "candidates": candidates}

    def discover_software_signature_candidates(self, software_family_id: int) -> dict:
        rows = self.db.rows("SELECT DISTINCT f.id FROM files f JOIN recognition_results r ON r.file_id=f.id WHERE r.software_family_id=?", (software_family_id,))
        data = [self.data(row["id"]) for row in rows]
        candidates = discover_candidate_signatures(data)
        for candidate in candidates:
            payload = {**candidate, "software_family_id": software_family_id, "file_ids": [row["id"] for row in rows]}
            self._candidate("software_signature", candidate["digest"], payload, candidate["confidence"])
        return {"software_family_id": software_family_id, "sample_count": len(data), "candidates": candidates}

    def ecu_families(self) -> list[dict]:
        return self.db.rows("SELECT e.*, COUNT(DISTINCT r.file_id) AS file_count, SUM(CASE WHEN f.file_type='original' THEN 1 ELSE 0 END) AS original_count, SUM(CASE WHEN f.file_type='tuned' THEN 1 ELSE 0 END) AS tuned_count FROM ecu_families e LEFT JOIN recognition_results r ON r.ecu_family_id=e.id LEFT JOIN files f ON f.id=r.file_id GROUP BY e.id ORDER BY e.family_name")

    def software_families(self) -> list[dict]:
        return self.db.rows("SELECT s.*, COUNT(DISTINCT r.file_id) AS file_count FROM software_families s LEFT JOIN recognition_results r ON r.software_family_id=s.id GROUP BY s.id ORDER BY s.family_name")

    def hierarchical_originals(self, recognition: dict) -> tuple[list[dict], dict]:
        """Use only verified family knowledge as an optional safe prefilter."""
        all_originals = [row for row in self.files() if row["file_type"] == "original"]
        ecu_values = [item["value"] for item in recognition.get("ecu", []) if item["confidence"] >= 70]
        if not ecu_values:
            return all_originals, {"stage": "all_originals", "reason": "Geen geverifieerde ECU-family identifier in input."}
        marks = ",".join("?" for _ in ecu_values)
        families = self.db.rows(f"SELECT id, family_name FROM ecu_families WHERE verified=1 AND family_name IN ({marks})", tuple(ecu_values))
        if not families:
            return all_originals, {"stage": "all_originals", "reason": "Geen geverifieerde ECU-family match; volledige fallback gebruikt."}
        family_ids = tuple(row["id"] for row in families)
        marks = ",".join("?" for _ in family_ids)
        ids = self.db.rows(f"SELECT DISTINCT file_id FROM recognition_results WHERE ecu_family_id IN ({marks})", family_ids)
        allowed = {row["file_id"] for row in ids}
        filtered = [row for row in all_originals if row["id"] in allowed]
        return (filtered or all_originals), {"stage": "verified_ecu_family", "family_ids": list(family_ids),
                                              "reason": "Gefilterd op goedgekeurde ECU-family."}

    def prefilter_originals(self, query_fingerprint: dict, recognition: dict) -> tuple[list[dict], dict]:
        """Bound full byte reads by ranking precomputed histogram fingerprints."""
        originals, hierarchy = self.hierarchical_originals(recognition)
        same_size = [row for row in originals if row["file_size"] == query_fingerprint["ecu_family"]["file_size"]]
        candidates = same_size or originals
        limit = self.config.get("candidate_pool", 250)
        if len(candidates) <= limit:
            hierarchy["prefilter"] = f"{len(candidates)} candidates; volledige bytevergelijking gebruikt."
            return candidates, hierarchy
        stored = {row["file_id"]: json.loads(row["fingerprint_data"]) for row in self.db.rows(
            "SELECT file_id,fingerprint_data FROM fingerprints WHERE file_id IN (" + ",".join("?" for _ in candidates) + ")",
            tuple(row["id"] for row in candidates))}
        query_histogram = query_fingerprint["histogram"]
        def distance(row: dict) -> float:
            item = stored.get(row["id"], {})
            histogram = item.get("histogram")
            if not histogram:
                return float("inf")
            return sum((left-right) ** 2 for left, right in zip(query_histogram, histogram))
        selected = sorted(candidates, key=distance)[:limit]
        hierarchy["prefilter"] = f"{len(candidates)} kandidaten gerangschikt op opgeslagen bytefrequentie; top {len(selected)} volledig vergeleken."
        return selected, hierarchy

    def verified_signature_matches(self, data: bytes, candidate_file_id: int) -> int:
        rows = self.db.rows("""
            SELECT s.offset, s.signature_data, s.mask_data
            FROM ecu_signatures s JOIN recognition_results r ON r.ecu_family_id=s.ecu_family_id
            WHERE r.file_id=? AND s.status='verified'
        """, (candidate_file_id,))
        return sum(matches_signature(data, row["offset"], bytes.fromhex(row["signature_data"]), bytes.fromhex(row["mask_data"])) for row in rows)

    def auto_classify_exact_duplicates(self) -> dict:
        """Classify unknown records only when byte-identical typed evidence exists."""
        candidates = self.db.rows("""
            SELECT u.id, u.filename, GROUP_CONCAT(DISTINCT known.file_type) AS types
            FROM files u JOIN files known ON known.sha256=u.sha256
            WHERE u.file_type='unknown' AND known.file_type IN ('original','tuned')
            GROUP BY u.id HAVING COUNT(DISTINCT known.file_type)=1
        """)
        changed, skipped = [], []
        for candidate in candidates:
            types = candidate["types"].split(',')
            if len(types) != 1:
                skipped.append(candidate["id"])
                continue
            try:
                self.reclassify_files([candidate["id"]], types[0])
                changed.append({"id": candidate["id"], "filename": candidate["filename"], "kind": types[0], "reason": "exacte SHA256-overeenkomst"})
            except ValueError:
                skipped.append(candidate["id"])
        return {"updated": changed, "skipped": skipped,
                "note": "Alleen exacte SHA256-overeenkomsten worden automatisch geclassificeerd."}

    def auto_classify_evidence(self) -> dict:
        """Classify unknown raw files when independent evidence is unambiguous.

        The method deliberately refuses ambiguous near matches. A high binary
        score alone does not prove Original versus Tuned when both categories
        contain the same software family.
        """
        unknown = [row for row in self.files() if row["file_type"] == "unknown"]
        typed = [row for row in self.files() if row["file_type"] in {"original", "tuned"}]
        updated, review, skipped = [], [], []
        for row in unknown:
            label = infer_path_type(Path(row["source_path"]))
            if label in {"original", "tuned"}:
                reason = "expliciet label in bestandsnaam of map"
                self.reclassify_files([row["id"]], label)
                updated.append({"id": row["id"], "filename": row["filename"], "kind": label,
                                "confidence": 100.0, "reason": reason})
                continue

            exact_types = {item["file_type"] for item in typed if item["sha256"] == row["sha256"]}
            if len(exact_types) == 1:
                label = exact_types.pop()
                self.reclassify_files([row["id"]], label)
                updated.append({"id": row["id"], "filename": row["filename"], "kind": label,
                                "confidence": 100.0, "reason": "exacte SHA256-overeenkomst"})
                continue

            same_size = [item for item in typed if item["file_size"] == row["file_size"]]
            if not same_size:
                skipped.append({"id": row["id"], "reason": "geen bestand met dezelfde grootte"})
                continue
            data = self.data(row["id"])
            best_by_type = {}
            for item in same_size:
                evidence = compare(data, self.data(item["id"]), row, item, self.config["block_size"])
                best_by_type[item["file_type"]] = max(best_by_type.get(item["file_type"], 0.0), evidence["match_score"])
            ranked = sorted(best_by_type.items(), key=lambda item: item[1], reverse=True)
            if (len(ranked) == 1 or ranked[0][1] - ranked[1][1] >= 2.0) and ranked[0][1] >= 99.5:
                label, score = ranked[0]
                confidence = round(min(99.0, 80.0 + (score - 99.5) * 4), 2)
                self.reclassify_files([row["id"]], label)
                updated.append({"id": row["id"], "filename": row["filename"], "kind": label,
                                "confidence": confidence, "reason": "unieke binary-match",
                                "match_score": round(score, 4)})
            else:
                review.append({"id": row["id"], "filename": row["filename"],
                               "candidates": [{"kind": kind, "match_score": round(score, 4)}
                                              for kind, score in ranked],
                               "reason": "binary-match niet uniek genoeg"})
        return {"updated": updated, "review": review, "skipped": skipped,
                "note": "Alleen eenduidige evidence is automatisch toegepast; reviewgevallen blijven unknown."}

    def import_folder(self, folder: str, kind: str = "auto", progress=None) -> dict:
        source = Path(folder).resolve()
        if not source.is_dir():
            raise ValueError("Importmap bestaat niet")
        paths = [p for p in source.rglob('*') if p.is_file() and p.suffix.lower() in {'.bin', '.ori', '.ols'}
                 and not p.resolve().is_relative_to(self.root.resolve())]
        result = {"processed": 0, "projects": 0, "errors": []}
        for index, path in enumerate(paths):
            try:
                if path.suffix.lower() == '.ols':
                    self.import_project(path)
                    result["projects"] += 1
                else:
                    self.import_file(path, kind)
                    result["processed"] += 1
            except (OSError, ValueError) as exc:
                result["errors"].append({"path": str(path), "error": str(exc)})
                LOG.exception("Import failed: %s", path)
            if progress:
                progress(f"Import {index+1}/{len(paths)}: {path.name}")
        return result

    def update_metadata(self, file_id: int, values: dict) -> None:
        self.file(file_id)
        if not values or set(values) - set(FIELDS):
            raise ValueError("Ongeldige metadatavelden")
        if any(not isinstance(v, str) or len(v) > 256 for v in values.values()):
            raise ValueError("Metadata moet tekst zijn van maximaal 256 tekens")
        with self.db.connect() as db:
            db.execute(f"UPDATE files SET {','.join(k+'=?' for k in values)} WHERE id=?", (*values.values(), file_id))
        LOG.info("Metadata updated id=%s fields=%s", file_id, list(values))

    def reclassify_files(self, file_ids: list[int], kind: str) -> int:
        """Move managed copies to a new safe category; sources remain untouched."""
        ids = list(dict.fromkeys(file_ids))
        if not ids:
            raise ValueError("Selecteer minstens één bestand.")
        if kind not in {"original", "tuned", "unknown"}:
            raise ValueError("Ongeldig bestandstype")
        rows = [self.file(file_id) for file_id in ids]
        if any(row["file_type"] == kind for row in rows):
            rows = [row for row in rows if row["file_type"] != kind]
        if not rows:
            return 0
        change_ids = [row["id"] for row in rows]
        placeholders = ",".join("?" for _ in change_ids)
        with self.db.connect() as db:
            paired = db.execute(f"SELECT DISTINCT original_file_id AS id FROM file_pairs WHERE original_file_id IN ({placeholders}) UNION SELECT DISTINCT tuned_file_id AS id FROM file_pairs WHERE tuned_file_id IN ({placeholders})", (*change_ids, *change_ids)).fetchall()
            if paired:
                raise ValueError("Een gekoppeld bestand kan niet worden herclassificeerd; verwijder of corrigeer eerst het paar.")
            for row in rows:
                duplicate = db.execute("SELECT id FROM files WHERE source_path=? AND sha256=? AND file_type=? AND id!=?", (row["source_path"], row["sha256"], kind, row["id"])).fetchone()
                if duplicate:
                    raise ValueError(f"{row['filename']} bestaat al als {kind} (ID {duplicate['id']}).")
        folder = "originals" if kind == "original" else kind
        for row in rows:
            data = self.data(row["id"])
            target = self.root / folder / (row["sha256"] + ".bin")
            try:
                with target.open("xb") as stream:
                    stream.write(data)
            except FileExistsError:
                if hashes(target.read_bytes())["sha256"] != row["sha256"]:
                    raise ValueError("Bestaande beheerde kopie heeft onjuiste hash")
            with self.db.connect() as db:
                db.execute("UPDATE files SET file_type=?, filepath=? WHERE id=?", (kind, str(target.resolve()), row["id"]))
        LOG.info("Reclassified files=%s kind=%s", [row["id"] for row in rows], kind)
        return len(rows)

    def pair(self, original_id: int, tuned_id: int, confirmed: bool = False, confidence: float = 100) -> int:
        a, b = self.file(original_id), self.file(tuned_id)
        if original_id == tuned_id or a['file_type'] != 'original' or b['file_type'] != 'tuned':
            raise ValueError("Selecteer een original en een tuned bestand")
        with self.db.connect() as db:
            db.execute("INSERT INTO file_pairs(original_file_id,tuned_file_id,pair_name,confidence,confirmed) VALUES (?,?,?,?,?) ON CONFLICT(original_file_id,tuned_file_id) DO UPDATE SET confirmed=max(confirmed,excluded.confirmed)",
                       (original_id, tuned_id, f"{a['filename']} → {b['filename']}", confidence, int(confirmed)))
            pair_id = db.execute("SELECT id FROM file_pairs WHERE original_file_id=? AND tuned_file_id=?", (original_id, tuned_id)).fetchone()[0]
        LOG.info("Pair %s confirmed=%s", pair_id, confirmed)
        return pair_id

    def suggest_pairs(self) -> int:
        originals = {}
        files = self.files()
        for row in files:
            if row['file_type'] == 'original':
                originals.setdefault((pair_key(row['filename']), row['file_size']), []).append(row)
        count = 0
        for row in files:
            if row['file_type'] != 'tuned':
                continue
            candidates = originals.get((pair_key(row['filename']), row['file_size']), [])
            if pair_key(row['filename']) and len(candidates) == 1:
                self.pair(candidates[0]['id'], row['id'], False, 60)
                count += 1
        return count

    def suggest_binary_relationships(self, limit_per_tuned: int = 5) -> list[dict]:
        """Suggest raw-file relationships using binary evidence only.

        Suggestions stay unconfirmed and are never treated as transferable
        tuning. Metadata-compatible files are preferred before same-size
        fallbacks to keep batch work bounded for large libraries.
        """
        if limit_per_tuned < 1:
            raise ValueError("limit_per_tuned must be positive")
        originals = [row for row in self.files() if row["file_type"] == "original"]
        tuned = [row for row in self.files() if row["file_type"] == "tuned"]
        proposals = []
        for tuned_row in tuned:
            compatible = [row for row in originals if row["file_size"] == tuned_row["file_size"]]
            if not compatible:
                continue

            def metadata_rank(row: dict) -> int:
                return sum(bool(row.get(field) and row.get(field) == tuned_row.get(field))
                           for field in ("ecu_family", "hardware_number", "software_number", "calibration_number"))

            compatible.sort(key=metadata_rank, reverse=True)
            ranked = []
            tuned_data = self.data(tuned_row["id"])
            for original_row in compatible[:max(limit_per_tuned * 4, 20)]:
                original_data = self.data(original_row["id"])
                evidence = compare(original_data, tuned_data, original_row, tuned_row,
                                   self.config["block_size"])
                if evidence["compatibility_confidence"] <= 0:
                    continue
                blocks = diff_blocks(original_data, tuned_data, self.config["diff_merge_gap"])
                ranked.append({"original_id": original_row["id"], "tuned_id": tuned_row["id"],
                               "confidence": evidence["compatibility_confidence"],
                               "match_score": evidence["match_score"],
                               "status": evidence["compatibility_status"],
                               "changed_regions": len(blocks), "evidence": evidence["reasons"]})
            for proposal in sorted(ranked, key=lambda item: (item["confidence"], item["match_score"]), reverse=True)[:limit_per_tuned]:
                self.pair(proposal["original_id"], proposal["tuned_id"], False, proposal["confidence"])
                proposals.append(proposal)
        return proposals

    def pairs(self) -> list[dict]:
        return self.db.rows("SELECT * FROM file_pairs ORDER BY id DESC")

    def confirm_pair(self, pair_id: int) -> None:
        with self.db.connect() as db:
            if not db.execute("UPDATE file_pairs SET confirmed=1 WHERE id=?", (pair_id,)).rowcount:
                raise ValueError("Onbekend pair-ID")

    def dashboard(self) -> dict:
        files = self.files()
        return {"Total Files": len(files), "Original Files": sum(f['file_type']=='original' for f in files),
                "Tuned Files": sum(f['file_type']=='tuned' for f in files), "WinOLS Projects": len(self.projects()), "Pairs": len(self.pairs()),
                "ECU Families": self.db.rows("SELECT COUNT(*) AS count FROM ecu_families WHERE verified=1")[0]["count"],
                "Software Versions": self.db.rows("SELECT COUNT(*) AS count FROM software_families WHERE verified=1")[0]["count"]}
