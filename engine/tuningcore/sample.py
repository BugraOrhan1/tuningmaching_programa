"""Synthetische OLS-builder (tests + benchmark) in de bewezen echte structuur.

Volgt de bewezen WinOLS-5-layout: header met length-prefixed versienamen +
importpaden, nul-padding, daarna versiepagina's die elk met een identiteits-
header beginnen en op vaste afstand herhalen (pagina's ≥99% identiek — zoals
echte versies, die bijna alle inhoud delen).
"""
from __future__ import annotations

import struct


def build_ols(identity: str, versions: list[tuple[str, bytes]]) -> bytes:
    """identity moet ≥16 ASCII-tekens zijn (printable-run drempel)."""
    assert len(identity) >= 16, "identiteitsheader moet >=16 tekens zijn"
    out = bytearray(b"\x00\x00\x00\x00WinOLS File\x00")

    def rec(raw: bytes):
        out.extend(struct.pack("<I", len(raw)) + raw)

    for name, _binary in versions:
        rec(name.encode("ascii"))
        rec((name + " - bestand: versie.bin").encode("ascii"))
    out.extend(b"\x00" * 8)  # nul-gat vóór de eerste pagina (anchor-eis)

    identity_raw = identity.encode("ascii")
    pages = []
    for _name, binary in versions:
        page = bytearray()
        page.extend(struct.pack("<I", len(identity_raw)) + identity_raw)
        page.extend(b"\x00" * 8)
        page.extend(binary)
        page.extend(b"\x00" * 4)
        pages.append(bytes(page))
    page_size = max(len(page) for page in pages) + 16
    for index, page in enumerate(pages):
        out.extend(page)
        # laatste pagina krijgt +4 padding zodat ook de laatste identiteits-
        # header een VOLLEDIGE stride voor zich heeft (zoals echte WinOLS)
        extra = 4 if index == len(pages) - 1 else 0
        out.extend(b"\x00" * (page_size - len(page) + extra))
    return bytes(out)
