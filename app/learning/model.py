"""Rebuildable nearest-neighbor baseline over observed byte distributions."""
import json
from app.analysis.fingerprint import fingerprint


class LearningIndex:
    def __init__(self, repo):
        self.repo = repo

    def nearest(self, data: bytes, limit: int = 10) -> list[dict]:
        if limit < 1:
            raise ValueError("limit must be positive")
        from sklearn.neighbors import NearestNeighbors
        rows = self.repo.db.rows("SELECT f.id, f.filename, f.file_size, p.fingerprint_data FROM files f JOIN fingerprints p ON f.id=p.file_id WHERE f.file_type='original'")
        if not rows:
            return []
        vectors = [json.loads(r['fingerprint_data'])['histogram'] for r in rows]
        model = NearestNeighbors(n_neighbors=min(limit, len(rows)), metric='cosine').fit(vectors)
        distances, indices = model.kneighbors([fingerprint(data, self.repo.config['block_size'])['histogram']])
        return [{"file_id": rows[int(i)]['id'], "filename": rows[int(i)]['filename'],
                 "histogram_distance": float(d), "note": "Byteverdeling; geen compatibiliteitsscore"}
                for d, i in zip(distances[0], indices[0])]
