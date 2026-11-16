"""Read-only MathMagic EPS header inspection."""
from __future__ import annotations

import re
from pathlib import Path

_BBOX = re.compile(r"^%%BoundingBox:\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", re.M)
_BASE = re.compile(r"^%%Baseline:\s*([-\d.]+)", re.M)
_CREATOR = re.compile(r"^%%Creator:\s*(.+)$", re.M)
_FONTS = re.compile(r"^%%(?:DocumentFonts:|\+)\s*(\S+)", re.M)


def inspect_eps_text(head: str) -> dict:
    head = head.replace("\r\n", "\n").replace("\r", "\n")  # MathMagic writes CR-only line endings
    creator = _CREATOR.search(head)
    bbox = _BBOX.search(head)
    base = _BASE.search(head)
    info = {
        "creator": creator.group(1).strip() if creator else None,
        "is_mathmagic": bool(creator and "MathMagic" in creator.group(1)),
        "has_mmf_data": "%%MMFDataBegin" in head and "%%MMFDataEnd" in head,
        "fonts": _FONTS.findall(head),
        "bbox": [float(x) for x in bbox.groups()] if bbox else None,
        "baseline_pt": float(base.group(1)) if base else None,
    }
    info["descent_pt"] = None
    if info["bbox"] and info["baseline_pt"] is not None:
        height = info["bbox"][3] - info["bbox"][1]
        info["descent_pt"] = round(height - info["baseline_pt"], 3)
    return info


def inspect_eps(path: str | Path, limit: int = 64 * 1024) -> dict:
    p = Path(path)
    with p.open("rb") as stream:
        head = stream.read(limit).decode("latin-1")
    info = inspect_eps_text(head)
    info["size"] = p.stat().st_size
    return info
