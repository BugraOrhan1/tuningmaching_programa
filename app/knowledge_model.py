"""V6 kennismodel-laag: ECU Image Identity, Project Families, Software
Lineage, negatieve kennis, bewijsniveaus, provenance-contract en de
Golden Dataset-benchmark (master-spec punten 4/5/6/7/8/9/10/20).

Bewijsregels (onveranderd):
- UNKNOWN is een geldige uitkomst; niets wordt naar een match gedwongen.
- Identiteiten nooit op offset alleen; zelfde tabeltype ≠ zelfde calibratie.
- ECU Image Identity vereist inhoudelijk bewijs (sha, size+metadata+
  diffratio); metadata-only is nooit genoeg.
- Klant-/voertuigdata (readouts) hangen NIET mee in de matching.
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ALGORITHM_VERSION = "v6.0"

# §20: expliciete bewijsniveaus met rangschikking (hoger wint)
EVIDENCE_LEVELS = ("UNKNOWN", "INFERRED", "SOURCE_STRUCTURAL", "SOURCE_EXPLICIT",
                   "TECHNICIAN_CONFIRMED")
_LEVEL_RANK = {level: rank for rank, level in enumerate(EVIDENCE_LEVELS)}

# relatietypes software-lineage (§6)
LINEAGE_RELATIONS = ("SAME_CALIBRATION_FAMILY", "SOFTWARE_UPDATE", "DERIVATIVE",
                     "HARDWARE_VARIANT", "UNRELATED", "UNKNOWN")

# maximale bytes-afwijking binnen één ECU image (tuning-revisie van hetzelfde image)
IMAGE_DIFF_RATIO_MAX = 0.05


def best_evidence_level(*levels: str) -> str:
    """Hoogste bewijsniveau uit een set waarnemingen (§20-regel)."""
    return max((level for level in levels if level in _LEVEL_RANK),
               key=lambda level: _LEVEL_RANK[level], default="UNKNOWN")


class KnowledgeModelEngine:
    """Werkt direct op de gedeelde database; één waarheid voor alle importpaden
    (library, managed-copy, OLS-extract) via de bestaande files/project-tabellen."""

    def __init__(self, service):
        self.service = service
        self.repo = service.repo

    # ------------------------------------------------------------------
    # Provenance-contract (§7)
    # ------------------------------------------------------------------
    def provenance(self, parser_version: str | None = None,
                   extra: dict | None = None) -> dict:
        build = self.repo.active_knowledge_build()
        return {"algorithm_version": ALGORITHM_VERSION,
                "knowledge_build_id": build["id"] if build else None,
                "parser_version": parser_version,
                "generated_at": datetime.now().isoformat(),
                **(extra or {})}

    # ------------------------------------------------------------------
    # Negatieve kennis (§8): REJECTED MATCH is ook kennis
    # ------------------------------------------------------------------
    def register_negative(self, subject_type: str, a: tuple[str, str],
                          b: tuple[str, str], reason: str = "",
                          reviewer: str | None = None) -> dict:
        """Technicus zegt: A ≠ B. Structureel, uniek en permanent."""
        a_type, a_id = a
        b_type, b_id = b
        with self.repo.db.connect() as db:
            cursor = db.execute(
                """INSERT OR IGNORE INTO negative_relations
                   (subject_type,a_type,a_id,b_type,b_id,relation,reason,reviewer)
                   VALUES (?,?,?,?,?,'NOT_SAME',?,?)""",
                (subject_type, a_type, a_id, b_type, b_id, reason,
                 reviewer or "technician"))
            created = cursor.rowcount > 0
        self.repo.audit("register_negative", subject_type,
                        f"{a_id}|{b_id}", actor=reviewer or "technician",
                        after={"a": a_id, "b": b_id}, reason=reason)
        return {"registered": created, "subject_type": subject_type,
                "a": a_id, "b": b_id}

    def negative_pairs(self, subject_type: str) -> set[frozenset]:
        rows = self.repo.db.rows(
            "SELECT a_type,a_id,b_type,b_id FROM negative_relations WHERE subject_type=?",
            (subject_type,))
        return {frozenset({(row["a_type"], row["a_id"]), (row["b_type"], row["b_id"])})
                for row in rows}

    def is_negative(self, subject_type: str, a: tuple[str, str],
                    b: tuple[str, str]) -> bool:
        return frozenset({a, b}) in self.negative_pairs(subject_type)

    def negatives(self, subject_type: str | None = None) -> list[dict]:
        if subject_type:
            return self.repo.db.rows(
                "SELECT * FROM negative_relations WHERE subject_type=? ORDER BY id DESC",
                (subject_type,))
        return self.repo.db.rows("SELECT * FROM negative_relations ORDER BY id DESC")

    # ------------------------------------------------------------------
    # ECU Image Identity (§4)
    # ------------------------------------------------------------------
    def build_ecu_image_identities(self) -> dict:
        """Groepeer files naar ECU-image-identiteiten op aantoonbare inhoud:
        R1 exacte sha256 · R2 zelfde size+metadata+diffratio ≤ 5% ·
        R3 zelfde size zonder metadata (kandidaat). Grootteverschil binnen
        hetzelfde OLS-project → aparte identiteit + UNKNOWN-relatie met reden."""
        rows = self.repo.db.rows(
            """SELECT id, sha256, file_size, ecu_family, hardware_number,
                      software_number, calibration_number, source_path
               FROM files ORDER BY id""")
        parent = {row["id"]: row["id"] for row in rows}

        def find(node):
            while parent[node] != node:
                parent[node] = parent[parent[node]]
                node = parent[node]
            return node

        def union(left, right):
            parent[find(left)] = find(right)

        # R1: byte-identiek
        by_sha = defaultdict(list)
        for row in rows:
            by_sha[row["sha256"]].append(row["id"])
        for members in by_sha.values():
            for other in members[1:]:
                union(members[0], other)

        # R2/R3: zelfde size; metadata-tuple of diffratio als extra bewijs
        by_size = defaultdict(list)
        for row in rows:
            by_size[row["file_size"]].append(row)
        size_rule = {}
        for size, group in by_size.items():
            if len(group) < 2:
                continue
            for index, left in enumerate(group):
                for right in group[index + 1:]:
                    if find(left["id"]) == find(right["id"]):
                        continue
                    meta_left = (left["ecu_family"], left["hardware_number"],
                                 left["software_number"], left["calibration_number"])
                    meta_right = (right["ecu_family"], right["hardware_number"],
                                  right["software_number"], right["calibration_number"])
                    has_meta = any(meta_left) and any(meta_right)
                    if has_meta and meta_left != meta_right:
                        continue  # metadata zegt verschillende images: niet samenvoegen
                    ratio = self._diff_ratio(left["id"], right["id"])
                    if ratio is None or ratio > IMAGE_DIFF_RATIO_MAX:
                        continue
                    if has_meta:
                        size_rule[(left["id"], right["id"])] = "R2_size_meta_diff"
                    else:
                        size_rule[(left["id"], right["id"])] = "R3_size_diff"
                    union(left["id"], right["id"])

        groups = defaultdict(list)
        for row in rows:
            groups[find(row["id"])].append(row)

        with self.repo.db.connect() as db:
            db.execute("DELETE FROM ecu_image_members")
            db.execute("DELETE FROM ecu_image_identities")
        count = 0
        for members in groups.values():
            shas = {member["sha256"] for member in members}
            rules = sorted({rule for (left, right), rule in size_rule.items()
                            if left in {m["id"] for m in members}
                            or right in {m["id"] for m in members}}) or (
                ["R1_exact_sha256"] if len(members) > 1 else [])
            if len(members) > 1 and any(rule != "R1_exact_sha256" for rule in rules) \
                    and not rules:
                rules = ["R3_size_diff"]
            meta = members[0]
            if len(members) > 1:
                status = "SUPPORTED" if ("R1_exact_sha256" in rules
                                         or "R2_size_meta_diff" in rules) else "CANDIDATE"
                confidence = 100.0 if "R1_exact_sha256" in rules else (
                    90.0 if "R2_size_meta_diff" in rules else 70.0)
            else:
                status, confidence = "CANDIDATE", 40.0
            evidence = [{"rules": rules, "member_count": len(members),
                         "sha_variants": len(shas),
                         "levels": best_evidence_level("SOURCE_STRUCTURAL")}]
            with self.repo.db.connect() as db:
                cursor = db.execute(
                    """INSERT INTO ecu_image_identities(image_size,ecu_family,hardware,
                       software,calibration,status,confidence,evidence,algorithm_version)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (meta["file_size"], meta["ecu_family"], meta["hardware_number"],
                     meta["software_number"], meta["calibration_number"], status,
                     confidence, json.dumps(evidence), ALGORITHM_VERSION))
                image_id = cursor.lastrowid
                for member in members:
                    db.execute(
                        """INSERT OR IGNORE INTO ecu_image_members
                           (image_id,member_type,member_id,sha256,relation,confidence,evidence)
                           VALUES (?,?,?,?,?,?,?)""",
                        (image_id, "file", member["id"], member["sha256"],
                         "SAME_IMAGE", confidence, json.dumps(evidence)))
            count += 1

        # §4/artikel 2: grootteverschil binnen één OLS-project = expliciete
        # UNKNOWN-relatie met reden (geen geforceerde groepering)
        relations = self._record_image_size_relations(rows)
        return {"identities": count, "size_relations": len(relations),
                "algorithm_version": ALGORITHM_VERSION}

    def _diff_ratio(self, left_id: int, right_id: int) -> float | None:
        """Diffratio tussen twee files; None bij ontbrekende data of grote size."""
        try:
            left = self.repo.data(left_id)
            right = self.repo.data(right_id)
        except (OSError, ValueError):
            return None
        if not left or len(left) != len(right):
            return None
        changed = sum(1 for a, b in zip(left, right) if a != b)
        return changed / len(left)

    def _record_image_size_relations(self, rows: list[dict]) -> list[dict]:
        """Versies binnen één OLS-project met verschillende imagegrootte:
        registreer de relatie als UNKNOWN met gemeten reden (subset-check)."""
        with self.repo.db.connect() as db:
            db.execute("DELETE FROM software_lineage WHERE from_family LIKE 'image:%'")
        by_project = defaultdict(list)
        for row in rows:
            source = str(row["source_path"])
            if source.startswith("ols://"):
                # formaat: ols://<sha256>/v<index> → groepeer op project-deel
                project_ref = source.rsplit("/v", 1)[0] if "/v" in source else source
                by_project[project_ref].append(row)
        recorded = []
        for project_ref, group in by_project.items():
            if len({row["file_size"] for row in group}) < 2:
                continue
            for index, left in enumerate(group):
                for right in group[index + 1:]:
                    if left["file_size"] == right["file_size"]:
                        continue
                    small, big = ((left, right) if left["file_size"] < right["file_size"]
                                  else (right, left))
                    contained = self._contained_ratio(small["id"], big["id"])
                    reason = (f"size mismatch {small['file_size']} vs {big['file_size']} B; "
                              f"kleiner is GEEN subset van groter "
                              f"(blokgelijkheid {contained:.0%} < drempel)"
                              if contained < 0.9 else
                              f"size mismatch {small['file_size']} vs {big['file_size']} B; "
                              f"kleiner lijkt subset (blokgelijkheid {contained:.0%})")
                    self.repo.db.rows(
                        """INSERT INTO software_lineage(ecu_family,from_family,to_family,
                           relation,confidence,evidence,status)
                           VALUES (?,?,?,?,?,?,?)""",
                        ("UNKNOWN", f"image:{small['id']}", f"image:{big['id']}",
                         "UNKNOWN", 0.0,
                         json.dumps({"reason": reason, "project": project_ref,
                                     "algorithm_version": ALGORITHM_VERSION}),
                         "UNKNOWN"))
                    recorded.append(reason)
        return recorded

    def _contained_ratio(self, small_id: int, big_id: int) -> float:
        """Hoeveel 4KB-blokken van 'small' bestaan letterlijk in 'big' (subset-
        bewijs voor kleinschalige images; sampling bij grote)."""
        small = self.repo.data(small_id)
        big = self.repo.data(big_id)
        if not small or not big:
            return 0.0
        blocks = [small[offset:offset + 4096]
                  for offset in range(0, len(small), 4096)]
        if len(blocks) > 256:  # sampling: eerste/kleine subset representative
            step = len(blocks) / 256
            blocks = [blocks[int(index * step)] for index in range(256)]
        hits = sum(1 for block in blocks if block and block in big)
        return hits / max(1, len(blocks))

    # ------------------------------------------------------------------
    # Project Families (§5)
    # ------------------------------------------------------------------
    def build_project_families(self) -> dict:
        """Groepeer OLS-projecten in families op (ecu, software) uit de
        herkende metadata van hun versie-binaries. bewijs-gebaseerd."""
        projects = self.repo.projects()
        grouped = defaultdict(list)
        for project in projects:
            rows = self.repo.db.rows(
                """SELECT f.ecu_family, f.software_number FROM ols_version_binaries v
                   JOIN files f ON f.id=v.file_id WHERE v.project_id=?""",
                (project["id"],))
            ecu = next((row["ecu_family"] for row in rows if row["ecu_family"]), None)
            software = next((row["software_number"] for row in rows
                             if row["software_number"]), None)
            grouped[(ecu or "UNKNOWN", software or "UNKNOWN")].append(project["id"])
        with self.repo.db.connect() as db:
            db.execute("DELETE FROM project_family_members")
            db.execute("DELETE FROM project_families")
        count = 0
        for (ecu, software), project_ids in sorted(grouped.items()):
            evidence = [{"ecu": ecu, "software": software,
                         "projects": len(project_ids),
                         "level": "SOURCE_STRUCTURAL" if ecu != "UNKNOWN" else "UNKNOWN"}]
            with self.repo.db.connect() as db:
                cursor = db.execute(
                    """INSERT INTO project_families(name,ecu_family,software_family,
                       project_count,status,evidence) VALUES (?,?,?,?,?,?)""",
                    (f"ECU {ecu} / SW {software}", ecu, software,
                     len(project_ids), "CANDIDATE" if ecu != "UNKNOWN" else "UNKNOWN",
                     json.dumps(evidence)))
                for project_id in project_ids:
                    db.execute(
                        "INSERT OR IGNORE INTO project_family_members(family_id,project_id)"
                        " VALUES (?,?)", (cursor.lastrowid, project_id))
            count += 1
        return {"families": count, "algorithm_version": ALGORITHM_VERSION}

    # ------------------------------------------------------------------
    # Software Lineage (§6)
    # ------------------------------------------------------------------
    def build_software_lineage(self) -> dict:
        """Classificeer relaties tussen softwarefamilies van dezelfde ECU:
        SAME_CALIBRATION_FAMILY (gedeelde image-identiteit) > SOFTWARE_UPDATE
        (numerieke SW-increment) > HARDWARE_VARIANT (hw verschilt) > UNKNOWN.
        Zonder bewijs: UNKNOWN — nooit geforceerd."""
        families = self.repo.db.rows("SELECT * FROM project_families")
        by_ecu = defaultdict(list)
        for family in families:
            by_ecu[family["ecu_family"]].append(family)
        self.repo.db.rows("DELETE FROM software_lineage WHERE relation != 'UNKNOWN' "
                          "OR from_family LIKE 'image:%'")
        created = 0
        for ecu, group in by_ecu.items():
            if ecu == "UNKNOWN":
                continue
            for index, left in enumerate(group):
                for right in group[index + 1:]:
                    relation, confidence, evidence = self._classify_family_pair(left, right)
                    with self.repo.db.connect() as db:
                        db.execute(
                            """INSERT INTO software_lineage(ecu_family,from_family,
                               to_family,relation,confidence,evidence,status)
                               VALUES (?,?,?,?,?,?,?)""",
                            (ecu, left["name"], right["name"], relation, confidence,
                             json.dumps(evidence),
                             "SUPPORTED" if relation in ("SAME_CALIBRATION_FAMILY",
                                                         "SOFTWARE_UPDATE")
                             else ("CANDIDATE" if relation != "UNKNOWN" else "UNKNOWN")))
                    created += 1
        return {"lineage_relations": created, "algorithm_version": ALGORITHM_VERSION}

    def _classify_family_pair(self, left: dict, right: dict) -> tuple[str, float, list]:
        evidence = []
        shared = self._shared_image_identities(left["id"], right["id"])
        if shared:
            evidence.append({"kind": "shared_ecu_image_identities", "count": shared,
                             "level": "SOURCE_STRUCTURAL"})
            return "SAME_CALIBRATION_FAMILY", min(90.0, 60.0 + 10.0 * shared), evidence
        left_sw, right_sw = left["software_family"], right["software_family"]
        if (left_sw or "").isdigit() and (right_sw or "").isdigit():
            low, high = sorted((int(left_sw), int(right_sw)))
            if high == low + 1:
                evidence.append({"kind": "software_number_increment",
                                 "from": low, "to": high, "level": "SOURCE_EXPLICIT"})
                return "SOFTWARE_UPDATE", 55.0, evidence
        if left["software_family"] != right["software_family"]:
            # zelfde ECU, zelfde calibratieruimte-kenmerken, andere SW zonder
            # increment-bewijs: derivative-kandidaat, nooit fact
            evidence.append({"kind": "same_ecu_different_software",
                             "level": "SOURCE_STRUCTURAL"})
            return "DERIVATIVE", 40.0, evidence
        evidence.append({"kind": "insufficient_evidence", "level": "UNKNOWN"})
        return "UNKNOWN", 0.0, evidence

    def _shared_image_identities(self, family_a: int, family_b: int) -> int:
        rows = self.repo.db.rows(
            """SELECT m.image_id, COUNT(DISTINCT fm2.family_id) AS families
               FROM ecu_image_members m
               JOIN files f ON f.id = m.member_id
               JOIN ols_version_binaries v ON v.file_id = f.id
               JOIN project_family_members fm ON fm.project_id = v.project_id
               JOIN project_family_members fm2 ON fm2.family_id = fm.family_id
               WHERE fm2.family_id IN (?, ?)
               GROUP BY m.image_id HAVING families >= 2""", (family_a, family_b))
        return len(rows)

    # ------------------------------------------------------------------
    # Golden Dataset-benchmark (§9)
    # ------------------------------------------------------------------
    def evaluate_golden(self, save: bool = True, workspace=None) -> dict:
        """Draai de vaste kennis-cases (KNOWN SAME/DIFFERENT/ORIGINAL-TUNED/
        SAME-CAL-ACROSS-SW/DIFFERENT-CAL/CHECKSUM/MAP/UNKNOWN + echte OLS-case)
        en meet per categorie. Dit is de regressieanker voor engine-versies."""
        from tests.golden.cases import run_golden_cases
        report = run_golden_cases(self.service, workspace=workspace)
        if save:
            with self.repo.db.connect() as db:
                db.execute(
                    """INSERT INTO golden_runs(engine_version,totals,per_category,
                       skipped,notes) VALUES (?,?,?,?,?)""",
                    (ALGORITHM_VERSION, json.dumps(report["totals"]),
                     json.dumps(report["per_category"]),
                     json.dumps(report.get("skipped", [])),
                     report.get("notes", "")))
        report["provenance"] = self.provenance()
        return report

    def golden_history(self) -> list[dict]:
        return self.repo.db.rows("SELECT * FROM golden_runs ORDER BY id DESC LIMIT 50")

    # ------------------------------------------------------------------
    # Knowledge regression (§10)
    # ------------------------------------------------------------------
    def snapshot_knowledge(self) -> dict:
        """Vastleggen van álle huidige conclusies (voor algorithm-versie-
        vergelijking): patterns, identities, images, alignments, negatives."""
        patterns = [{"key": pattern["pattern_key"], "status": pattern["status"],
                     "confidence": pattern["confidence"],
                     "members": len(pattern["members"])}
                    for pattern in self.service.patterns_detail()]
        identities = []
        for item in self.repo.calibration_identities():
            signature = (item.get("structural_signature")
                         or item.get("signature") or item.get("identity_key")
                         or f"identity:{item['id']}")
            identities.append({"signature": signature, "status": item["status"],
                               "members": len(item["members"])})
        images = [{"size": row["image_size"], "status": row["status"],
                   "confidence": row["confidence"]}
                  for row in self.repo.db.rows("SELECT * FROM ecu_image_identities")]
        alignments = [{"source": row["source_file_id"], "target": row["target_file_id"],
                       "status": row["status"]}
                      for row in self.repo.db.rows("SELECT * FROM calibration_alignments")]
        negatives = [f"{row['a_id']}!={row['b_id']}"
                     for row in self.negatives()]
        return {"algorithm_version": ALGORITHM_VERSION,
                "taken_at": datetime.now().isoformat(),
                "patterns": patterns, "identities": identities, "images": images,
                "alignments": alignments, "negatives": negatives}

    @staticmethod
    def diff_knowledge_snapshots(before: dict, after: dict) -> dict:
        """Welke conclusies verdwenen/verschenen/veranderden; welke rejected
        matches zijn teruggekomen (§10)."""
        def keyset(records, fields):
            return {tuple(record[field] for field in fields): record
                    for record in records}

        old_patterns = keyset(before["patterns"], ("key",))
        new_patterns = keyset(after["patterns"], ("key",))
        old_ids = keyset(before["identities"], ("signature",))
        new_ids = keyset(after["identities"], ("signature",))
        return {
            "patterns_disappeared": sorted(set(old_patterns) - set(new_patterns)),
            "patterns_appeared": sorted(set(new_patterns) - set(old_patterns)),
            "patterns_changed": sorted(
                key for key in set(old_patterns) & set(new_patterns)
                if old_patterns[key]["status"] != new_patterns[key]["status"]
                or old_patterns[key]["confidence"] != new_patterns[key]["confidence"]),
            "identities_disappeared": sorted(set(old_ids) - set(new_ids)),
            "identities_appeared": sorted(set(new_ids) - set(old_ids)),
            "rejected_that_returned": sorted(
                key for key in set(old_ids) & set(new_ids)
                if old_ids[key]["status"] == "REJECTED"
                and new_ids[key]["status"] != "REJECTED"),
            "negatives_removed": sorted(set(before["negatives"])
                                        - set(after["negatives"])),
        }
