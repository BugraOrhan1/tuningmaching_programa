"""Read-only WinOLS project import facade.

Binary extraction is evidence-based: version binaries are only reported when
their boundaries are proven by an explicit import header or by an identity
header repeating at a constant stride. See ``ols_structure``.
"""
from __future__ import annotations

from pathlib import Path

from app.winols.ols_reader import inspect_ols, read_ols
from app.winols.ols_structure import parse_ols_structure


class OlsImporter:
    """Inspect and reconstruct OLS content without modifying its source."""

    def inspect_project(self, path: str | Path, max_file_mb: int = 64) -> dict:
        return inspect_ols(read_ols(path, max_file_mb))

    def extract_metadata(self, path: str | Path, max_file_mb: int = 64) -> dict:
        details = self.inspect_project(path, max_file_mb)
        return {
            "raw": details.get("tagged_metadata", {}),
            "suggested_type": details.get("suggested_type", "unknown"),
            "suggestion_reason": details.get("suggestion_reason"),
            "status": "available" if details.get("tagged_metadata") else "not_available",
        }

    def extract_files(self, path: str | Path, max_file_mb: int = 64) -> dict:
        """Report the binaries whose boundaries are proven by file evidence."""
        data = read_ols(path, max_file_mb)
        structure = parse_ols_structure(data)
        return {"status": "extracted" if structure["binaries"] else "unsupported",
                "binaries": structure["binaries"],
                "versions": structure["versions"],
                "reason": "" if structure["binaries"] else
                          "Geen bewezen binary-grenzen in dit bestand gevonden."}

    def extract_project_structure(self, path: str | Path, max_file_mb: int = 64) -> dict:
        data = read_ols(path, max_file_mb)
        details = inspect_ols(data)
        structure = parse_ols_structure(data)
        records = details.get("records", [])
        return {"status": "extracted" if structure["binaries"] else "partial",
                "objects": details.get("objects", []),
                "records": records,
                "structure": structure,
                "versions": [record for record in records if record["record_type"] == "version_or_role_label"],
                "maps": [record for record in records if record["record_type"] == "map_label"],
                "binary_evidence": details.get("forensic", {}).get("binary_evidence", []),
                "relationships": ("proven" if structure["version_binaries"] else "target_unknown"),
                "unsupported": structure["unknown_structures"]}

    def extract_available_calibration_information(self, path: str | Path, max_file_mb: int = 64) -> dict:
        data = read_ols(path, max_file_mb)
        structure = parse_ols_structure(data)
        return {"status": "candidates_observed" if structure["maps"] else "not_available",
                "maps": structure["maps"],
                "map_range": structure.get("map_range"),
                "reason": "Adressen, dimensies en factoren zijn waargenomen kandidaten uit "
                          "Kaart-records; geen gegarandeerde WinOLS-mapdefinitie."}