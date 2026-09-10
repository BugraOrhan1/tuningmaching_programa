"""Bounded-memory ranking over the configured candidate pool.

Large libraries are prefiltered by stored fingerprints, so the report must
expose that shortlist rather than implying every original was byte-compared.
"""
import heapq
from pathlib import Path
from app.analysis.binary_reader import read_binary
from app.analysis.fingerprint import hashes
from app.analysis.metadata import extract_metadata
from app.analysis.recognition import recognize
from app.analysis.similarity import compare
from app.analysis.fingerprint import fingerprint
from app.matching.ranking import overall_score


def find_matches(repo, path: str, progress=None, query_data: bytes | None = None) -> dict:
    query = read_binary(path, repo.config['max_file_mb']) if query_data is None else query_data
    metadata = extract_metadata(query)
    query_recognition = recognize(query)
    originals, hierarchy = repo.prefilter_originals(fingerprint(query, repo.config['block_size']), query_recognition)
    heap, errors = [], []
    pairs = repo.pairs()
    for index, row in enumerate(originals):
        try:
            score = compare(query, repo.data(row['id']), metadata, row, repo.config['block_size'])
            candidate_recognition = repo.recognition(row['id'])
            explanation = overall_score(score, query_recognition, candidate_recognition,
                                        repo.verified_signature_matches(query, row['id']))
            result = {"file_id": row['id'], "filename": row['filename'], **score, **explanation,
                      "pairs": [p for p in pairs if p['original_file_id'] == row['id']]}
            item = (explanation['overall_match_score'], score['compatibility_confidence'], -row['id'], result)
            heapq.heappush(heap, item)
            if len(heap) > repo.config['top_matches']:
                heapq.heappop(heap)
        except (OSError, ValueError) as exc:
            errors.append({"file_id": row['id'], "error": str(exc)})
        if progress:
            progress(f"Analyse {index+1}/{len(originals)}: {row['filename']}")
    ranked = [r[3] for r in sorted(heap, reverse=True)]
    high_confidence = [match for match in ranked if match["overall_match_score"] >= 60 and match["compatibility_status"] != "incompatible_base"]
    return {"filename": Path(path).name, "file_size": len(query), **hashes(query),
            "metadata": metadata, "identification": query_recognition, "hierarchy": hierarchy,
            "matches": ranked, "outlier": not bool(high_confidence),
            "outlier_warning": ("NO HIGH-CONFIDENCE MATCH: dit bestand past onvoldoende bij de bekende database."
                                if not high_confidence else None),
            "errors": errors, "searched": len(originals),
            "note": "Scores bewijzen geen ECU-compatibiliteit. Controleer in WinOLS."}
