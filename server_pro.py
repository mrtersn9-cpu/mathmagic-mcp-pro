"""MathMagic MCP Pro v0.4.2 - full MathMagic tool set with the message adapter (no keyboard/mouse/clipboard).

Run: python -u server_pro.py   (stdio JSON-RPC, one message per line)
"""
from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime
from functools import wraps
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mathmagic_mcp.protocol import MCPServer, schema, s, b  # noqa: E402
from mathmagic_mcp import idbridge as ib  # noqa: E402
from mathmagic_mcp import mmwin  # noqa: E402
from mathmagic_mcp import pipeline as pl  # noqa: E402
from mathmagic_mcp import synclock  # noqa: E402
from mathmagic_mcp import win32util as w  # noqa: E402

VERSION = pl.VERSION
EXE = os.environ.get("MATHMAGIC_EXE", r"C:\Program Files (x86)\MathMagic Pro Edition\MathMagic Pro 9.31 InD.exe")
PLUGIN_DIR = os.environ.get("MATHMAGIC_PLUGIN_DIR", r"C:\Program Files\Adobe\Adobe InDesign 2026\Plug-Ins\MathMagic CC2026-64bit")
LOG_DIR = os.environ.get("MATHMAGIC_LOG_DIR", str(Path.home() / "MathMagicMCP" / "logs"))
DEFAULT_MODE = os.environ.get("MATHMAGIC_DEFAULT_MODE", "offline")
LOCK_TIMEOUT = float(os.environ.get("MATHMAGIC_LOCK_TIMEOUT", "15"))
P = pl.Pipeline(EXE, LOG_DIR)

PLUGIN_ACTIONS = {
    "New Equation": "used_by_mcp (plugin mode)", "Edit Equation": "used_by_mcp (plugin edit)",
    "Default Baseline": "used_by_mcp (after every placement)", "Shift Baseline...": "dialog_only (InDesign UI)",
    "Apply a StyleSet...": "dialog_only (InDesign UI) - use set_style + rerender_equations",
    "Apply a StyleSet to Equations...": "dialog_only (InDesign UI) - use rerender_equations",
    "Export All Equations...": "dialog_only (InDesign UI) - use list_equations / export_equation",
    "Preferences...": "dialog_only (InDesign UI)", "Equation Conversion Preferences...": "disabled in tests",
    "Convert to Equation": "disabled in tests - use create_equation", "About MathMagic CC2026 Plug-in...": "not needed",
}


def locked(op: str):
    """Serialise every mutating tool across all server processes (several Claude sessions)."""
    def deco(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            if not kwargs.get("confirm", False):
                return fn(*args, **kwargs)
            try:
                with synclock.exclusive(op, timeout=LOCK_TIMEOUT):
                    return fn(*args, **kwargs)
            except synclock.LockBusy as exc:
                return {"ok": False, "status": "BUSY", "owner": exc.owner,
                        "note": "Another MathMagic MCP operation (maybe another Claude session) is running."}
        return inner
    return deco


def _dry(what: str) -> dict:
    return {"ok": True, "dry_run": True, "note": f"Pass confirm=true to {what}."}


# ------------------------------------------------------------------ read-only tools
def policy() -> dict:
    return {
        "ok": True, "version": VERSION,
        "never_uses": ["keyboard (SendInput/keybd_event)", "mouse", "clipboard", "SetFocus/SetForegroundWindow",
                       "license dialog", "saving or overwriting documents unless save_every / mathmagic_save_document is used"],
        "uses": ["window messages to MathMagic (WM_CHAR, WM_COMMAND, WM_SETTEXT, BM_CLICK)", "InDesign COM DoScript with fixed JSX",
                 "PrintWindow captures (read-only)", "StyleSet text files in the MathMagic StyleSets folder"],
        "modes": {"offline": "Default. Render via MathMagic Save As, place inline at the marker, embed, Default Baseline, label; "
                             "one InDesign undo step per equation; does not take focus from the user's app.",
                  "plugin": "InDesign plugin New/Edit Equation + Update. The plugin brings MathMagic, then InDesign, to the front."},
        "default_mode": DEFAULT_MODE,
        "synchronisation": ["cross-process lock for all mutating tools", "ordered message barriers (no fixed sleeps)",
                            "strict modal-dialog guard (stops on unexpected dialogs)", "frame labels mm.id/latex/sha/style",
                            "batch journal <manifest>.progress.jsonl + skip of finished items", "auto-relaunch of MathMagic"],
        "auto_acknowledged_dialogs": ["MathMagic font PostScript-name warning", "Tip of the Day"],
        "stops_on": ["Authorization (license) dialog", "unexpected modal dialog", "marker missing/duplicated", "InDesign not running"],
        "automation_channel": "Only these mathmagic_* tools. Windows MCP / computer-use / key or mouse automation of MathMagic or "
                              "InDesign windows is not allowed; stop and report instead.",
        "user_input_safety": ["waits (read-only GetAsyncKeyState) until the user releases Alt/Ctrl/Shift/Win before typing",
                              "an empty equation (characters lost) is retried once, then reported as EMPTY_RENDER",
                              "focus report separates took_focus_from_user (MathMagic/InDesign came to front) from "
                              "user_switched_apps (the user's own Alt+Tab)"],
        "content_checks": ["LaTeX round-trip (verify_latex, default on): EXACT / EQUIVALENT / DIFFERENT -> LATEX_MISMATCH",
                           "auto-fix of MathMagic's large-operator binding (\\int_0^1 x^2 -> {x^2}), reported as latex_rewrites",
                           "style-only variants are equivalent (\\dfrac/\\tfrac/\\cfrac = \\frac, size hints ignored)",
                           "multi-digit numbers are one unit (60^{\\circ} == {60}^{\\circ})"],
        "native_accents": {"\\widehat{..}": "Wide Hat (triangular) - MathMagic variable symbol V(42)",
                           "\\overarc{..} / \\wideparen{..} / \\overparen{..}": "Over Elliptical Arc - V(19)",
                           "how": "typed with an \\overbrace placeholder, structure verified, saved as native .mmf, symbol "
                                  "swapped, reopened (File > Open by messages) and exported; result field native_accents",
                           "limits": ["\\overbrace cannot be used in the same equation (NATIVE_ACCENT_UNSUPPORTED)",
                                      "hat/arc height is a StyleSet spacing value, it does not grow with size_pt"]},
        "layout_notes": ["equations are inline, embedded, scale 100%, Default Baseline applied",
                         "paragraphs with stacked inline fractions need fixed leading (~1.75 x size); auto leading overlaps"],
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
    mm = st.get("mathmagic", {})
    checks.update({"indesign_running": st.get("indesign_running"), "mathmagic_running": mm.get("running"),
                   "mathmagic_responsive": mm.get("responsive"), "license_blocked": mm.get("license_blocked")})
    checks["ready"] = bool(checks["windows"] and checks["mathmagic_exe_exists"] and checks["pywin32"]
                           and checks["indesign_running"] and not checks["license_blocked"])
    return {"ok": True, "checks": checks, "status": st}


def inspect_indesign() -> dict:
    return {"ok": True, **P.idc.run(ib.jsx_status())}


def capabilities() -> dict:
    """Live inventory of every MathMagic menu command and plugin action, classified for automation."""
    out: dict = {"ok": True, "version": VERSION}
    try:
        inv = P.mm.menu_inventory()
        counts: dict = {}
        for item in inv:
            counts[item["class"]] = counts.get(item["class"], 0) + 1
        out["mathmagic_commands"] = {"total": len(inv), "by_class": counts, "items": inv}
    except mmwin.MathMagicError as exc:
        out["mathmagic_commands"] = {"error": str(exc), "status": exc.status}
    if P.idc.running():
        try:
            acts = P.idc.run(ib.jsx_status()).get("actions", [])
            out["indesign_plugin_actions"] = [{**a, "automation": PLUGIN_ACTIONS.get(a["name"], "not classified")} for a in acts]
        except ib.InDesignError as exc:
            out["indesign_plugin_actions"] = {"error": str(exc)}
    out["classes"] = {"used_by_mcp": "driven by this server", "message_safe_available": "no dialog; formatting is normally done via LaTeX",
                      "dialog_only": "opens a modal dialog; not automated (StyleSet is the exception, via set_style)",
                      "excluded_clipboard": "would use the clipboard", "excluded_external_or_license": "web/print/license/help",
                      "ui_only_not_needed": "view/window layout"}
    return out


def probe_uia() -> dict:
    st = P.mm.status()
    out = {"ok": True, "mathmagic": st, "windows": []}
    try:
        from pywinauto import Desktop  # type: ignore
    except ImportError:
        return {**out, "uia": "pywinauto not installed"}
    ids = {"value": 30043, "invoke": 30031, "text": 30040, "expand_collapse": 30028}
    before = w.foreground()
    for win in Desktop(backend="uia").windows():
        try:
            if win.process_id() not in st["pids"]:
                continue
        except Exception:
            continue
        counts = {k: 0 for k in ids}
        desc = win.descendants()
        for c in desc[:400]:
            for k, pid in ids.items():
                try:
                    counts[k] += bool(c.element_info.element.GetCurrentPropertyValue(pid))
                except Exception:
                    pass
        out["windows"].append({"title": win.window_text()[:80], "descendants": len(desc), "patterns": counts})
    out["foreground_unchanged"] = before.get("hwnd") == w.foreground().get("hwnd")
    out["note"] = "The equation canvas is custom-drawn (no TextPattern); editing uses window messages, not UIA."
    return out


def preview(latex: str, marker: str = "", mode: str = "", size_pt: float | None = None) -> dict:
    pl.validate_latex(latex)
    if marker:
        pl.validate_marker(marker)
    if size_pt is not None:
        mmwin.size_commands(size_pt)
    m = mode or DEFAULT_MODE
    steps = {"plugin": ["select marker", "plugin New Equation", "MathMagic: clear+type+select+convert (one burst)", "Update",
                        "verify + label", "optional marker removal"],
             "offline": ["MathMagic: clear+type+select+convert (one burst) + Save As EPS", "verify EPS",
                         "InDesign (one undo step): place at marker, fit, embed, Default Baseline, label, verify",
                         "optional marker removal"]}[m]
    return {"ok": True, "dry_run": True, "mode": m, "latex_sha256": pl._sha(latex), "length": len(latex),
            "marker": marker or None, "size_pt": size_pt, "steps": steps}


def preview_batch(manifest_path: str) -> dict:
    items = pl.read_manifest(manifest_path)
    return {"ok": True, "dry_run": True, "count": len(items),
            "first": [{"id": i.get("id"), "marker": i["marker"], "length": len(i["latex"])} for i in items[:20]],
            "estimated_minutes_offline": round(len(items) * 1.2 / 60, 1)}


def verify(marker: str, document: str = "") -> dict:
    return P.verify(marker, document)


def list_equations(document: str = "", include_latex: bool = False, deep: bool = False) -> dict:
    return P.list_equations(document, include_latex, deep)


def get_style() -> dict:
    return P.get_style()


def capture(out_png: str) -> dict:
    if not out_png.lower().endswith(".png"):
        raise ValueError("out_png must end with .png")
    Path(out_png).resolve().parent.mkdir(parents=True, exist_ok=True)
    return P.capture_editor(out_png)


# ------------------------------------------------------------------ mutating tools
@locked("launch")
def launch(confirm: bool = False) -> dict:
    return P.launch() if confirm else _dry("start MathMagic without activating it")


@locked("dismiss")
def dismiss(confirm: bool = False) -> dict:
    return P.dismiss_dialogs() if confirm else _dry("acknowledge MathMagic font warnings / Tip of the Day")


@locked("create")
def create(latex: str, marker: str, confirm: bool = False, mode: str = "", document: str = "", remove_marker: bool = False,
           replace: bool = False, eps_dir: str = "", size_pt: float | None = None, verify_latex: bool | None = None,
           id: str = "", capture_png: str = "") -> dict:
    pl.validate_latex(latex); pl.validate_marker(marker)
    m = mode or DEFAULT_MODE
    if not confirm:
        return preview(latex, marker, m, size_pt)
    if m == "offline":
        return P.create_offline(latex, marker, document, eps_dir, replace, remove_marker, size_pt, verify_latex, id, capture_png)
    if m == "plugin":
        return P.create_plugin(latex, marker, document, remove_marker, size_pt, id)
    raise ValueError("mode must be plugin or offline")


@locked("edit")
def edit(latex: str, marker: str, confirm: bool = False, mode: str = "", document: str = "", eps_dir: str = "",
         size_pt: float | None = None, verify_latex: bool | None = None) -> dict:
    pl.validate_latex(latex); pl.validate_marker(marker)
    m = mode or DEFAULT_MODE
    if not confirm:
        return {**preview(latex, marker, m, size_pt), "operation": "edit"}
    if m == "offline":
        return P.create_offline(latex, marker, document, eps_dir, True, False, size_pt, verify_latex)
    return P.edit_plugin(latex, marker, document, size_pt)


@locked("render")
def export_equation(latex: str, out_path: str, confirm: bool = False, overwrite: bool = False, size_pt: float | None = None,
                    verify_latex: bool | None = None, ams: bool = False, capture_png: str = "") -> dict:
    if not confirm:
        return {**_dry("render the file with MathMagic"), "format": mmwin.format_keyword(out_path, ams)}
    return P.render(latex, out_path, overwrite, size_pt, verify_latex, capture_png, ams)


@locked("place")
def place_eps(eps_path: str, marker: str, confirm: bool = False, document: str = "", embed: bool = True,
              default_baseline: bool = True, replace: bool = False, remove_marker: bool = False, id: str = "") -> dict:
    if not confirm:
        return _dry("place the EPS into InDesign")
    labels = {"id": id or pl.validate_marker(marker), "tool": pl.TOOL_TAG}
    return P.place_eps(eps_path, marker, document, embed, default_baseline, replace, remove_marker, labels)


@locked("batch")
def run_batch(manifest_path: str, confirm: bool = False, mode: str = "", document: str = "", start_index: int = 0,
              time_budget_s: int = 120, stop_on_error: bool = True, remove_markers: bool = False, eps_dir: str = "",
              replace: bool = False, skip_existing: bool = True, save_every: int = 0, size_pt: float | None = None,
              verify_latex: bool | None = None) -> dict:
    if not confirm:
        return preview_batch(manifest_path)
    return P.batch(manifest_path, mode or DEFAULT_MODE, document, start_index, time_budget_s, stop_on_error, remove_markers,
                   eps_dir, replace, skip_existing, save_every, size_pt, verify_latex)


@locked("rerender")
def rerender(confirm: bool = False, document: str = "", ids: list | None = None, eps_dir: str = "", time_budget_s: int = 120,
             only_style_differs: bool = True) -> dict:
    if not confirm:
        eqs = P.list_equations(document, False)
        return {"ok": True, "dry_run": True, "tagged": eqs["summary"]["tagged"], "styles": eqs["summary"]["styles"]}
    return P.rerender(document, ids, eps_dir, time_budget_s, only_style_differs)


@locked("set_style")
def set_style(name: str, confirm: bool = False, font: str = "", size_pt: float | None = None,
              variable_italic: bool | None = None, variable_font: str = "", number_font: str = "", greek_font: str = "",
              make_default: bool = True, overwrite: bool = False) -> dict:
    if not confirm:
        return {**_dry("write the StyleSet and make it MathMagic's default"), "current": P.get_style()["current_default"]}
    return P.set_style(name, font or None, size_pt, variable_italic, variable_font or None, number_font or None,
                       greek_font or None, make_default, overwrite)


@locked("apply_styleset")
def apply_styleset(name: str, confirm: bool = False, make_default: bool = True) -> dict:
    return P.apply_styleset(name, make_default) if confirm else _dry(f"apply StyleSet '{name}'")


@locked("prepare")
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


@locked("backup")
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


@locked("save")
def save_document(confirm: bool = False, document: str = "") -> dict:
    if not confirm:
        return _dry("save the InDesign document in place (only documents that already have a file)")
    return P.idc.run(ib.jsx_save_document(P._doc_name(document)))


@locked("cleanup")
def cleanup_marker(marker: str, confirm: bool = False, document: str = "", require_equation: bool = True) -> dict:
    return P.cleanup_marker(marker, document, require_equation) if confirm else _dry("remove the marker text")


MODE = s("offline (default; no focus change) or plugin (plugin brings windows to front)", enum=["offline", "plugin"])
DOC = s("Open InDesign document name (default: active document)")
SIZE = {"type": "number", "minimum": 4, "maximum": 72, "description": "Per-equation size in pt (menu sizes + 0.1 pt steps)"}
CONFIRM = b("Must be true to make changes")
TOOLS = {
    "mathmagic_policy": ({"description": "What this server does and never does; modes, synchronisation and focus behaviour.",
                          "inputSchema": schema({})}, policy),
    "mathmagic_preflight": ({"description": "Read-only readiness check (files, pywin32, InDesign/MathMagic running and responsive, license dialog).",
                             "inputSchema": schema({})}, preflight),
    "mathmagic_status": ({"description": "Read-only: MathMagic windows/documents/dialogs, InDesign documents and plugin actions, style state, foreground.",
                          "inputSchema": schema({})}, P.status),
    "mathmagic_capabilities": ({"description": "Read-only live inventory of ALL MathMagic menu commands and InDesign plugin actions, classified for automation.",
                                "inputSchema": schema({})}, capabilities),
    "mathmagic_inspect_indesign": ({"description": "Read-only InDesign probe (never launches InDesign): documents, selection, MathMagic plugin actions.",
                                    "inputSchema": schema({})}, inspect_indesign),
    "mathmagic_probe_uia": ({"description": "Read-only UI Automation capability scan of MathMagic with modal-dialog detection.",
                             "inputSchema": schema({})}, probe_uia),
    "mathmagic_preview_equation": ({"description": "Validate LaTeX/marker/size and show the planned steps. No changes.",
                                    "inputSchema": schema({"latex": s("LaTeX"), "marker": s("[[MM:ID]]"), "mode": MODE, "size_pt": SIZE}, ["latex"])}, preview),
    "mathmagic_preview_batch": ({"description": "Validate a JSON manifest (up to 5000 equations; optional per-item size_pt). No changes.",
                                 "inputSchema": schema({"manifest_path": s("Absolute .json path")}, ["manifest_path"])}, preview_batch),
    "mathmagic_verify_equation": ({"description": "Read-only: native MathMagic equation before [[MM:ID]]? Link, embedding, plugin recognition, labels.",
                                   "inputSchema": schema({"marker": s("[[MM:ID]]"), "document": DOC}, ["marker"])}, verify),
    "mathmagic_list_equations": ({"description": "Read-only inventory of MathMagic equations in a document (ids, page, embedded, style, optional LaTeX).",
                                  "inputSchema": schema({"document": DOC, "include_latex": b("Return stored LaTeX"),
                                                         "deep": b("Also ask the plugin about unknown EPS links (slower)")})}, list_equations),
    "mathmagic_get_style": ({"description": "Read-only: MathMagic's current default style (fonts per role, base size) and available StyleSets.",
                             "inputSchema": schema({})}, get_style),
    "mathmagic_capture_editor": ({"description": "Save a PNG of the open MathMagic equation window (PrintWindow, no focus change).",
                                  "inputSchema": schema({"out_png": s("Absolute .png path")}, ["out_png"])}, capture),
    "mathmagic_launch": ({"description": "Start MathMagic without activating it; reports LICENSE_REQUIRED if the Authorization dialog appears.",
                          "inputSchema": schema({"confirm": CONFIRM})}, launch),
    "mathmagic_dismiss_dialogs": ({"description": "Acknowledge only known harmless MathMagic dialogs (font warning, Tip of the Day). Never the license dialog.",
                                   "inputSchema": schema({"confirm": CONFIRM})}, dismiss),
    "mathmagic_create_equation": ({"description": "Insert a native MathMagic equation at an [[MM:ID]] marker (no keyboard/mouse/clipboard); "
                                                  "returns verification, timing and a focus report. One InDesign undo step (offline).",
                                   "inputSchema": schema({"latex": s("LaTeX"), "marker": s("[[MM:ID]]"), "confirm": CONFIRM, "mode": MODE, "document": DOC,
                                                          "remove_marker": b("Remove marker after verification"),
                                                          "replace": b("Replace an existing equation before the marker"),
                                                          "eps_dir": s("offline: EPS folder (default: <document>.mathmagic-eps)"), "size_pt": SIZE,
                                                          "verify_latex": b("offline: export LaTeX back and compare structurally (default on; MATHMAGIC_VERIFY_LATEX=0 disables)"),
                                                          "id": s("Equation id label (default: marker id)"), "capture_png": s("Optional .png of the editor")},
                                                         ["latex", "marker"])}, create),
    "mathmagic_edit_equation": ({"description": "Replace the equation before [[MM:ID]] with new LaTeX (offline: re-render + replace; plugin: Edit Equation).",
                                 "inputSchema": schema({"latex": s("New LaTeX"), "marker": s("[[MM:ID]]"), "confirm": CONFIRM, "mode": MODE,
                                                        "document": DOC, "eps_dir": s("offline: EPS folder"), "size_pt": SIZE,
                                                        "verify_latex": b("offline: LaTeX round-trip check")}, ["latex", "marker"])}, edit),
    "mathmagic_export_equation": ({"description": "Render LaTeX with MathMagic to a file; format from the extension: .eps .pdf .svg .png .jpg .gif .bmp "
                                                  ".wmf .mmf .mml/.mathml/.html (MathML) .tex (LaTeX, ams=true for AMS) .amath .mathtxt.",
                                   "inputSchema": schema({"latex": s("LaTeX"), "out_path": s("Absolute output path"), "confirm": CONFIRM,
                                                          "overwrite": b("Replace existing file"), "size_pt": SIZE,
                                                          "verify_latex": b("LaTeX round-trip check"), "ams": b("AMS LaTeX for .tex"),
                                                          "capture_png": s("Optional .png of the editor")}, ["latex", "out_path"])}, export_equation),
    "mathmagic_render_eps": ({"description": "Alias of mathmagic_export_equation for .eps output.",
                              "inputSchema": schema({"latex": s("LaTeX"), "out_path": s("Absolute .eps path"), "confirm": CONFIRM,
                                                     "overwrite": b("Replace existing file"), "size_pt": SIZE, "verify_latex": b("LaTeX check"),
                                                     "capture_png": s("Optional .png")}, ["latex", "out_path"])}, export_equation),
    "mathmagic_place_eps": ({"description": "Place a MathMagic EPS inline at [[MM:ID]] (fit, embed, Default Baseline, label) as one undo step.",
                             "inputSchema": schema({"eps_path": s("Absolute .eps path"), "marker": s("[[MM:ID]]"), "confirm": CONFIRM, "document": DOC,
                                                    "embed": b("Embed (default true)"), "default_baseline": b("Default Baseline (default true)"),
                                                    "replace": b("Replace an existing equation"), "remove_marker": b("Remove marker after verification"),
                                                    "id": s("Equation id label")}, ["eps_path", "marker"])}, place_eps),
    "mathmagic_run_batch": ({"description": "Process a manifest ({equations:[{id,marker,latex,size_pt?}]}, e.g. from soru-bankasi-uret-pro "
                                            "prepare_mathmagic.py) within a time budget; skips finished items, journals progress, relaunches "
                                            "MathMagic if it exits, retries an empty equation once, optional periodic save. Stops on the first "
                                            "error (LATEX_MISMATCH shows latex_exported). Returns next_index to continue.",
                             "inputSchema": schema({"manifest_path": s("Absolute .json path"), "confirm": CONFIRM, "mode": MODE, "document": DOC,
                                                    "start_index": {"type": "integer", "minimum": 0},
                                                    "time_budget_s": {"type": "integer", "minimum": 5, "maximum": 1800},
                                                    "stop_on_error": b("Default true"), "remove_markers": b("Remove markers after verification"),
                                                    "eps_dir": s("offline: EPS folder"), "replace": b("Replace existing equations"),
                                                    "skip_existing": b("Skip markers that already have an equation (default true)"),
                                                    "save_every": {"type": "integer", "minimum": 0, "description": "Save the document every N inserted equations (0 = never)"},
                                                    "size_pt": SIZE, "verify_latex": b("offline: LaTeX round-trip check per item")},
                                                   ["manifest_path"])}, run_batch),
    "mathmagic_rerender_equations": ({"description": "Re-render labelled equations from their stored LaTeX with the current StyleSet and replace them in place.",
                                      "inputSchema": schema({"confirm": CONFIRM, "document": DOC, "ids": {"type": "array", "items": {"type": "string"}},
                                                             "eps_dir": s("EPS folder"), "time_budget_s": {"type": "integer", "minimum": 5, "maximum": 1800},
                                                             "only_style_differs": b("Only equations made with another style (default true)")})}, rerender),
    "mathmagic_set_style": ({"description": "Create a StyleSet (font for text/function/variable/vector/number, base size pt, italic variables) from the "
                                            "current default, back up the old default as a StyleSet, make it MathMagic's default and verify with a probe render.",
                             "inputSchema": schema({"name": s("StyleSet name"), "confirm": CONFIRM, "font": s("Main font family"),
                                                    "size_pt": {"type": "number", "minimum": 4, "maximum": 72}, "variable_italic": b("Italic variables"),
                                                    "variable_font": s("Font for variables"), "number_font": s("Font for numbers"),
                                                    "greek_font": s("Font for Greek"), "make_default": b("Default true"),
                                                    "overwrite": b("Replace a StyleSet with the same name")}, ["name"])}, set_style),
    "mathmagic_apply_styleset": ({"description": "Make an existing StyleSet (see get_style) MathMagic's default, e.g. to restore the backup.",
                                  "inputSchema": schema({"name": s("StyleSet name"), "confirm": CONFIRM, "make_default": b("Default true")}, ["name"])},
                                 apply_styleset),
    "mathmagic_prepare_offline_batch": ({"description": "Write each manifest LaTeX to <marker>.tex in an empty folder (inputs only).",
                                         "inputSchema": schema({"manifest_path": s("Absolute .json path"), "output_dir": s("Folder"), "confirm": CONFIRM},
                                                               ["manifest_path", "output_dir"])}, prepare_offline_batch),
    "mathmagic_backup_indd": ({"description": "Copy the last saved .indd to another folder (unsaved changes excluded).",
                               "inputSchema": schema({"folder": s("Absolute backup folder"), "confirm": CONFIRM, "document": DOC}, ["folder"])}, backup_indd),
    "mathmagic_save_document": ({"description": "Save the InDesign document in place (only if it already has a file).",
                                 "inputSchema": schema({"confirm": CONFIRM, "document": DOC})}, save_document),
    "mathmagic_cleanup_marker": ({"description": "Remove an [[MM:ID]] marker; by default only if a verified equation precedes it.",
                                  "inputSchema": schema({"marker": s("[[MM:ID]]"), "confirm": CONFIRM, "document": DOC,
                                                         "require_equation": b("Default true")}, ["marker"])}, cleanup_marker),
}

INSTRUCTIONS = """MathMagic MCP Pro: native, editable MathMagic equations in Adobe InDesign, driven only by window messages and
InDesign COM (no keyboard, mouse, clipboard or focus stealing in the default offline mode).

- MathMagic is driven ONLY through these mathmagic_* tools. Never use Windows MCP, computer-use, browser automation or
  scripts that send keys/clicks to MathMagic or InDesign windows; if a tool is missing or fails, stop and report.
- Never click or close the MathMagic license/Authorization ("Try") dialog; ask the user. LICENSE_REQUIRED means wait for them.
- Workflow: mathmagic_preflight -> mathmagic_set_style (book font/size, once) -> text with unique [[MM:ID]] markers is written
  by the InDesign MCP and saved -> mathmagic_backup_indd -> mathmagic_preview_batch -> mathmagic_run_batch(confirm=true,
  verify_latex=true, remove_markers=true; repeat with start_index=next_index) -> mathmagic_list_equations.
- Do not edit the same InDesign document with another MCP while a MathMagic tool runs. BUSY = another session holds the lock.
- LATEX_MISMATCH: MathMagic built a different structure; fix the source LaTeX (wrap operands of \\int/\\sum: {x^2}).
  EMPTY_RENDER: typed characters were lost twice (e.g. the user held Alt/Ctrl); simply run again.
- Stacked inline fractions need fixed paragraph leading (~1.75 x text size); auto leading overlaps.
- Geometry accents: write angles as m(\\widehat{DEF}) (triangular wide hat) and arcs as \\overarc{AB}. MathMagic's own
  TeX import cannot build these (\\widehat loses its content), so the server builds them through MathMagic's native
  .mmf format automatically. \\hat{X} is for ONE letter only; never \\stackrel. Do not combine \\overbrace with them.
- Question banks: the soru-bankasi-uret-pro skill (scripts/prepare_mathmagic.py, indesign/MATHMAGIC-ENTEGRASYON.md)
  produces the marker text and manifests."""

if __name__ == "__main__":
    MCPServer(TOOLS, version=VERSION, instructions=INSTRUCTIONS).run()
