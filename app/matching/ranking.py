"""Explainable V2 matching score assembled from independently visible evidence."""
from __future__ import annotations


def _top_value(recognition: dict, group: str) -> str | None:
    items = recognition.get(group, [])
    return items[0]["value"] if items else None


def overall_score(binary: dict, query_recognition: dict, candidate_recognition: dict,
                  verified_signature_matches: int = 0) -> dict:
    components = {"binary_similarity": binary["match_score"]}
    labels = (("ecu", "ecu_compatibility"), ("hardware", "hardware_similarity"),
              ("software", "software_similarity"), ("calibration", "calibration_similarity"))
    reasons, warnings = [], []
    for group, name in labels:
        left, right = _top_value(query_recognition, group), _top_value(candidate_recognition, group)
        if left and right:
            components[name] = 100.0 if left == right else 0.0
            (reasons if left == right else warnings).append(
                f"{'Zelfde' if left == right else 'Verschillende'} {group}-identifier: {left}{'' if left == right else ' / ' + right}")
    weights = {"binary_similarity": 0.55, "ecu_compatibility": 0.20, "hardware_similarity": 0.10,
               "software_similarity": 0.10, "calibration_similarity": 0.05}
    present = {name: weights[name] for name in components}
    total_weight = sum(present.values())
    overall = sum(components[name] * present[name] for name in components) / total_weight
    if binary["compatibility_status"] == "incompatible_base":
        overall = min(overall, 20.0)
        warnings.append("Softwarebasis is incompatibel; bekende tuninggebieden zijn onderdrukt.")
    if verified_signature_matches:
        reasons.append(f"{verified_signature_matches} geverifieerde signatures matched")
    return {"overall_match_score": round(overall, 4), "score_components": components,
            "verified_signature_matches": verified_signature_matches, "match_reasons": reasons + binary["reasons"],
            "match_warnings": warnings}
