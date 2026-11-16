"""MathMagic MCP Pro v0.3 — full tool set with the message adapter (no keyboard/mouse/clipboard).

Run: python -u server_pro.py   (stdio JSON-RPC, one message per line)
"""
from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mathmagic_mcp.protocol import MCPServer, schema, s, b  # noqa: E402
from mathmagic_mcp import idbridge as ib  # noqa: E402
from mathmagic_mcp import pipeline as pl  # noqa: E402
from mathmagic_mcp import win32util as w  # noqa: E402

VERSION = "0.3.0"
EXE = os.environ.get("MATHMAGIC_EXE", r"C:\Program Files (x86)\MathMagic Pro Edition\MathMagic Pro 9.31 InD.exe")
PLUGIN_DIR = os.environ.get("MATHMAGIC_PLUGIN_DIR", r"C:\Program Files\Adobe\Adobe InDesign 2026\Plug-Ins\MathMagic CC2026-64bit")
LOG_DIR = os.environ.get("MATHMAGIC_LOG_DIR", str(Path.home() / "MathMagicMCP" / "logs"))
DEFAULT_MODE = os.environ.get("MATHMAGIC_DEFAULT_MODE", "offline")

P = pl.Pipeline(EXE, LOG_DIR)


def _need(confirm: bool, what: str) -> dict | None:
    if not confirm:
        return {"ok": True, "dry_run": True, "note": f"Pass confirm=true to {what}."}
    return None


def policy() -> dict:
    return {
        "ok": True, "version": VERSION,
        "never_uses": ["keyboard (SendInput/keybd_event)", "mouse", "clipboard", "SetFocus/SetForegroundWindow",
                       "license dialog", "original document save/overwrite"],
        "uses": ["window messages to MathMagic (WM_CHAR, WM_COMMAND, WM_SETTEXT)", "InDesign COM DoScript with fixed JSX",
                 "PrintWindow captures (read-only)"],
        "modes": {
            "plugin": "InDesign plugin New/Edit Equation + MathMagic Update. Verified. The plugin itself brings MathMagic, "
                      "then InDesign, to the front for each equation.",
            "offline": "Default. MathMagic renders an EPS via Save As (messages), InDesign places it inline at the marker, "
                       "embeds it and applies the plugin's Default Baseline. Verified ~1-2 s/equation without taking "
                       "focus from the user's app. Starts MathMagic minimized-without-activation if needed.",
        },
        "focus_report": "Each result has focus.took_focus_from_user (your own app lost the foreground) and "
                        "focus.foreground_changed (any window change, e.g. MathMagic's own dialogs while it was in front).",
        "default_mode": DEFAULT_MODE,
        "auto_acknowledged_dialogs": ["MathMagic font PostScript-name warning", "Tip of the Day"],
        "stops_on": ["Authorization (license) dialog", "unknown modal dialogs", "missing marker", "InDesign not running"],
    }


def preflight() -> dict:
    checks = {"windows": w.IS_WINDOWS, "mathmagic_exe": EXE, "mathmagic_exe_exists": Path(EXE).is_file(),
              "indesign_plugin_dir_exists": Path(PLUGIN_DIR).is_dir()}
    try:
        import win32com.client  # noqa: F401
        checks["pywin32"] = True
    except ImportError:
        checks["pywin32"] = False
    st = P.status()
    checks["indesign_running"] = st.get("indesign_running")
    checks["mathmagic_running"] = st.get("mathmagic", {}).get("running")
    checks["license_blocked"] = st.get("mathmagic", {}).get("license_blocked")
    checks["ready"] = bool(checks["windows"] and checks["mathmagic_exe_exists"] and checks["pywin32"]
                           and checks["indesign_running"] and not checks["license_blocked"])
    return {"ok": True, "checks": checks, "status": st}


def inspect_indesign() -> dict:
    return {"ok": True, **P.idc.run(ib.jsx_status())}


def probe_uia() -> dict:
    """Read-only UIA capability scan (fixed: uses GetCurrentPropertyValue) plus modal-dialog detection."""
    st = P.mm.status()
    out = {"ok": True, "mathmagic": st, "windows": []}
    try:
        from pywinauto import Desktop  # type: ignore
    except ImportError:
        out["uia"] = "pywinauto not installed"
        return out
    ids = {"value": 30043, "invoke": 30031, "text": 30040, "expand_collapse": 30028}
    before = w.foreground()
    for win in Desktop(backend="uia").windows():
        try:
            if win.process_id() not in st["pids"]:
                continue
        except Exception:
            continue
        counts = {k: 0 for k in ids}; types: dict = {}
        desc = win.descendants()
        for c in desc[:400]:
            ei = c.element_info
            types[ei.control_type] = types.get(ei.control_type, 0) + 1
            for k, pid in ids.items():
                try:
                    counts[k] += bool(ei.element.GetCurrentPropertyValue(pid))
                except Exception:
                    pass
        out["windows"].append({"title": win.window_text()[:80], "descendants": len(desc), "patterns": counts, "types": types})
    out["foreground_unchanged"] = before.get("hwnd") == w.foreground().get("hwnd")
    out["note"] = "The equation canvas is custom-drawn (no TextPattern); editing uses window messages, not UIA."
    return out


def preview(latex: str, marker: str = "", mode: str = "") -> dict:
    pl.validate_latex(latex)
    if marker:
        pl.validate_marker(marker)
    m = mode or DEFAULT_MODE
    steps = {"plugin": ["select marker caret", "InDesign: New Equation (plugin inserts placeholder)",
                        "MathMagic linked window: WM_CHAR + Select All + Convert TeX", "Update (32880)",
                        "auto-acknowledge font warning", "verify link/plugin recognition", "optional marker removal"],
             "offline": ["MathMagic: New + WM_CHAR + Select All + Convert TeX", "Save As EPS via dialog messages",
                         "verify EPS (MathMagic creator + MMF data)", "InDesign: place inline at marker, embed",
                         "Default Baseline", "verify", "optional marker removal"]}[m]
    return {"ok": True, "dry_run": True, "mode": m, "latex_sha256": pl._sha(latex), "length": len(latex),
            "marker": marker or None, "steps": steps}


def preview_batch(manifest_path: str) -> dict:
    items = pl.read_manifest(manifest_path)
    return {"ok": True, "dry_run": True, "count": len(items),
            "first": [{"id": i.get("id"), "marker": i["marker"], "length": len(i["latex"])} for i in items[:20]]}


def verify(marker: str, document: str = "") -> dict:
    return P.verify(marker, document)


def capture(out_png: str) -> dict:
    if not out_png.lower().endswith(".png"):
        raise ValueError("out_png must end with .png")
    Path(out_png).resolve().parent.mkdir(parents=True, exist_ok=True)
    return P.capture_editor(out_png)


def launch(confirm: bool = False) -> dict:
    return _need(confirm, "start MathMagic without activating it") or P.launch()


def dismiss(confirm: bool = False) -> dict:
    return _need(confirm, "acknowledge MathMagic font warnings / Tip of the Day") or P.dismiss_dialogs()


def create(latex: str, marker: str, confirm: bool = False, mode: str = "", document: str = "",
           remove_marker: bool = False, replace: bool = False, eps_dir: str = "", capture_png: str = "") -> dict:
    pl.validate_latex(latex); pl.validate_marker(marker)
    m = mode or DEFAULT_MODE
    if not confirm:
        return preview(latex, marker, m)
    if m == "offline":
        return P.create_offline(latex, marker, document, eps_dir, replace, remove_marker, capture_png)
    if m == "plugin":
        return P.create_plugin(latex, marker, document, remove_marker, capture_png)
    raise ValueError("mode must be plugin or offline")


def edit(latex: str, marker: str, confirm: bool = False, mode: str = "", document: str = "", eps_dir: str = "") -> dict:
    pl.validate_latex(latex); pl.validate_marker(marker)
    m = mode or DEFAULT_MODE
    if not confirm:
        return {**preview(latex, marker, m), "operation": "edit"}
    if m == "offline":
        return P.create_offline(latex, marker, document, eps_dir, replace=True)
    return P.edit_plugin(latex, marker, document)


def render_eps(latex: str, out_path: str, confirm: bool = False, overwrite: bool = False, capture_png: str = "") -> dict:
    return _need(confirm, "render an EPS file with MathMagic") or P.render_eps(latex, out_path, overwrite, capture_png)


def place_eps(eps_path: str, marker: str, confirm: bool = False, document: str = "", embed: bool = True,
              default_baseline: bool = True, replace: bool = False, remove_marker: bool = False) -> dict:
    return _need(confirm, "place the EPS into InDesign") or P.place_eps(eps_path, marker, document, embed,
                                                                          default_baseline, replace, remove_marker)


def run_batch(manifest_path: str, confirm: bool = False, mode: str = "", document: str = "", start_index: int = 0,
              time_budget_s: int = 45, stop_on_error: bool = True, remove_markers: bool = False,
              eps_dir: str = "", replace: bool = False) -> dict:
    if not confirm:
        return preview_batch(manifest_path)
    return P.batch(manifest_path, mode or DEFAULT_MODE, document, start_index, time_budget_s, stop_on_error,
                   remove_markers, eps_dir, replace)


def prepare_offline_batch(manifest_path: str, output_dir: str, confirm: bool = False) -> dict:
    items = pl.read_manifest(manifest_path)
    out = Path(output_dir).resolve()
    plan = [{"marker": i["marker"], "file": pl.validate_marker(i["marker"]) + ".tex"} for i in items]
    if not confirm:
        return {"ok": True, "dry_run": True, "count": len(plan), "output_dir": str(out)}
    out.mkdir(parents=True, exist_ok=True)
    if any((out / p["file"]).exists() for p in plan):
        return {"ok": False, "status": "REFUSED_OVERWRITE"}
    for item, p in zip(items, plan):
        (out / p["file"]).write_text(item["latex"] + "\n", encoding="utf-8")
    return {"ok": True, "count": len(plan), "output_dir": str(out), "note": "Inputs only; no rendering done."}


def backup_indd(folder: str, confirm: bool = False, document: str = "") -> dict:
    if not confirm:
        return {"ok": True, "dry_run": True, "note": "Copies the last SAVED .indd; unsaved changes are not included."}
    st = P.idc.run(ib.jsx_documents())
    name = document or st.get("active")
    src = Path(next((d["path"] for d in st.get("documents", []) if d["name"] == name), "") or "")
    if not src.is_file() or src.suffix.lower() != ".indd":
        return {"ok": False, "error": "Document must be saved as .indd first"}
    target = Path(folder).resolve()
    if target == src.parent.resolve():
        return {"ok": False, "error": "Choose a different backup folder"}
    target.mkdir(parents=True, exist_ok=True)
    out = target / f"{src.stem}-mm-backup-{datetime.now():%Y%m%d-%H%M%S}{src.suffix}"
    shutil.copy2(src, out)
    return {"ok": True, "backup": str(out), "source": str(src), "unsaved_changes_included": False}


def cleanup_marker(marker: str, confirm: bool = False, document: str = "", require_equation: bool = True) -> dict:
    return _need(confirm, "remove the marker text") or P.cleanup_marker(marker, document, require_equation)


MODE = s("plugin (verified; plugin brings windows to front) or offline (EPS + place)", enum=["plugin", "offline"])
DOC = s("Open InDesign document name (default: active document)")
TOOLS = {
    "mathmagic_policy": ({"description": "What this server does and never does; modes and focus behaviour.",
                          "inputSchema": schema({})}, policy),
    "mathmagic_preflight": ({"description": "Read-only readiness check: files, pywin32, InDesign/MathMagic running, license dialog.",
                             "inputSchema": schema({})}, preflight),
    "mathmagic_status": ({"description": "Read-only: MathMagic windows/documents/dialogs, InDesign documents, MathMagic plugin actions, foreground.",
                          "inputSchema": schema({})}, P.status),
    "mathmagic_inspect_indesign": ({"description": "Read-only InDesign probe (never launches InDesign): documents, selection, all MathMagic plugin actions.",
                                    "inputSchema": schema({})}, inspect_indesign),
    "mathmagic_probe_uia": ({"description": "Read-only Windows UI Automation capability scan of MathMagic with modal-dialog detection.",
                             "inputSchema": schema({})}, probe_uia),
    "mathmagic_preview_equation": ({"description": "Validate LaTeX/marker and show the planned steps. No changes.",
                                    "inputSchema": schema({"latex": s("LaTeX"), "marker": s("[[MM:ID]]"), "mode": MODE}, ["latex"])}, preview),
    "mathmagic_preview_batch": ({"description": "Validate a JSON manifest (up to 2000 equations). No changes.",
                                 "inputSchema": schema({"manifest_path": s("Absolute .json path")}, ["manifest_path"])}, preview_batch),
    "mathmagic_verify_equation": ({"description": "Read-only: is there a native MathMagic equation right before [[MM:ID]]? Link, embedding, plugin recognition.",
                                   "inputSchema": schema({"marker": s("[[MM:ID]]"), "document": DOC}, ["marker"])}, verify),
    "mathmagic_capture_editor": ({"description": "Save a PNG of the open MathMagic equation window (PrintWindow, no focus change).",
                                  "inputSchema": schema({"out_png": s("Absolute .png path")}, ["out_png"])}, capture),
    "mathmagic_launch": ({"description": "Start MathMagic without activating it. Reports LICENSE_REQUIRED if the Authorization dialog appears.",
                          "inputSchema": schema({"confirm": b("Must be true")})}, launch),
    "mathmagic_dismiss_dialogs": ({"description": "Acknowledge only known harmless MathMagic dialogs (font warning, Tip of the Day). Never the license dialog.",
                                   "inputSchema": schema({"confirm": b("Must be true")})}, dismiss),
    "mathmagic_create_equation": ({"description": "Insert a native MathMagic equation at an [[MM:ID]] marker without keyboard/mouse/clipboard. "
                                                  "Returns verification, timing and a foreground-window report.",
                                   "inputSchema": schema({"latex": s("LaTeX"), "marker": s("[[MM:ID]]"), "confirm": b("Must be true to change the document"),
                                                          "mode": MODE, "document": DOC, "remove_marker": b("Remove marker after verification"),
                                                          "replace": b("offline: replace an existing equation before the marker"),
                                                          "eps_dir": s("offline: folder for rendered EPS files"),
                                                          "capture_png": s("Optional .png path for an editor capture")}, ["latex", "marker"])}, create),
    "mathmagic_edit_equation": ({"description": "Replace the equation just before [[MM:ID]] with new LaTeX (plugin: Edit Equation; offline: re-render and replace).",
                                 "inputSchema": schema({"latex": s("New LaTeX"), "marker": s("[[MM:ID]]"), "confirm": b("Must be true"),
                                                        "mode": MODE, "document": DOC, "eps_dir": s("offline: EPS folder")}, ["latex", "marker"])}, edit),
    "mathmagic_render_eps": ({"description": "Render LaTeX to a MathMagic EPS file (editable MathMagic data inside) via window messages.",
                              "inputSchema": schema({"latex": s("LaTeX"), "out_path": s("Absolute .eps path"), "confirm": b("Must be true"),
                                                     "overwrite": b("Replace an existing file"), "capture_png": s("Optional .png path")},
                                                    ["latex", "out_path"])}, render_eps),
    "mathmagic_place_eps": ({"description": "Place a MathMagic EPS inline at [[MM:ID]] by InDesign scripting, embed it and align the baseline.",
                             "inputSchema": schema({"eps_path": s("Absolute .eps path"), "marker": s("[[MM:ID]]"), "confirm": b("Must be true"),
                                                    "document": DOC, "embed": b("Embed (default true)"), "default_baseline": b("Apply Default Baseline (default true)"),
                                                    "replace": b("Replace an existing equation"), "remove_marker": b("Remove marker after verification")},
                                                   ["eps_path", "marker"])}, place_eps),
    "mathmagic_run_batch": ({"description": "Process a manifest sequentially within a time budget; returns next_index to continue. Stops on first error by default.",
                             "inputSchema": schema({"manifest_path": s("Absolute .json path"), "confirm": b("Must be true"), "mode": MODE,
                                                    "document": DOC, "start_index": {"type": "integer", "minimum": 0},
                                                    "time_budget_s": {"type": "integer", "minimum": 5, "maximum": 600},
                                                    "stop_on_error": b("Default true"), "remove_markers": b("Remove markers after verification"),
                                                    "eps_dir": s("offline: EPS folder"), "replace": b("offline: replace existing equations")},
                                                   ["manifest_path"])}, run_batch),
    "mathmagic_prepare_offline_batch": ({"description": "Write each manifest LaTeX to <marker>.tex in an empty folder (inputs only).",
                                         "inputSchema": schema({"manifest_path": s("Absolute .json path"), "output_dir": s("Folder"),
                                                                "confirm": b("Must be true")}, ["manifest_path", "output_dir"])}, prepare_offline_batch),
    "mathmagic_backup_indd": ({"description": "Copy the last saved .indd to another folder (unsaved changes excluded).",
                               "inputSchema": schema({"folder": s("Absolute backup folder"), "confirm": b("Must be true"), "document": DOC},
                                                     ["folder"])}, backup_indd),
    "mathmagic_cleanup_marker": ({"description": "Remove an [[MM:ID]] marker; by default only if a verified equation precedes it.",
                                  "inputSchema": schema({"marker": s("[[MM:ID]]"), "confirm": b("Must be true"), "document": DOC,
                                                         "require_equation": b("Default true")}, ["marker"])}, cleanup_marker),
}

if __name__ == "__main__":
    MCPServer(TOOLS, version=VERSION).run()
