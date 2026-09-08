"""Slicer-embedded thumbnail extraction for G-code files.

Cura, PrusaSlicer and OrcaSlicer all embed a preview image at the top
of the exported program as a comment block carrying a base64 PNG:

    ; thumbnail begin 220x124 51234
    iVBORw0KGgoAAAANSUhEUg...
    iVBORw0KGgoAAAANSUhEUg...
    ; thumbnail end

Cura's OctoPrint-metadata plugin additionally wraps the blocks in
``;THUMBNAIL_BLOCK_START`` / ``;THUMBNAIL_BLOCK_END`` comment lines —
those are ignored here; the inner ``; thumbnail begin/end`` blocks are
the payload either way.

:func:`extract_thumbnail` returns the *largest* block (most
detail for a preview icon), validated as real base64, as a
``data:image/png;base64,…`` URL ready for an ``<img src>``. Malformed
blocks are skipped; a file without any thumbnail yields ``None``.
"""

from __future__ import annotations

import base64
import binascii
import re
from typing import Any, Dict, List, Optional

# "; thumbnail begin 220x124 51234" — the trailing byte-length token
# is optional and unvalidated (some slicers omit it). The underscore
# variant ("thumbnail_begin") is accepted for tolerance.
_BEGIN_RE = re.compile(
    r"^\s*;\s*thumbnail\s+_?begin\s+(\d+)\s*[xX]\s*(\d+)",
    re.IGNORECASE,
)
_END_RE = re.compile(r"^\s*;\s*thumbnail\s+_?end\s*$", re.IGNORECASE)


def extract_thumbnail(text: str) -> Optional[Dict[str, Any]]:
    """Extract the largest embedded thumbnail from G-code text.

    Returns ``{"data_url": str, "width": int, "height": int}`` or
    ``None`` when the text carries no (valid) thumbnail block.
    """
    best: Optional[Dict[str, Any]] = None
    best_area = 0
    collecting: Optional[Dict[str, int]] = None
    chunks: List[str] = []

    for raw_line in text.splitlines():
        begin = _BEGIN_RE.match(raw_line)
        if begin:
            collecting = {
                "width": int(begin.group(1)),
                "height": int(begin.group(2)),
            }
            chunks = []
            continue

        if collecting is None:
            continue

        if _END_RE.match(raw_line):
            b64 = "".join(chunks)
            try:
                base64.b64decode(b64, validate=True)
            except (binascii.Error, ValueError):
                # Corrupt block — skip it and keep scanning.
                collecting = None
                chunks = []
                continue
            area = collecting["width"] * collecting["height"]
            if best is None or area > best_area:
                best = {
                    "data_url": f"data:image/png;base64,{b64}",
                    "width": collecting["width"],
                    "height": collecting["height"],
                }
                best_area = area
            collecting = None
            chunks = []
            continue

        # Payload line: strip whitespace and an optional leading ';'.
        line = raw_line.strip()
        if line.startswith(";"):
            line = line[1:].strip()
        if line:
            chunks.append(line)

    return best
