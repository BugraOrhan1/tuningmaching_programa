"""Group observed changes by relative location and size, without map labels."""
import math


def feature(block: dict, file_size: int) -> list[float]:
    return [block['start_offset'] / max(1, file_size),
            math.log2(1 + block['length']) / 32, block['change_percentage'] / 100]


def cluster_changes(records: list[dict]) -> list[dict]:
    if not records:
        return []
    from sklearn.cluster import DBSCAN
    labels = DBSCAN(eps=.045, min_samples=1).fit_predict([r['features'] for r in records])
    groups = {}
    for record, label in zip(records, labels):
        groups.setdefault(int(label), []).append(record)
    return [{"name": f"Change cluster {label+1}", "members": members,
             "pair_count": len({r['pair_id'] for r in members}),
             "meaning": "Possible calibration region; alleen locatie/grootte/dichtheid gegroepeerd"}
            for label, members in groups.items()]


def compare_strategies(reports: list[dict]) -> dict:
    """Compare literal overlap only; differing software remains unverified."""
    comparisons = []
    for i, a in enumerate(reports):
        for b in reports[i+1:]:
            intersections = []
            for x in a['blocks']:
                for y in b['blocks']:
                    start, end = max(x['start_offset'], y['start_offset']), min(x['end_offset'], y['end_offset'])
                    if start < end:
                        intersections.append({"start_offset": start, "end_offset": end})
            comparisons.append({"pair_a": a['pair']['id'], "pair_b": b['pair']['id'],
                                "overlap_regions": intersections,
                                "regions_a": a['blocks'], "regions_b": b['blocks'],
                                "same_original_sha256": a['original_sha256'] == b['original_sha256']})
    return {"comparisons": comparisons, "note": "Offsetoverlap bewijst geen gelijke mapfunctie of tuningstrategie."}
