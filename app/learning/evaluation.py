"""Deterministic evaluation of heuristic confidence scores."""
from __future__ import annotations


def evaluate_confidence(records: list[dict], threshold: float = 70.0) -> dict:
    """Evaluate labeled confidence records without claiming calibration as truth.

    Each record has ``score`` (0..100) and ``label`` (positive, negative, or
    ambiguous). Ambiguous records are reported but excluded from binary metrics.
    """
    if not 0 <= threshold <= 100:
        raise ValueError("threshold must be between 0 and 100")
    usable = []
    ambiguous = 0
    for record in records:
        label = str(record.get("label", "")).lower()
        score = float(record.get("score", -1))
        if label == "ambiguous":
            ambiguous += 1
            continue
        if label not in {"positive", "negative"} or not 0 <= score <= 100:
            raise ValueError("records require label positive/negative/ambiguous and score 0..100")
        usable.append((score / 100.0, label == "positive"))
    true_positive = sum(score >= threshold / 100 and label for score, label in usable)
    false_positive = sum(score >= threshold / 100 and not label for score, label in usable)
    false_negative = sum(score < threshold / 100 and label for score, label in usable)
    true_negative = sum(score < threshold / 100 and not label for score, label in usable)
    precision = true_positive / max(1, true_positive + false_positive)
    recall = true_positive / max(1, true_positive + false_negative)
    f1 = 2 * precision * recall / max(1e-12, precision + recall)
    brier = (sum((score - float(label)) ** 2 for score, label in usable) / len(usable)
             if usable else None)
    bins = []
    for lower in range(0, 100, 10):
        upper = lower + 10
        bucket = [(score, label) for score, label in usable
                  if lower / 100 <= score < upper / 100 or (upper == 100 and score == 1)]
        if bucket:
            bins.append({"lower": lower, "upper": upper,
                         "count": len(bucket),
                         "mean_score": round(sum(score for score, _ in bucket) / len(bucket) * 100, 2),
                         "positive_rate": round(sum(label for _, label in bucket) / len(bucket), 4)})
    return {
        "threshold": threshold,
        "sample_count": len(usable),
        "ambiguous_count": ambiguous,
        "true_positive": true_positive,
        "true_negative": true_negative,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "false_positive_rate": round(false_positive / max(1, false_positive + true_negative), 6),
        "false_negative_rate": round(false_negative / max(1, false_negative + true_positive), 6),
        "brier_score": round(brier, 6) if brier is not None else None,
        "calibration_bins": bins,
        "confidence_type": "STATISTICALLY_CALIBRATED_CONFIDENCE" if usable else "NOT_CALIBRATED",
        "note": "Metrics describe this labeled sample; they are not a universal probability guarantee.",
    }
