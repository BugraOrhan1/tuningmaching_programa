"""Rapportexport (§62): JSON / CSV / Markdown / HTML voor elk kennisrapport.

Exporteurs zijn puur conventies over bestaande rapport-dicts: geen nieuwe
analyse, geen interpretatie — exact dezelfde evidence als in de GUI/API.
"""
from __future__ import annotations

import csv
import html
import io
import json
from datetime import datetime
from pathlib import Path

FORMATS = ("json", "csv", "md", "html")


def _flat_rows(value):
    """Grootste list-of-dicts vinden voor CSV; rest gaat naar sleutel/waarde-regels."""
    best, best_size = None, 0
    scalars = {}
    for key, item in value.items():
        if isinstance(item, list) and item and isinstance(item[0], dict) and len(item) > best_size:
            best, best_size = item, len(item)
        elif not isinstance(item, (dict, list)):
            scalars[key] = item
    return scalars, best


def to_csv(data: dict) -> str:
    if not isinstance(data, dict) or not data:
        return ""
    buffer = io.StringIO()
    scalars, rows = _flat_rows(data)
    if scalars:
        writer = csv.writer(buffer)
        writer.writerow(["key", "value"])
        for key, value in scalars.items():
            writer.writerow([key, value])
        if rows:
            buffer.write("\n")
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in rows[0]})
    return buffer.getvalue()


def to_markdown(data: dict) -> str:
    lines = [f"# {data.get('report', data.get('filename', 'Rapport'))}", ""]
    if data.get("generated_at"):
        lines += [f"Gegenereerd: {data['generated_at']}", ""]
    for key, item in data.items():
        if key in {"report", "generated_at"}:
            continue
        if isinstance(item, dict):
            lines += [f"## {key}", "", "```json",
                      json.dumps(item, indent=2, ensure_ascii=False, default=str), "```", ""]
        elif isinstance(item, list) and item and isinstance(item[0], dict):
            lines += [f"## {key}", "", "| " + " | ".join(item[0]) + " |",
                      "|" + "---|" * len(item[0])]
            for row in item[:200]:
                lines.append("| " + " | ".join(
                    str(row.get(column, "")) for column in item[0]) + " |")
            lines.append("")
        else:
            lines += [f"- **{key}**: {item}"]
    lines += ["", "ANALYSIS ONLY FOR TECHNICIAN REVIEW — geen BIN gewijzigd."]
    return "\n".join(lines)


def to_html(data: dict) -> str:
    parts = ["<!doctype html><html><head><meta charset='utf-8'>",
             "<title>TuningMatching rapport</title>",
             "<style>body{font-family:system-ui;margin:2rem}"
             "table{border-collapse:collapse}td,th{border:1px solid #999;padding:4px 8px}"
             ".unknown{color:#b00}</style></head><body>"]
    parts.append(f"<h1>{html.escape(str(data.get('report', data.get('filename', 'Rapport'))))}</h1>")
    for key, item in data.items():
        if key in {"report"}:
            continue
        parts.append(f"<h2>{html.escape(key)}</h2>")
        if isinstance(item, list) and item and isinstance(item[0], dict):
            parts.append("<table><tr>" + "".join(
                f"<th>{html.escape(str(c))}</th>" for c in item[0]) + "</tr>")
            for row in item[:300]:
                cells = "".join(f"<td>{html.escape(str(row.get(c, '')))}</td>" for c in item[0])
                parts.append(f"<tr>{cells}</tr>")
            parts.append("</table>")
        elif isinstance(item, dict):
            parts.append("<table>" + "".join(
                f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(str(v))}</td></tr>"
                for k, v in item.items()) + "</table>")
        else:
            text = html.escape(str(item))
            if "UNKNOWN" in str(item).upper():
                text = f"<span class='unknown'>{text}</span>"
            parts.append(f"<p>{text}</p>")
    parts.append("<p><strong>ANALYSIS ONLY FOR TECHNICIAN REVIEW</strong> — geen BIN gewijzigd.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)


def export_report(data: dict, fmt: str, path: str | Path | None = None) -> str:
    """Rapport schrijven; geeft het bestandspad terug. fmt: json|csv|md|html."""
    if fmt not in FORMATS:
        raise ValueError(f"Onbekend rapportformaat: {fmt} (kies uit {FORMATS})")
    payload = dict(data or {})
    payload.setdefault("generated_at", datetime.now().isoformat())
    if fmt == "json":
        text = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    elif fmt == "csv":
        text = to_csv(payload)
    elif fmt == "md":
        text = to_markdown(payload)
    else:
        text = to_html(payload)
    if path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = str(payload.get("report", "rapport")).replace(" ", "_").lower()
        path = Path("exports") / f"{slug}_{stamp}.{fmt}"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)
