"""V3 Tuning Intelligence Engine: patronen, cross-software alignment,
mapdetection, New BIN-rapport en hervatbare jobs.

Alles analyse/kennis: geen enkele BIN wordt gewijzigd. Elke conclusie draagt
evidence + confidence; zonder bewijs blijft het UNKNOWN (zie EVIDENCE_MODEL.md).
"""
from __future__ import annotations

import bisect
import json
import math

import numpy as np

from app.analysis.alignment import align_regions
from app.analysis.similarity import compare
from app.analysis.tuning_region import (CONTEXT_BYTES, build_regions, entropy,
                                        mark_checksum_candidates, signature_similarity)

NEAR_PATTERN_THRESHOLD = 0.95          # deterministische near-merge drempel
CROSS_SOFTWARE_CONTEXT_WINDOW = 128    # bytes rond een regio voor contextvergelijking


def _windows(data: bytes, start: int, end: int) -> tuple[bytes, bytes]:
    return (data[max(0, start - CROSS_SOFTWARE_CONTEXT_WINDOW):start],
            data[end:end + CROSS_SOFTWARE_CONTEXT_WINDOW])


class ServiceV3Mixin:
    # ------------------------------------------------------------------
    # FASE 2/3: regio's en Tuning DNA
    # ------------------------------------------------------------------
    def regions(self, pair_id: int) -> dict:
        return {"pair_id": pair_id, "regions": self.repo.regions_for_pair(pair_id),
                "note": "Regio's zijn analyse; checksum-kandidaten zijn gemarkeerd en "
                        "worden nooit als tuninggebied gebruikt."}

    def region_detail(self, region_id: int) -> dict:
        region = self.repo.region(region_id)
        if region is None:
            raise ValueError("Onbekend regio-ID")
        related = self.repo.db.rows(
            "SELECT id, pair_id, start_offset, end_offset, region_class, stage "
            "FROM tuning_regions WHERE structural_signature=? AND id<>? LIMIT 50",
            (region["structural_signature"], region_id))
        patterns = self.repo.db.rows(
            """SELECT p.id, p.pattern_key, p.frequency, p.confidence, p.status
               FROM tuning_patterns p JOIN tuning_pattern_members m ON m.pattern_id=p.id
               WHERE m.region_id=?""", (region_id,))
        return {"region": region, "related_regions": related, "patterns": patterns}

    # ------------------------------------------------------------------
    # FASE 4: patroonclustering (deterministisch, hervatbaar)
    # ------------------------------------------------------------------
    def rebuild_patterns(self, batch_size: int = 25, resume: bool = False, progress=None) -> dict:
        """Gebouwde patronen zijn volledig deterministisch uit opgeslagen
        regio's; een onderbroken run gaat verder vanaf het checkpoint."""
        if batch_size < 1:
            raise ValueError("batch_size moet minimaal 1 zijn")
        run = self.repo.resume_run("pattern_rebuild") if resume else None
        run_id = run["id"] if run else self.repo.start_run("pattern_rebuild", {"batch_size": batch_size})
        last_pair = run["checkpoint"].get("last_pair_id", 0) if run else 0
        stats = dict(run["stats"]) if run else {"pairs": 0, "regions": 0, "errors": 0}
        pairs = [p for p in self.repo.pairs() if p["confirmed"] and p["id"] > last_pair]
        for index in range(0, len(pairs), batch_size):
            batch = pairs[index:index + batch_size]
            for pair in batch:
                try:
                    report = self.diff(pair["id"])
                    stats["pairs"] += 1
                    stats["regions"] += len(report["blocks"])
                except (OSError, ValueError):
                    stats["errors"] += 1
                if progress:
                    progress(f"Regio's {stats['pairs']}/{len(pairs)}")
            self.repo.checkpoint_run(run_id, {"last_pair_id": batch[-1]["id"]}, stats)

        regions = self.repo.all_candidate_regions(confirmed_only=True)
        # checksum-kandidaten eerst: zelfde relatieve plaats, >=3 paren,
        # >=2 ECU-families, onderling verschillende tuned-inhoud.
        groups: dict[tuple[float, int], list[dict]] = {}
        for region in regions:
            groups.setdefault((round(region["relative_start"], 3), region["length"]), []).append(region)
        shared_ids = []
        for members in groups.values():
            families = {member.get("ecu_family") or "unknown" for member in members}
            tuned_hashes = {member["tuned_bytes_hash"] for member in members}
            if len(members) >= 3 and len(families) >= 2 and len(tuned_hashes) >= 3:
                shared_ids.extend(member["id"] for member in members)
        self.repo.mark_shared_regions(shared_ids)
        stats["checksum_candidates"] = len(shared_ids)

        tunable = [region for region in regions if region["region_class"] not in
                   ("checksum_candidate", "padding")]
        self.repo.reset_pattern_members()
        cluster_groups: dict[tuple[str, str], list[dict]] = {}
        for region in tunable:
            family = region.get("ecu_family") or "unknown"
            cluster_groups.setdefault((family, region["structural_signature"]), []).append(region)
        accepted: list[dict] = []
        for key in sorted(cluster_groups):
            members = cluster_groups[key]
            features_list = [member["structure_features"] for member in members]
            reference = features_list[0]
            near = [candidate for candidate in accepted
                    if candidate["ecu_family"] == key[0]
                    and signature_similarity(candidate["reference_features"], reference)
                    >= NEAR_PATTERN_THRESHOLD]
            if near:
                target = near[0]
                target["members"].extend(members)
                target["signature_variants"].add(members[0]["structural_signature"])
                target["reference_features"] = reference  # laatste gemergd; deterministisch
                continue
            accepted.append({"ecu_family": key[0], "signature": key[1],
                             "signature_variants": {key[1]}, "members": list(members),
                             "reference_features": reference})

        pattern_count = 0
        for group in accepted:
            members = group["members"]
            project_ids = {member["pair_id"] for member in members}
            stages: dict[str, int] = {}
            for member in members:
                stage = member.get("stage") or "unknown"
                stages[stage] = stages.get(stage, 0) + 1
            software_variants = sorted({member.get("software_number") or "unknown"
                                        for member in members})
            deltas = [member["structure_features"]["delta_summary"] for member in members]
            up = sum(delta.get("sign_up", 0) for delta in deltas)
            down = sum(delta.get("sign_down", 0) for delta in deltas)
            dominant_up = up >= down
            contradicting = sum(
                1 for delta in deltas
                if (delta.get("sign_up", 0) >= delta.get("sign_down", 0)) is not dominant_up
                and max(delta.get("sign_up", 0), delta.get("sign_down", 0), 1) >= 3)
            pairwise = []
            feature_list = [member["structure_features"] for member in members[:50]]
            for i, left in enumerate(feature_list):
                for right in feature_list[i + 1:]:
                    pairwise.append(signature_similarity(left, right))
            structural_similarity = round(100 * (sum(pairwise) / len(pairwise)) if pairwise else 100.0, 2)
            typical_delta = {"mean_delta": round(sum(d.get("mean_delta", 0.0) for d in deltas)
                                                 / max(1, len(deltas)), 3),
                             "up": up, "down": down}
            projects = len(project_ids)
            confidence = round(max(50.0, min(95.0, 50.0 + 15.0 * math.log2(1 + projects))
                                   - 10.0 * (1 if contradicting else 0)), 2)
            payload = {
                "ecu_family": group["ecu_family"],
                "structural_signature": group["signature"],
                "signature_variants": sorted(group["signature_variants"]),
                "confirmed_projects": projects,
                "observed_regions": len(members),
                "software_variants": software_variants,
                "stages": stages,
                "structural_similarity": structural_similarity,
                "typical_delta": typical_delta,
                "contradictions": contradicting,
                "note": "Structuurpatroon uit bevestigde paren; geen mapnaam, geen "
                        "tuninginstructie.",
            }
            pattern_key = f"v3:{group['ecu_family']}:{group['signature'][:24]}"
            pattern_id = self.repo.upsert_pattern(pattern_key, payload, projects, confidence)
            self.repo.replace_pattern_members(pattern_id, [
                {"region_id": member["id"], "pair_id": member["pair_id"],
                 "similarity": round(100 * signature_similarity(
                     group["reference_features"], member["structure_features"]), 2)}
                for member in members])
            pattern_count += 1
            if progress:
                progress(f"Patronen {pattern_count}")
        stats["patterns"] = pattern_count
        self.repo.finish_run(run_id, "done", stats)
        return {"run_id": run_id, "patterns": pattern_count, **stats}

    def patterns_detail(self, status: str | None = None) -> list[dict]:
        return self.repo.patterns_v3(status)

    def review_pattern(self, pattern_id: int, action: str, reviewer: str | None = None,
                       note: str = "") -> dict:
        return self.repo.review_knowledge("tuning_pattern", pattern_id, action, reviewer, note)

    def review_region(self, region_id: int, action: str, reviewer: str | None = None,
                      note: str = "", payload: dict | None = None) -> dict:
        if action in {"mark_checksum", "mark_calibration", "mark_code", "mark_unknown"}:
            klass = {"mark_checksum": "checksum_candidate", "mark_calibration": "calibration_region",
                     "mark_code": "unknown", "mark_unknown": "unknown"}[action]
            with self.repo.db.connect() as db:
                db.execute("UPDATE tuning_regions SET region_class=?, status='reviewed' WHERE id=?",
                           (klass, region_id))
        return self.repo.review_knowledge("tuning_region", region_id, action, reviewer, note, payload)

    # ------------------------------------------------------------------
    # FASE 5: cross-software alignment
    # ------------------------------------------------------------------
    def align_pattern_across_software(self, pattern_id: int, block_size: int = 64) -> dict:
        """Breng één patroon over softwarevarianten heen in kaart.

        Methode: exacte blok-run-alignment (bestaande align_regions) tussen de
        originals van verschillende leden, daarna contextvergelijking rond de
        gemapte positie. Absolute offsets zijn uitkomst, geen invoer.
        """
        pattern = self.repo.pattern(pattern_id)
        if not pattern:
            raise ValueError("Onbekend patroon-ID")
        member_regions = pattern["members"]
        per_file: dict[int, list[dict]] = {}
        for member in member_regions:
            pair = next((p for p in self.repo.pairs() if p["id"] == member["pair_id"]), None)
            if not pair:
                continue
            per_file.setdefault(pair["original_file_id"], []).append(member)
        file_info = {file_id: self.repo.file(file_id) for file_id in per_file}
        results = []
        file_ids = sorted(per_file)
        for s_index, source_id in enumerate(file_ids):
            try:
                source_data = self.repo.data(source_id)
            except (OSError, ValueError):
                continue
            for target_id in file_ids[s_index + 1:]:
                source_meta, target_meta = file_info[source_id], file_info[target_id]
                if (source_meta.get("software_number") and target_meta.get("software_number")
                        and source_meta["software_number"] == target_meta["software_number"]):
                    continue  # zelfde software: geen cross-software-alignering
                try:
                    target_data = self.repo.data(target_id)
                except (OSError, ValueError):
                    continue
                runs = [(run["source_start"], run["target_start"], run["length"])
                        for run in align_regions(source_data, target_data, block_size, 1)
                        if run["method"] == "exact_structural_block_run"]
                run_starts = [run[0] for run in runs]

                def map_offset(position: int) -> int | None:
                    index = bisect.bisect_right(run_starts, position) - 1
                    if index < 0:
                        return None
                    s_start, t_start, length = runs[index]
                    if position >= s_start + length:
                        return None
                    return t_start + (position - s_start)

                mappings: dict[int, int] = {}
                for member in per_file[source_id]:
                    mapped = map_offset(member["start_offset"])
                    if mapped is None:
                        continue
                    previous = mappings.get(member["region_id"])
                    if previous is not None and abs(previous - mapped) > 512:
                        continue  # contradictie wordt beneden geteld
                    mappings[member["region_id"]] = mapped
                positions = sorted(mappings.values())
                for member in per_file[source_id]:
                    mapped = mappings.get(member["region_id"])
                    supporting = sum(1 for position in positions if abs(position - (mapped or 0)) <= 512)
                    contradicting = 0
                    if mapped is not None:
                        contradicting = sum(1 for region_id, position in mappings.items()
                                            if region_id != member["id"]
                                            and abs(position - mapped) > 512)
                    evidence = [{"type": "block_run_alignment", "runs": len(runs),
                                 "method": "exact_structural_block_run"}]
                    context_similarity = 0.0
                    if mapped is not None:
                        s_before, s_after = _windows(source_data, member["start_offset"], member["end_offset"])
                        t_before, t_after = _windows(target_data, mapped,
                                                     mapped + member["length"])
                        parts = [compare(s_before, t_before, {}, {})["match_score"] if s_before and t_before else None,
                                 compare(s_after, t_after, {}, {})["match_score"] if s_after and t_after else None]
                        present = [value for value in parts if value is not None]
                        context_similarity = round(sum(present) / len(present), 3) if present else 0.0
                        evidence.append({"type": "context_similarity", "value": context_similarity,
                                         "window": CROSS_SOFTWARE_CONTEXT_WINDOW})
                    support_projects = len({m["pair_id"] for m in per_file[source_id]})
                    if mapped is None:
                        alignment_confidence = 0.0
                        status = "unknown"
                        evidence.append({"type": "no_block_run",
                                         "note": "Geen bewezen blok-run tussen deze softwarevarianten."})
                    else:
                        alignment_confidence = round(min(95.0, 0.4 * 100.0
                                                         + 0.3 * context_similarity
                                                         + 0.3 * min(100.0, support_projects / 3 * 100.0)
                                                         - 10.0 * min(2, contradicting)), 2)
                        status = "candidate"
                    results.append(self.repo.add_alignment({
                        "pattern_id": pattern_id, "source_file_id": source_id,
                        "target_file_id": target_id,
                        "source_software": source_meta.get("software_number"),
                        "target_software": target_meta.get("software_number"),
                        "source_start": member["start_offset"], "source_end": member["end_offset"],
                        "target_start": mapped,
                        "target_end": (mapped + member["length"]) if mapped is not None else None,
                        "structural_similarity": member.get("similarity", 100.0),
                        "alignment_confidence": alignment_confidence,
                        "evidence_count": len(evidence), "supporting_projects": support_projects,
                        "supporting_signatures": len(pattern["payload"]["signature_variants"]),
                        "contradicting_evidence": contradicting,
                        "evidence": evidence, "status": status}))
        offsets_by_software: dict[str, list[int]] = {}
        for alignment in self.repo.alignments_for_pattern(pattern_id):
            if alignment["target_start"] is not None:
                key = alignment["target_software"] or f"sha:{alignment['target_file_id']}"
                offsets_by_software.setdefault(key, []).append(alignment["target_start"])
        return {"pattern_id": pattern_id, "alignments_created": len(results),
                "offsets_by_software": {key: sorted(set(values))
                                        for key, values in offsets_by_software.items()},
                "note": "Alignering is evidence-verzameling, geen bewijs dat de gebieden "
                        "dezelfde functie hebben."}

    def find_pattern_matches(self, query: bytes, threshold: float = 70.0,
                             max_patterns: int = 50) -> list[dict]:
        """Zoek bekende structuurpatronen in een nieuwe (original) BIN.

        Per patroon worden maximaal 8 bron-originals via blok-runs op de query
        uitgelijnd; de context rond de gemapte regio bepaalt de score.
        """
        if not 50 <= threshold <= 100:
            raise ValueError("Drempel moet tussen 50 en 100 liggen")
        patterns = self.repo.patterns_v3()[:max_patterns]
        matches = []
        for pattern in patterns:
            best = None
            source_files: dict[int, list[dict]] = {}
            for member in pattern["members"]:
                pair_rows = self.repo.db.rows(
                    "SELECT original_file_id FROM file_pairs WHERE id=?", (member["pair_id"],))
                if pair_rows:
                    source_files.setdefault(pair_rows[0]["original_file_id"], []).append(member)
            for source_id, members in list(source_files.items())[:8]:
                try:
                    source_data = self.repo.data(source_id)
                except (OSError, ValueError):
                    continue
                runs = [(run["source_start"], run["target_start"], run["length"])
                        for run in align_regions(source_data, query, 64, 1)
                        if run["method"] == "exact_structural_block_run"]
                run_starts = [run[0] for run in runs]

                def map_offset(position: int) -> int | None:
                    index = bisect.bisect_right(run_starts, position) - 1
                    if index < 0:
                        return None
                    s_start, t_start, length = runs[index]
                    if position >= s_start + length:
                        return None
                    return t_start + (position - s_start)

                for member in members:
                    mapped = map_offset(member["start_offset"])
                    if mapped is None:
                        continue
                    s_before, s_after = _windows(source_data, member["start_offset"], member["end_offset"])
                    q_before, q_after = _windows(query, mapped, mapped + member["length"])
                    parts = [compare(s_before, q_before, {}, {})["match_score"] if s_before and q_before else None,
                             compare(s_after, q_after, {}, {})["match_score"] if s_after and q_after else None]
                    present = [value for value in parts if value is not None]
                    if not present:
                        continue
                    context_similarity = sum(present) / len(present)
                    if context_similarity < threshold:
                        continue
                    candidate = {"pattern_id": pattern["id"],
                                 "pattern_key": pattern["pattern_key"],
                                 "stage": pattern["payload"].get("stages"),
                                 "confirmed_projects": pattern["payload"]["confirmed_projects"],
                                 "context_similarity": round(context_similarity, 3),
                                 "query_offset": mapped,
                                 "source_file_id": source_id,
                                 "source_offset": member["start_offset"],
                                 "region_length": member["length"],
                                 "region_class": member.get("region_class"),
                                 "pattern_confidence": pattern["confidence"],
                                 "evidence_count": 2,
                                 "note": "Context-overeenkomst na blok-run-alignment; "
                                         "geen mapnaam."}
                    if best is None or candidate["context_similarity"] > best["context_similarity"]:
                        best = candidate
            if best:
                matches.append(best)
        return sorted(matches, key=lambda item: -item["context_similarity"])

    # ------------------------------------------------------------------
    # FASE mapdetection: structuurherkenning zonder naamgeving
    # ------------------------------------------------------------------
    def detect_map_structures(self, file_id: int, max_scan: int = 1 << 20,
                              step: int = 64) -> dict:
        """Deterministische 1D/2D-structuurkandidaten. MAP DETECTION ≠ MAP
        NAMING: alleen 'axis_candidate'/'table_candidate' met gedocumenteerde
        criteria; zonder bewijs blijft map_type 'unknown'."""
        data = self.repo.data(file_id)
        scan = data[:max_scan]
        structures = []

        def monotone(sequence: np.ndarray) -> bool:
            differences = np.diff(sequence.astype(np.int64))
            return bool((differences >= 0).all() and (differences > 0).any())

        for window in (8, 16, 32):
            for position in range(0, len(scan) - window * 2, step):
                segment = scan[position:position + window * 2]
                arr = np.frombuffer(segment, dtype=np.uint8)
                if monotone(arr):
                    for element_size in (1, 2):
                        values = arr[0:window * 2]
                        if element_size == 2:
                            values = (np.frombuffer(segment, dtype=np.uint8)[0::2].astype(np.int64)
                                      + 256 * np.frombuffer(segment, dtype=np.uint8)[1::2].astype(np.int64))[:window]
                            if len(values) >= 8 and monotone(values[:8]):
                                structures.append({
                                    "start_offset": position, "end_offset": position + window * 2,
                                    "map_type": "axis_candidate",
                                    "map_confidence": round(min(90.0, 60.0 + window * 0.75), 2),
                                    "dimensions": [window], "element_size": 2,
                                    "payload": {"ordering": "observed_high_byte_second",
                                                "criteria": "monotone reeks over 8+ elementen"},
                                    "status": "candidate"})
                                break
                        else:
                            structures.append({
                                "start_offset": position, "end_offset": position + window * 2,
                                "map_type": "axis_candidate",
                                "map_confidence": round(min(90.0, 60.0 + window * 0.75), 2),
                                "dimensions": [window * 2], "element_size": 1,
                                "payload": {"criteria": "monotone reeks over 8+ elementen"},
                                "status": "candidate"})
                            break
                if len(structures) >= 200:
                    break
            if len(structures) >= 200:
                break
        # 2D-tabelkandidaat: rijen met gelijke periode die qua vorm op elkaar lijken
        for period in (8, 12, 16, 24, 32, 48, 64):
            for position in range(0, min(len(scan) - period * 6, 256 * 1024), step):
                rows = [np.frombuffer(scan[position + i * period:
                                                position + (i + 1) * period],
                                      dtype=np.uint8) for i in range(5)]
                pairs_ok = 0
                for row_a, row_b in zip(rows, rows[1:]):
                    equal = int((row_a == row_b).sum())
                    if equal / period >= 0.9:
                        pairs_ok += 1
                if pairs_ok >= 4:
                    structures.append({
                        "start_offset": position, "end_offset": position + period * 5,
                        "map_type": "table_candidate",
                        "map_confidence": round(min(90.0, 55.0 + pairs_ok * 5.0), 2),
                        "dimensions": [5, period], "element_size": 1,
                        "payload": {"criteria": "5 opeenvolgende rijen >=90% gelijk "
                                                "op periode " + str(period)},
                        "status": "candidate"})
                    break
            if len(structures) >= 400:
                break
        # binnen dezelfde 64-byte gridcel maximaal één kandidaat
        deduped: dict[int, dict] = {}
        for structure in structures:
            cell = structure["start_offset"] // 64
            if cell not in deduped or structure["map_confidence"] > deduped[cell]["map_confidence"]:
                deduped[cell] = structure
        final = sorted(deduped.values(), key=lambda item: item["start_offset"])
        self.repo.replace_file_map_regions(file_id, final)
        return {"file_id": file_id, "structures": len(final),
                "scan_limit_bytes": max_scan,
                "note": "Structuurkandidaten zonder functie of naam; tabelassen zijn "
                        "niet geverifieerd."}

    # ------------------------------------------------------------------
    # FASE 7: New BIN Analysis
    # ------------------------------------------------------------------
    def new_bin_report(self, file_id: int, threshold: float = 70.0) -> dict:
        file_row = self.repo.file(file_id)
        query = self.repo.data(file_id)
        analysis = self.analyze(file_row["filepath"])
        best = analysis["matches"][0] if analysis["matches"] else None
        pattern_matches = self.find_pattern_matches(query, threshold)
        structures = self.detect_map_structures(file_id)
        related_projects = sorted({pair["id"] for match in analysis["matches"]
                                   for pair in match["pairs"]})
        components = {
            "binary_similarity": best["match_score"] if best else 0.0,
            "pattern_confidence": pattern_matches[0]["pattern_confidence"] if pattern_matches else 0.0,
            "context_alignment": pattern_matches[0]["context_similarity"] if pattern_matches else 0.0,
            "structural_similarity": best.get("structural_similarity", 0.0) if best else 0.0,
        }
        weights = {name: value for name, value in
                   {"binary_similarity": 0.4, "pattern_confidence": 0.25,
                    "context_alignment": 0.2, "structural_similarity": 0.15}.items()
                   if components[name] > 0}
        overall = round(sum(components[name] * weights[name] for name in weights)
                        / sum(weights.values()), 2) if weights else 0.0
        identification = analysis.get("identification", {})
        return {
            "file_id": file_id, "filename": file_row["filename"],
            "identification": identification,
            "ecu_family": next((item["value"] for item in identification.get("ecu", [])[:1]), "UNKNOWN"),
            "software_family": next((item["value"] for item in identification.get("software", [])[:1]), "UNKNOWN"),
            "calibration_family": next((item["value"] for item in identification.get("calibration", [])[:1]), "UNKNOWN"),
            "related_projects": len(related_projects),
            "related_originals": [{"file_id": match["file_id"], "filename": match["filename"],
                                   "structural_similarity": match["match_score"],
                                   "software_compatibility": match["compatibility_confidence"],
                                   "compatibility_status": match["compatibility_status"]}
                                  for match in analysis["matches"][:10]],
            "tuning_dna_matches": pattern_matches,
            "map_structures": self.repo.map_regions_for_file(file_id)[:100],
            "score_components": components,
            "score_weights": weights,
            "overall_confidence": overall,
            "evidence_summary": {
                "confirmed_pairs": len(related_projects),
                "patterns_considered": len(pattern_matches),
                "top_pattern": pattern_matches[0]["pattern_id"] if pattern_matches else None,
                "contradictions": sum(1 for match in analysis["matches"]
                                      if match.get("metadata_conflicts")),
                "note": "Alle onderliggende scores zijn zichtbaar; overall is een "
                        "gedocumenteerd gewogen gemiddelde, geen zwarte doos."},
            "note": "Analyse-only rapport; er is geen BIN gewijzigd.",
        }

    # ------------------------------------------------------------------
    # FASE 9: hervatbare job-wrapper
    # ------------------------------------------------------------------
    def run_pattern_job(self, resume: bool = True, progress=None) -> dict:
        return self.rebuild_patterns(resume=resume, progress=progress)

    def jobs(self) -> list[dict]:
        return self.repo.runs()

    def search(self, term: str) -> dict:
        return self.repo.search(term)

    # ------------------------------------------------------------------
    # FASE 6: OLS project graph
    # ------------------------------------------------------------------
    def ols_graph(self, project_id: int) -> dict:
        project = self.repo.project(project_id)
        if not project:
            raise ValueError("Onbekend project-ID")
        versions = self.repo.ols_versions(project_id)
        binaries = self.repo.db.rows("SELECT * FROM ols_binaries WHERE project_id=?", (project_id,))
        references = self.repo.db.rows(
            "SELECT * FROM ols_version_relations WHERE project_id=?", (project_id,))
        record_types = self.repo.db.rows(
            "SELECT record_type, COUNT(*) AS count FROM ols_records WHERE project_id=? "
            "GROUP BY record_type ORDER BY count DESC", (project_id,))
        unknown_relations = []
        nodes = [{"type": "project", "id": project_id, "name": project["filename"]}]
        edges = []
        for version in versions:
            label = version["version_name"] or f"naamloos (index {version['version_index']})"
            nodes.append({"type": "version", "id": f"v{version['version_index']}", "name": label,
                          "role": version["role"], "role_confidence": version["role_confidence"]})
            edges.append({"from": f"project:{project_id}",
                          "to": f"version:v{version['version_index']}",
                          "relation": version["relation_type"],
                          "confidence": version["relation_confidence"]})
            if version["relation_type"] in ("target_unknown", "binary_without_version"):
                unknown_relations.append({"version": label,
                                          "reason": version["relation_evidence"] or "geen bewezen relatie"})
            if version["file_id"]:
                nodes.append({"type": "file", "id": version["file_id"],
                              "name": f"file {version['file_id']}",
                              "sha256": version["binary_sha256"]})
                edges.append({"from": f"version:v{version['version_index']}",
                              "to": f"file:{version['file_id']}", "relation": "extracted_binary",
                              "confidence": version["role_confidence"]})
        for binary in binaries:
            nodes.append({"type": "ols_binary", "id": f"bin:{binary['internal_id']}",
                          "offset": binary["offset"], "length": binary["length"],
                          "status": binary["status"]})
            edges.append({"from": f"project:{project_id}",
                          "to": f"bin:{binary['internal_id']}", "relation": "contains",
                          "confidence": binary["confidence"]})
        return {"project": {"id": project_id, "filename": project["filename"],
                            "sha256": project["sha256"]},
                "nodes": nodes, "edges": edges,
                "record_types": record_types,
                "proven_relations": len(references),
                "unknown_relationships": unknown_relations,
                "note": "Relaties zonder bewijs staan expliciet als UNKNOWN; niets is "
                        "automatisch gekoppeld."}

