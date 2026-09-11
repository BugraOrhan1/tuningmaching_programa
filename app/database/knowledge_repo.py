"""V3-kennisopslag: regio's, patronen, alignments, evidence, jobs, zoeken.

Additieve mixin op de bestaande Repository; hergebruikt dezelfde SQLite-
database en verandert niets aan V2-gedrag.
"""
from __future__ import annotations

import json
import hashlib
import math

REGION_FIELDS = (
    "pair_id", "seq", "start_offset", "end_offset", "length", "changed_byte_count",
    "changed_percentage", "original_bytes_hash", "tuned_bytes_hash", "before_context",
    "after_context", "original_context_hash", "original_region_context_hash",
    "tuned_context_hash", "relative_start", "relative_end", "structural_signature",
    "delta_signature", "structure_features", "entropy_before", "entropy_after",
    "region_class", "checksum_status", "cross_pair_shared", "alignment_confidence", "map_confidence",
    "map_type", "stage", "ecu_family", "software_number", "calibration_number",
    "hardware_number", "project", "evidence", "confidence", "status")


class RepositoryV3Mixin:
    # ---------- tuning_regions ----------
    def replace_pair_regions(self, pair_id: int, regions: list[dict]) -> list[int]:
        with self.db.connect() as db:
            db.execute("DELETE FROM tuning_regions WHERE pair_id=?", (pair_id,))
            ids = []
            for region in regions:
                values = []
                for field in REGION_FIELDS:
                    raw = pair_id if field == "pair_id" else region.get(field)
                    if field in ("structure_features", "evidence"):
                        raw = json.dumps(raw, ensure_ascii=False, sort_keys=True)
                    elif field == "cross_pair_shared":
                        raw = int(bool(raw))
                    values.append(raw)
                cursor = db.execute(
                    f"INSERT INTO tuning_regions ({','.join(REGION_FIELDS)}) "
                    f"VALUES ({','.join('?' for _ in REGION_FIELDS)})", tuple(values))
                ids.append(cursor.lastrowid)
        return ids

    def regions_for_pair(self, pair_id: int) -> list[dict]:
        rows = self.db.rows("SELECT * FROM tuning_regions WHERE pair_id=? ORDER BY seq, start_offset",
                            (pair_id,))
        for row in rows:
            row["structure_features"] = json.loads(row["structure_features"])
            row["evidence"] = json.loads(row["evidence"])
        return rows

    def region(self, region_id: int) -> dict | None:
        rows = self.db.rows("SELECT * FROM tuning_regions WHERE id=?", (region_id,))
        if not rows:
            return None
        rows[0]["structure_features"] = json.loads(rows[0]["structure_features"])
        rows[0]["evidence"] = json.loads(rows[0]["evidence"])
        return rows[0]

    def all_candidate_regions(self, confirmed_only: bool = True) -> list[dict]:
        query = ("SELECT r.* FROM tuning_regions r JOIN file_pairs p ON p.id=r.pair_id"
                 + (" WHERE p.confirmed=1 AND r.status <> 'rejected'" if confirmed_only
                    else " WHERE r.status <> 'rejected'")
                 + " ORDER BY r.pair_id, r.seq")
        rows = self.db.rows(query)
        for row in rows:
            row["structure_features"] = json.loads(row["structure_features"])
            row["evidence"] = json.loads(row["evidence"])
        return rows

    def mark_shared_regions(self, region_ids: list[int]) -> None:
        with self.db.connect() as db:
            db.executemany("UPDATE tuning_regions SET cross_pair_shared=1, "
                           "region_class='checksum_candidate', checksum_status='CHECKSUM_CANDIDATE', "
                           "confidence=MIN(confidence,40.0) "
                           "WHERE id=?", [(int(i),) for i in region_ids])

    def set_region_map_evidence(self, region_id: int, map_type: str, map_confidence: float,
                                evidence_entry: dict) -> None:
        region = self.region(region_id)
        evidence = region["evidence"] + [evidence_entry]
        with self.db.connect() as db:
            db.execute("UPDATE tuning_regions SET map_type=?, map_confidence=?, evidence=? WHERE id=?",
                       (map_type, map_confidence, json.dumps(evidence, ensure_ascii=False), region_id))

    # ---------- patterns & members ----------
    def upsert_pattern(self, pattern_key: str, payload: dict, frequency: int,
                       confidence: float, status: str = "candidate") -> int:
        with self.db.connect() as db:
            db.execute("""INSERT INTO tuning_patterns(pattern_key,payload,frequency,confidence,status)
                          VALUES (?,?,?,?,?)
                          ON CONFLICT(pattern_key) DO UPDATE SET payload=excluded.payload,
                          frequency=excluded.frequency, confidence=excluded.confidence,
                          status=CASE WHEN tuning_patterns.status IN ('verified','rejected')
                                      THEN tuning_patterns.status ELSE excluded.status END,
                          updated_at=CURRENT_TIMESTAMP""",
                       (pattern_key, json.dumps(payload, ensure_ascii=False), frequency,
                        confidence, status))
            return db.execute("SELECT id FROM tuning_patterns WHERE pattern_key=?",
                              (pattern_key,)).fetchone()["id"]

    def replace_pattern_members(self, pattern_id: int, members: list[dict]) -> None:
        with self.db.connect() as db:
            db.execute("DELETE FROM tuning_pattern_members WHERE pattern_id=?", (pattern_id,))
            db.executemany(
                "INSERT OR IGNORE INTO tuning_pattern_members(pattern_id,region_id,pair_id,similarity) "
                "VALUES (?,?,?,?)",
                [(pattern_id, m["region_id"], m["pair_id"], m.get("similarity", 100.0)) for m in members])

    @staticmethod
    def _recompute_pattern_stats(db, pattern_id: int, base_payload: dict) -> tuple[dict, int, float]:
        """Herbouw payload/statistieken/confidence uit de huidige leden.

        Confidence-formule (gedocumenteerd in EVIDENCE_MODEL.md):
        clamp(50 + 15*log2(1+confirmed_projects), 50, 95). Heuristisch,
        geen statistische kalibratie.
        """
        members = db.execute("""SELECT r.stage, r.software_number
            FROM tuning_pattern_members m JOIN tuning_regions r ON r.id=m.region_id
            WHERE m.pattern_id=?""", (pattern_id,)).fetchall()
        counts = db.execute("""SELECT COUNT(*), COUNT(DISTINCT pair_id)
            FROM tuning_pattern_members WHERE pattern_id=?""", (pattern_id,)).fetchone()
        payload = dict(base_payload)
        payload["observed_regions"] = counts[0]
        payload["confirmed_projects"] = counts[1]
        payload["stages"] = dict(sorted(
            {((row["stage"] or "unknown")): 0 for row in members}.items())) if members else {}
        for row in members:
            stage = row["stage"] or "unknown"
            payload["stages"][stage] = payload["stages"].get(stage, 0) + 1
        payload["software_variants"] = sorted({(row["software_number"] or "unknown") for row in members})
        confidence = round(max(50.0, min(95.0, 50.0 + 15.0 * math.log2(1 + counts[1]))), 2)
        return payload, counts[1], confidence

    def merge_patterns(self, source_id: int, target_id: int) -> dict:
        if source_id == target_id:
            raise ValueError("Een pattern kan niet met zichzelf worden gemerged")
        source = self.pattern(source_id)
        target = self.pattern(target_id)
        if not source or not target:
            raise ValueError("Onbekend pattern-ID voor merge")
        with self.db.connect() as db:
            db.executemany("""INSERT OR IGNORE INTO tuning_pattern_members
                (pattern_id,region_id,pair_id,similarity) VALUES (?,?,?,?)""",
                           [(target_id, row["region_id"], row["pair_id"], row["similarity"])
                            for row in source["members"]])
            payload, projects, confidence = self._recompute_pattern_stats(
                db, target_id, dict(target["payload"]))
            payload["merged_pattern_ids"] = sorted(set(payload.get("merged_pattern_ids", [])) | {source_id})
            db.execute("""UPDATE tuning_patterns SET payload=?, frequency=?, confidence=?,
                status='candidate', updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                       (json.dumps(payload, ensure_ascii=False), projects, confidence, target_id))
            # stale kennis van het bronpattern weg: leden zijn verhuisd
            db.execute("DELETE FROM software_alignments WHERE pattern_id=?", (source_id,))
            db.execute("DELETE FROM tuning_pattern_members WHERE pattern_id=?", (source_id,))
            db.execute("UPDATE tuning_patterns SET status='rejected', frequency=0, "
                       "updated_at=CURRENT_TIMESTAMP WHERE id=?", (source_id,))
        return {"source_pattern_id": source_id, "target_pattern_id": target_id,
                "members": payload["observed_regions"], "projects": projects,
                "confidence": confidence, "status": "rebuilt"}

    def split_pattern(self, pattern_id: int, region_ids: list[int]) -> dict:
        pattern = self.pattern(pattern_id)
        selected = set(region_ids)
        if not pattern or not selected:
            raise ValueError("Pattern en region_ids zijn verplicht voor split")
        members = [row for row in pattern["members"] if row["region_id"] in selected]
        if not members or len(members) == len(pattern["members"]):
            raise ValueError("Split vereist een niet-lege, niet-volledige memberselectie")
        split_key = "split:{}:{}".format(pattern_id, hashlib.sha256(
            ",".join(str(value) for value in sorted(selected)).encode()).hexdigest()[:16])
        payload = dict(pattern["payload"])
        payload["split_from_pattern_id"] = pattern_id
        with self.db.connect() as db:
            db.execute("""INSERT INTO tuning_patterns
                (pattern_key,payload,frequency,confidence,status) VALUES (?,?,?,?,?)""",
                       (split_key, json.dumps(payload, ensure_ascii=False), 0,
                        pattern["confidence"], "candidate"))
            split_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.executemany("""INSERT INTO tuning_pattern_members
                (pattern_id,region_id,pair_id,similarity) VALUES (?,?,?,?)""",
                           [(split_id, row["region_id"], row["pair_id"], row["similarity"])
                            for row in members])
            db.executemany("DELETE FROM tuning_pattern_members WHERE pattern_id=? AND region_id=?",
                           [(pattern_id, row["region_id"]) for row in members])
            split_payload, split_projects, split_confidence = self._recompute_pattern_stats(
                db, split_id, payload)
            db.execute("""UPDATE tuning_patterns SET payload=?, frequency=?, confidence=?,
                updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                       (json.dumps(split_payload, ensure_ascii=False), split_projects,
                        split_confidence, split_id))
            remaining_payload, remaining_projects, remaining_confidence = self._recompute_pattern_stats(
                db, pattern_id, dict(pattern["payload"]))
            db.execute("""UPDATE tuning_patterns SET payload=?, frequency=?, confidence=?,
                updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                       (json.dumps(remaining_payload, ensure_ascii=False), remaining_projects,
                        remaining_confidence, pattern_id))
        return {"source_pattern_id": pattern_id, "split_pattern_id": split_id,
                "moved_regions": len(members), "confidence": split_confidence,
                "status": "rebuilt"}

    def patterns_v3(self, status: str | None = None) -> list[dict]:
        query = "SELECT * FROM tuning_patterns"
        args: tuple = ()
        if status:
            query += " WHERE status=?"
            args = (status,)
        else:
            query += " WHERE status <> 'rejected'"
        query += " ORDER BY frequency DESC, confidence DESC, id"
        rows = self.db.rows(query, args)
        for row in rows:
            row["payload"] = json.loads(row["payload"])
            row["members"] = self.db.rows(
                """SELECT m.*, r.start_offset, r.end_offset, r.length, r.region_class,
                          r.stage, r.software_number, r.ecu_family, r.structural_signature
                   FROM tuning_pattern_members m JOIN tuning_regions r ON r.id=m.region_id
                   WHERE m.pattern_id=? AND r.status <> 'rejected'""", (row["id"],))
            row["alignments"] = self.db.rows(
                "SELECT * FROM software_alignments WHERE pattern_id=?", (row["id"],))
        return rows

    def pattern(self, pattern_id: int) -> dict | None:
        rows = [row for row in self.patterns_v3() if row["id"] == pattern_id]
        return rows[0] if rows else None

    def reset_pattern_members(self) -> None:
        with self.db.connect() as db:
            db.execute("DELETE FROM tuning_pattern_members")
            db.execute("DELETE FROM software_alignments")

    # ---------- software alignments ----------
    def add_alignment(self, row: dict) -> int:
        with self.db.connect() as db:
            cursor = db.execute("""INSERT INTO software_alignments
                (pattern_id,source_file_id,target_file_id,source_software,target_software,
                 source_start,source_end,target_start,target_end,structural_similarity,
                 alignment_confidence,evidence_count,supporting_projects,supporting_signatures,
                 contradicting_evidence,method,evidence,status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (row.get("pattern_id"), row.get("source_file_id"), row.get("target_file_id"),
                 row.get("source_software"), row.get("target_software"),
                 row.get("source_start"), row.get("source_end"),
                 row.get("target_start"), row.get("target_end"),
                 row.get("structural_similarity", 0.0), row.get("alignment_confidence", 0.0),
                 row.get("evidence_count", 0), row.get("supporting_projects", 0),
                 row.get("supporting_signatures", 0), row.get("contradicting_evidence", 0),
                 row.get("method", "structural_signature"),
                 json.dumps(row.get("evidence", []), ensure_ascii=False),
                 row.get("status", "candidate")))
            return cursor.lastrowid

    def alignments_for_pattern(self, pattern_id: int) -> list[dict]:
        rows = self.db.rows("SELECT * FROM software_alignments WHERE pattern_id=?", (pattern_id,))
        for row in rows:
            row["evidence"] = json.loads(row["evidence"])
        return rows

    # ---------- map structures ----------
    def replace_file_map_regions(self, file_id: int, structures: list[dict]) -> None:
        with self.db.connect() as db:
            db.execute("DELETE FROM map_regions WHERE file_id=?", (file_id,))
            db.executemany("""INSERT INTO map_regions
                (file_id,start_offset,end_offset,map_type,map_confidence,dimensions,element_size,payload,status)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                [(file_id, s["start_offset"], s["end_offset"], s["map_type"], s["map_confidence"],
                  json.dumps(s.get("dimensions")), s.get("element_size"),
                  json.dumps(s.get("payload", {}), ensure_ascii=False), s.get("status", "candidate"))
                 for s in structures])

    def map_regions_for_file(self, file_id: int) -> list[dict]:
        rows = self.db.rows("SELECT * FROM map_regions WHERE file_id=? ORDER BY start_offset",
                            (file_id,))
        for row in rows:
            row["dimensions"] = json.loads(row["dimensions"]) if row["dimensions"] else None
            row["payload"] = json.loads(row["payload"])
        return rows

    def replace_calibration_objects(self, file_id: int, objects: list[dict]) -> None:
        """Replace derived calibration candidates while preserving source files."""
        with self.db.connect() as db:
            db.execute("DELETE FROM calibration_objects WHERE file_id=?", (file_id,))
            db.executemany("""INSERT INTO calibration_objects
                (file_id,map_region_id,object_key,ecu_family,hardware,software_family,
                 calibration_family,dimensions,data_type,element_size,endian,row_count,
                 column_count,axis_count,axis_signature,surrounding_signature,
                 internal_pattern_signature,neighboring_regions,value_statistics,entropy,
                 context_hashes,relative_layout,structural_signature,detection_confidence,
                 evidence,status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [(file_id, item.get("map_region_id"), item["object_key"], item.get("ecu_family"),
                  item.get("hardware"), item.get("software_family"), item.get("calibration_family"),
                  json.dumps(item.get("dimensions")), item.get("data_type", "UNKNOWN"),
                  item.get("element_size"), item.get("endian", "UNKNOWN"), item.get("row_count"),
                  item.get("column_count"), item.get("axis_count", 0), item.get("axis_signature", "UNKNOWN"),
                  item.get("surrounding_signature", "UNKNOWN"), item.get("internal_pattern_signature", "UNKNOWN"),
                  json.dumps(item.get("neighboring_regions", [])), json.dumps(item.get("value_statistics", {})),
                  item.get("entropy"), json.dumps(item.get("context_hashes", {})),
                  json.dumps(item.get("relative_layout", {})), item["structural_signature"],
                  item.get("detection_confidence", 0.0), json.dumps(item.get("evidence", []), ensure_ascii=False),
                  item.get("status", "candidate")) for item in objects])

    def calibration_objects_for_file(self, file_id: int) -> list[dict]:
        rows = self.db.rows("SELECT * FROM calibration_objects WHERE file_id=? ORDER BY id", (file_id,))
        for row in rows:
            for field in ("dimensions", "neighboring_regions", "value_statistics", "context_hashes",
                          "relative_layout", "evidence"):
                row[field] = json.loads(row[field]) if row[field] else None
        return rows

    def calibration_identities(self) -> list[dict]:
        rows = self.db.rows("SELECT * FROM calibration_identities ORDER BY confidence DESC, id")
        for row in rows:
            for field in ("software_variants", "supporting_evidence", "contradicting_evidence"):
                row[field] = json.loads(row[field]) if row[field] else []
            row["members"] = self.db.rows(
                "SELECT * FROM calibration_identity_members WHERE identity_id=? ORDER BY id",
                (row["id"],))
        return rows

    def calibration_identity(self, identity_id: int) -> dict | None:
        rows = self.db.rows("SELECT * FROM calibration_identities WHERE id=?", (identity_id,))
        if not rows:
            return None
        row = rows[0]
        for field in ("software_variants", "supporting_evidence", "contradicting_evidence"):
            row[field] = json.loads(row[field]) if row[field] else []
        row["members"] = self.db.rows(
            "SELECT * FROM calibration_identity_members WHERE identity_id=? ORDER BY id",
            (identity_id,))
        return row

    def review_calibration_identity(self, identity_id: int, action: str,
                                    reviewer: str | None = None, note: str = "",
                                    payload: dict | None = None) -> dict:
        statuses = {"approve": "SUPPORTED", "verify": "VERIFIED", "reject": "REJECTED",
                    "mark_unknown": "UNKNOWN"}
        if action not in set(statuses) | {"correct"}:
            raise ValueError("Ongeldige Calibration Identity-reviewactie")
        identity = self.calibration_identity(identity_id)
        if identity is None:
            raise ValueError("Onbekende Calibration Identity")
        new_status = statuses.get(action)
        with self.db.connect() as db:
            db.execute("""INSERT INTO knowledge_reviews
                (subject_type,subject_id,action,payload,reviewer,note)
                VALUES (?,?,?,?,?,?)""",
                       ("calibration_identity", str(identity_id), action,
                        json.dumps(payload or {}, ensure_ascii=False), reviewer, note))
            if new_status:
                db.execute("""UPDATE calibration_identities
                    SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                           (new_status, identity_id))
                db.execute("""UPDATE calibration_identity_members SET status=?
                    WHERE identity_id=?""", (new_status, identity_id))
        return {"identity": self.calibration_identity(identity_id), "action": action,
                "reviewer": reviewer, "note": note}

    # ---------- evidence ----------
    def add_evidence(self, subject_type: str, subject_id: str, evidence_type: str, value: str,
                     offset: int | None = None, confidence: float = 0.0,
                     status: str = "observed", source: str = "analysis") -> int:
        with self.db.connect() as db:
            cursor = db.execute("""INSERT INTO evidence
                (subject_type,subject_id,evidence_type,value,offset,confidence,status,source)
                VALUES (?,?,?,?,?,?,?,?)""",
                (subject_type, str(subject_id), evidence_type, value, offset, confidence, status, source))
            return cursor.lastrowid

    def evidence_for(self, subject_type: str, subject_id: str) -> list[dict]:
        return self.db.rows("SELECT * FROM evidence WHERE subject_type=? AND subject_id=?"
                            " ORDER BY confidence DESC, id", (subject_type, str(subject_id)))

    def link_evidence(self, evidence_id: int, relation_type: str, target_type: str,
                      target_id: str, confidence: float = 100.0) -> None:
        with self.db.connect() as db:
            db.execute("""INSERT INTO evidence_relations
                (evidence_id,relation_type,target_type,target_id,confidence) VALUES (?,?,?,?,?)""",
                (evidence_id, relation_type, target_type, str(target_id), confidence))

    # ---------- knowledge reviews ----------
    def review_knowledge(self, subject_type: str, subject_id: str, action: str,
                         reviewer: str | None = None, note: str = "",
                         payload: dict | None = None) -> dict:
        if action not in {"approve", "reject", "correct", "merge", "split", "mark_unknown",
                          "mark_checksum", "mark_calibration", "mark_code", "change_stage",
                          "correct_relation"}:
            raise ValueError("Ongeldige review-actie")
        with self.db.connect() as db:
            db.execute("""INSERT INTO knowledge_reviews
                (subject_type,subject_id,action,payload,reviewer,note) VALUES (?,?,?,?,?,?)""",
                (subject_type, str(subject_id), action,
                 json.dumps(payload or {}, ensure_ascii=False), reviewer, note))
            if subject_type == "tuning_pattern" and action in {"approve", "reject"}:
                db.execute("UPDATE tuning_patterns SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                           ("verified" if action == "approve" else "rejected", int(subject_id)))
            if subject_type == "tuning_region" and action in {"approve", "reject"}:
                db.execute("UPDATE tuning_regions SET status=? WHERE id=?",
                           ("verified" if action == "approve" else "rejected", int(subject_id)))
        self.audit(action, subject_type, subject_id, actor=reviewer or "technician",
                   after={"payload": payload or {}, "note": note}, reason=note)
        return {"subject_type": subject_type, "subject_id": subject_id, "action": action,
                "note": note, "reviewer": reviewer}

    def knowledge_history(self, subject_type: str | None = None) -> list[dict]:
        query = "SELECT * FROM knowledge_reviews"
        args: tuple = ()
        if subject_type:
            query += " WHERE subject_type=?"
            args = (subject_type,)
        return self.db.rows(query + " ORDER BY id DESC", args)

    # ---------- analysis runs (checkpoints) ----------
    def start_run(self, run_type: str, config: dict | None = None) -> int:
        with self.db.connect() as db:
            cursor = db.execute("INSERT INTO analysis_runs(run_type,config) VALUES (?,?)",
                                (run_type, json.dumps(config or {})))
            return cursor.lastrowid

    def checkpoint_run(self, run_id: int, checkpoint: dict, stats: dict | None = None) -> None:
        """Checkpoint schrijven; een tussentijdse pauze/annulering blijft staan."""
        with self.db.connect() as db:
            db.execute("""UPDATE analysis_runs SET checkpoint=?, stats=?,
                          status=CASE WHEN status IN ('paused','cancelled','cancel_requested',
                                                      'done','interrupted')
                                      THEN status ELSE 'running' END,
                          updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                       (json.dumps(checkpoint), json.dumps(stats or {}), run_id))

    def finish_run(self, run_id: int, status: str = "done", stats: dict | None = None) -> None:
        with self.db.connect() as db:
            db.execute("""UPDATE analysis_runs SET status=?, stats=?, updated_at=CURRENT_TIMESTAMP
                          WHERE id=?""", (status, json.dumps(stats or {}), run_id))

    def resume_run(self, run_type: str) -> dict | None:
        rows = self.db.rows("""SELECT * FROM analysis_runs WHERE run_type=? AND status IN
                               ('interrupted','paused')
                               ORDER BY id DESC LIMIT 1""", (run_type,))
        if not rows:
            return None
        rows[0]["checkpoint"] = json.loads(rows[0]["checkpoint"])
        rows[0]["stats"] = json.loads(rows[0]["stats"])
        rows[0]["config"] = json.loads(rows[0]["config"])
        return rows[0]

    def runs(self) -> list[dict]:
        return self.db.rows("SELECT * FROM analysis_runs ORDER BY id DESC LIMIT 100")

    def run(self, run_id: int) -> dict | None:
        rows = self.db.rows("SELECT * FROM analysis_runs WHERE id=?", (run_id,))
        if rows:
            rows[0]["checkpoint"] = json.loads(rows[0]["checkpoint"])
            rows[0]["stats"] = json.loads(rows[0]["stats"])
            rows[0]["config"] = json.loads(rows[0]["config"])
        return rows[0] if rows else None

    def run_status(self, run_id: int) -> str:
        rows = self.db.rows("SELECT status FROM analysis_runs WHERE id=?", (run_id,))
        return rows[0]["status"] if rows else "unknown"

    def pause_run(self, run_id: int, checkpoint: dict, stats: dict | None = None) -> None:
        """Checkpoint wegschrijven en de run PAUZEERD achterlaten."""
        with self.db.connect() as db:
            db.execute("""UPDATE analysis_runs SET checkpoint=?, stats=?, status='paused',
                          updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                       (json.dumps(checkpoint), json.dumps(stats or {}), run_id))

    def cancel_run(self, run_id: int, stats: dict | None = None) -> None:
        self.finish_run(run_id, "cancelled", stats)

    def reopen_run(self, run_id: int) -> None:
        """Gepauzeerde/onderbroken run heropenen bij hervat (§51)."""
        with self.db.connect() as db:
            db.execute("""UPDATE analysis_runs SET status='running',
                          updated_at=CURRENT_TIMESTAMP WHERE id=?""", (run_id,))

    def audit(self, action: str, subject_type: str, subject_id, actor: str = "technician",
              before=None, after=None, reason: str = "") -> None:
        """Auditlog (§63): elke technicus-actie traceerbaar en backupbaar."""
        with self.db.connect() as db:
            db.execute("""INSERT INTO audit_log(actor,action,subject_type,subject_id,
                before_state,after_state,reason) VALUES (?,?,?,?,?,?,?)""",
                       (actor, action, subject_type, str(subject_id),
                        json.dumps(before or {}, ensure_ascii=False, default=str),
                        json.dumps(after or {}, ensure_ascii=False, default=str), reason))

    def audit_log(self, limit: int = 200, subject_type: str | None = None) -> list[dict]:
        if subject_type:
            return self.db.rows("""SELECT * FROM audit_log WHERE subject_type=?
                ORDER BY id DESC LIMIT ?""", (subject_type, limit))
        return self.db.rows("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))

    def create_knowledge_build(self, source_run_id: int | None, source_projects: int,
                               pattern_count: int, calibration_identity_count: int,
                               config_version: str = "v1", notes: str = "") -> int:
        with self.db.connect() as db:
            db.execute("UPDATE knowledge_builds SET status='SUPERSEDED' WHERE status='ACTIVE'")
            cursor = db.execute("""INSERT INTO knowledge_builds
                (source_run_id,source_projects,pattern_count,calibration_identity_count,
                 config_version,notes) VALUES (?,?,?,?,?,?)""",
                (source_run_id, source_projects, pattern_count, calibration_identity_count,
                 config_version, notes))
            return cursor.lastrowid

    def knowledge_builds(self) -> list[dict]:
        return self.db.rows("SELECT * FROM knowledge_builds ORDER BY id DESC")

    def active_knowledge_build(self) -> dict | None:
        rows = self.db.rows("SELECT * FROM knowledge_builds WHERE status='ACTIVE' ORDER BY id DESC LIMIT 1")
        return rows[0] if rows else None

    def save_confidence_evaluation(self, metrics: dict) -> int:
        with self.db.connect() as db:
            cursor = db.execute("""INSERT INTO confidence_evaluations
                (threshold,sample_count,ambiguous_count,precision,recall,f1,
                 false_positive_rate,false_negative_rate,brier_score,metrics)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (metrics["threshold"], metrics["sample_count"], metrics["ambiguous_count"],
                 metrics["precision"], metrics["recall"], metrics["f1"],
                 metrics["false_positive_rate"], metrics["false_negative_rate"],
                 metrics["brier_score"], json.dumps(metrics, ensure_ascii=False)))
            return cursor.lastrowid

    def confidence_evaluations(self) -> list[dict]:
        rows = self.db.rows("SELECT * FROM confidence_evaluations ORDER BY id DESC")
        for row in rows:
            row["metrics"] = json.loads(row["metrics"])
        return rows

    # ---------- search ----------
    def search(self, term: str, limit: int = 25) -> dict:
        term = (term or "").strip()
        if not term:
            raise ValueError("Lege zoekterm")
        like = f"%{term}%"
        files = self.db.rows(
            """SELECT id, filename, file_type, file_size, sha256, ecu_family, hardware_number,
                      software_number, calibration_number, vehicle_make, vehicle_model,
                      engine_code, transmission, stage, project
               FROM files WHERE filename LIKE ? OR sha256 LIKE ? OR md5 LIKE ?
                  OR ecu_family LIKE ? OR hardware_number LIKE ? OR software_number LIKE ?
                  OR calibration_number LIKE ? OR vehicle_make LIKE ? OR vehicle_model LIKE ?
                  OR engine_code LIKE ? OR transmission LIKE ? OR stage LIKE ? OR project LIKE ?
               ORDER BY id LIMIT ?""",
            (like, like, like, like, like, like, like, like, like, like, like, like, like, limit))
        patterns = self.db.rows(
            """SELECT id, pattern_key, frequency, confidence, status, payload
               FROM tuning_patterns WHERE pattern_key LIKE ? OR payload LIKE ?
               ORDER BY frequency DESC LIMIT ?""", (like, like, limit))
        for pattern in patterns:
            pattern["payload"] = json.loads(pattern["payload"])
        projects = self.db.rows(
            """SELECT id, filename, file_size, sha256, project_metadata FROM winols_projects
               WHERE filename LIKE ? OR sha256 LIKE ? OR project_metadata LIKE ? LIMIT ?""",
            (like, like, like, limit))
        regions = self.db.rows(
            """SELECT id, pair_id, start_offset, end_offset, region_class, structural_signature
               FROM tuning_regions WHERE structural_signature LIKE ? OR delta_signature LIKE ?
               OR region_class LIKE ? LIMIT ?""", (like, like, like, limit))
        identities = self.db.rows(
            """SELECT id, identity_key, ecu_family, structural_signature, software_variants,
                      confidence, status
               FROM calibration_identities
               WHERE identity_key LIKE ? OR ecu_family LIKE ? OR structural_signature LIKE ?
                  OR software_variants LIKE ? OR status LIKE ?
               ORDER BY confidence DESC LIMIT ?""",
            (like, like, like, like, like, limit))
        for identity in identities:
            identity["software_variants"] = json.loads(identity["software_variants"])
        evidence = self.db.rows(
            """SELECT id, subject_type, subject_id, evidence_type, value, confidence, status, source
               FROM evidence WHERE subject_type LIKE ? OR subject_id LIKE ? OR evidence_type LIKE ?
                  OR value LIKE ? OR status LIKE ? OR source LIKE ?
               ORDER BY confidence DESC LIMIT ?""",
            (like, like, like, like, like, like, limit))
        builds = self.db.rows(
            """SELECT id, status, source_projects, pattern_count, calibration_identity_count,
                      config_version, notes FROM knowledge_builds
               WHERE status LIKE ? OR config_version LIKE ? OR notes LIKE ?
               ORDER BY id DESC LIMIT ?""", (like, like, like, limit))
        return {"term": term, "files": files, "patterns": patterns,
                "winols_projects": projects, "regions": regions,
                "calibration_identities": identities, "evidence": evidence,
                "knowledge_builds": builds}
