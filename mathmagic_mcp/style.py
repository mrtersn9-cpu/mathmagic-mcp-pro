"""MathMagic StyleSet (.mms / DefaultSetting*.mmd) parsing and generation.

Verified format (MathMagic Pro Win 9.31): plain text, CR line endings, entries
  \\st(slot, Font Name, face)   face 0=plain 1=bold 2=italic 3=bold italic
  \\sz(0,2,12)                  base (full) size in points; other \\sz are percentages
Slots repeat in groups of 10 (0-9, 10-19, 20-29, 30-32); within a group the
observed meaning is: 0 text, 1 function, 2 variable, 3 lower-case Greek,
4 upper-case Greek, 5 vector/matrix (bold), 6 number, 7-9 user styles.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

SLOT_NAMES = {0: "text", 1: "function", 2: "variable", 3: "greek_lc", 4: "greek_uc",
              5: "vector", 6: "number", 7: "user1", 8: "user2", 9: "user3"}
MAIN_FONT_SLOTS = (0, 1, 2, 5, 6)
_ST = re.compile(r"^\\st\((\d+),(.*?),\s*(\d+)\)\s*$")
_SZ0 = re.compile(r"^\\sz\(0,(\d+),([\d.]+)\)\s*$")
_NAME = re.compile(r"^\\SSNAME\((.*)\)\s*$")
_SAFE_NAME = re.compile(r"^[\w .()+-]{1,60}$", re.UNICODE)
FACES = {0: "plain", 1: "bold", 2: "italic", 3: "bold_italic"}


def styles_dir() -> Path:
    return Path(os.environ.get("MATHMAGIC_STYLESET_DIR", str(
        Path.home() / "Documents" / "MathMagic Equation Editor" / "MathMagic Pro" / "MathMagic User Data v7" / "StyleSets")))


def _lines(text: str) -> list[str]:
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def parse_style(text: str) -> dict:
    fonts: dict[int, dict] = {}
    base = None
    name = None
    for line in _lines(text):
        line = line.strip()
        m = _ST.match(line)
        if m:
            slot = int(m.group(1))
            fonts[slot] = {"font": m.group(2).strip(), "face": FACES.get(int(m.group(3)), m.group(3))}
            continue
        m = _SZ0.match(line)
        if m:
            base = float(m.group(2))
            continue
        m = _NAME.match(line)
        if m:
            name = m.group(1)
    summary = {SLOT_NAMES[s]: fonts[s] for s in SLOT_NAMES if s in fonts}
    return {"name": name, "base_size_pt": base, "slots": summary, "slot_count": len(fonts),
            "fonts_used": sorted({f["font"] for f in fonts.values()})}


def read_file(path: Path) -> str:
    return path.read_bytes().decode("mbcs" if os.name == "nt" else "latin-1")


def current_default() -> dict:
    files = sorted(styles_dir().glob("DefaultSetting*.mmd"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return {"ok": False, "error": "No DefaultSetting*.mmd in " + str(styles_dir())}
    return {"ok": True, "file": str(files[0]), **parse_style(read_file(files[0]))}


def list_stylesets() -> list[dict]:
    out = []
    for p in sorted(styles_dir().glob("*.mms")):
        try:
            info = parse_style(read_file(p))
            out.append({"name": p.stem, "base_size_pt": info["base_size_pt"], "fonts_used": info["fonts_used"],
                        "variable": info["slots"].get("variable")})
        except OSError:
            continue
    return out


def build_style(base_text: str, name: str, font: str | None = None, size_pt: float | None = None,
                variable_italic: bool | None = None, variable_font: str | None = None,
                number_font: str | None = None, greek_font: str | None = None) -> str:
    """Return a new StyleSet text derived from base_text. Unrelated settings are preserved."""
    if not _SAFE_NAME.match(name or ""):
        raise ValueError("StyleSet name: 1-60 letters, digits, space . ( ) + - _")
    if size_pt is not None and not 4 <= float(size_pt) <= 72:
        raise ValueError("size_pt must be between 4 and 72")
    for f in (font, variable_font, number_font, greek_font):
        if f is not None and (not f.strip() or any(c in f for c in "(),\\\r\n")):
            raise ValueError("Invalid font name")
    out = []
    for raw in _lines(base_text):
        line = raw.strip()
        m = _ST.match(line)
        if m:
            slot, fnt, face = int(m.group(1)), m.group(2).strip(), int(m.group(3))
            kind = slot % 10
            if kind in MAIN_FONT_SLOTS and font:
                fnt = font
            if kind == 2:
                if variable_font:
                    fnt = variable_font
                if variable_italic is not None:
                    face = 2 if variable_italic else 0
            if kind == 6 and number_font:
                fnt = number_font
            if kind in (3, 4) and greek_font:
                fnt = greek_font
            raw = f"\\st({slot},{fnt}, {face})"
        elif _SZ0.match(line) and size_pt is not None:
            unit = _SZ0.match(line).group(1)
            raw = f"\\sz(0,{unit},{float(size_pt):g})"
        elif _NAME.match(line):
            raw = f"\\SSNAME({name})"
        elif line.startswith("\\DATE("):
            now = datetime.now()
            raw = f"\\DATE({now.month}, {now.day}, {now.year}, {now:%H:%M:%S})"
        out.append(raw)
    return "\r".join(out)


def write_styleset(name: str, text: str, overwrite: bool = False) -> Path:
    path = styles_dir() / f"{name}.mms"
    if path.exists() and not overwrite:
        raise FileExistsError(f"StyleSet '{name}' already exists; pass overwrite=true")
    path.write_bytes(text.encode("mbcs" if os.name == "nt" else "latin-1"))
    return path


def installed_fonts() -> set[str]:
    """Family-ish names from the Windows font registry (machine + user)."""
    names: set[str] = set()
    if os.name != "nt":
        return names
    import winreg
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            key = winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
        except OSError:
            continue
        with key:
            i = 0
            while True:
                try:
                    value = winreg.EnumValue(key, i)[0]
                except OSError:
                    break
                i += 1
                names.add(re.sub(r"\s*\((TrueType|OpenType)\)$", "", value).strip().lower())
    return names


def font_installed(font: str, fonts: set[str] | None = None) -> bool:
    fonts = installed_fonts() if fonts is None else fonts
    f = font.strip().lower()
    return f in fonts or any(name.startswith(f + " ") or name.split(" & ")[0] == f for name in fonts)
