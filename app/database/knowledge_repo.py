"""V3-kennisopslag: regio's, patronen, alignments, evidence, jobs, zoeken.

Additieve mixin op de bestaande Repository; hergebruikt dezelfde SQLite-
database en verandert niets aan V2-gedrag.
"""
from __future__ import annotations

import json

REGION_FIELDS = (
    "pair_id", "seq", "start_offset", "end_offset", "length", "changed_byte_count",
    "changed_percentage", "original_bytes_hash", "tuned_bytes_hash", "before_context",
    "after_context", "original_context_hash", "original_region_context_hash",
    "tuned_context_hash", "relative_start", "relative_end", "structural_signature",
    "delta_signature", "structure_features", "entropy_before", "entropy_after",
    "region_class", "cross_pair_shared", "alignment_confidence", "map_confidence",
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
                 + (" WHERE p.confirmed=1" if confirmed_only else "")
                 + " ORDER BY r.pair_id, r.seq")
        rows = self.db.rows(query)
        for row in rows:
            row["structure_features"] = json.loads(row["structure_features"])
            row["evidence"] = json.loads(row["evidence"])
        return rows

    def mark_shared_regions(self, region_ids: list[int]) -> None:
        with self.db.connect() as db:
            db.executemany("UPDATE tuning_regions SET cross_pair_shared=1, "
                           "region_class='checksum_candidate', confidence=MIN(confidence,40.0) "
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
                          status=excluded.status, updated_at=CURRENT_TIMESTAMP""",
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

    def patterns_v3(self, status: str | None = None) -> list[dict]:
        query = "SELECT * FROM tuning_patterns"
        args: tuple = ()
        if status:
            query += " WHERE status=?"
            args = (status,)
        query += " ORDER BY frequency DESC, confidence DESC, id"
        rows = self.db.rows(query, args)
        for row in rows:
            row["payload"] = json.loads(row["payload"])
            row["members"] = self.db.rows(
                """SELECT m.*, r.start_offset, r.end_offset, r.region_class, r.stage,
                          r.software_number, r.ecu_family
                   FROM tuning_pattern_members m JOIN tuning_regions r ON r.id=m.region_id
                   WHERE m.pattern_id=?""", (row["id"],))
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
        with self.db.connect() as db:
            db.execute("""UPDATE analysis_runs SET checkpoint=?, stats=?, status='running',
                          updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                       (json.dumps(checkpoint), json.dumps(stats or {}), run_id))

    def finish_run(self, run_id: int, status: str = "done", stats: dict | None = None) -> None:
        with self.db.connect() as db:
            db.execute("""UPDATE analysis_runs SET status=?, stats=?, updated_at=CURRENT_TIMESTAMP
                          WHERE id=?""", (status, json.dumps(stats or {}), run_id))

    def resume_run(self, run_type: str) -> dict | None:
        rows = self.db.rows("""SELECT * FROM analysis_runs WHERE run_type=? AND status='interrupted'
                               ORDER BY id DESC LIMIT 1""", (run_type,))
        if not rows:
            return None
        rows[0]["checkpoint"] = json.loads(rows[0]["checkpoint"])
        rows[0]["stats"] = json.loads(rows[0]["stats"])
        rows[0]["config"] = json.loads(rows[0]["config"])
        return rows[0]

    def runs(self) -> list[dict]:
        return self.db.rows("SELECT * FROM analysis_runs ORDER BY id DESC LIMIT 100")

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
        return {"term": term, "files": files, "patterns": patterns,
                "winols_projects": projects, "regions": regions}
