"""Unique JSON and CSV reports with a SHA256 manifest; no BIN generation."""
import csv
import hashlib
import json
import html
from pathlib import Path
from uuid import uuid4


def export_report(report: dict, folder: Path) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    stem = 'analysis_' + uuid4().hex
    output = folder / (stem + '.json')
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    csv_path = folder / (stem + '.csv')
    groups = [report] if 'blocks' in report else [known for match in report.get('matches', []) for known in match.get('known_changes', [])]
    with csv_path.open('x', newline='', encoding='utf-8-sig') as stream:
        writer = csv.writer(stream)
        writer.writerow(['pair_id', 'start_hex', 'end_exclusive_hex', 'length', 'changed_bytes', 'change_percentage'])
        for group in groups:
            for block in group['blocks']:
                writer.writerow([group.get('pair', {}).get('id', ''), hex(block['start_offset']), hex(block['end_offset']), block['length'],
                                 block['changed_bytes'], block['change_percentage']])
    manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (output, csv_path)}
    html_path = folder / (stem + '.html')
    rendered = html.escape(json.dumps(report, ensure_ascii=False, indent=2))
    with html_path.open('x', encoding='utf-8') as stream:
        stream.write("<!doctype html><meta charset='utf-8'><title>Tuning File AI Assistant report</title>"
                     "<style>body{font-family:system-ui;background:#111827;color:#e5e7eb;margin:2rem}pre{white-space:pre-wrap;background:#1f2937;padding:1rem;border-radius:8px}</style>"
                     "<h1>Tuning File AI Assistant report</h1><p>Read-only analysis. Verify in WinOLS before any work.</p><pre>" + rendered + "</pre>")
    manifest[html_path.name] = hashlib.sha256(html_path.read_bytes()).hexdigest()
    manifest_path = folder / (stem + '.sha256.json')
    with manifest_path.open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, indent=2)
    return {"json": str(output), "csv": str(csv_path), "html": str(html_path), "manifest": str(manifest_path)}
