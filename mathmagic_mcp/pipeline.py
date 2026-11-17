"""High-level MathMagic + InDesign workflows (v0.4): message adapter, no keyboard/mouse/clipboard.

Modes
- "offline" (default): MathMagic renders the file via messages + Save As; InDesign places it inline at the
  marker, embeds it, applies the plugin's Default Baseline and labels the frame - one undo step.
- "plugin": InDesign plugin New/Edit Equation -> linked MathMagic window (messages) -> Update. The plugin
  itself brings MathMagic, then InDesign, to the front.

Synchronisation
- ordered barriers instead of sleeps: a posted burst (clear, type, select, convert[, size]) is followed by a
  posted Save As / Update whose dialog / window-close proves everything before it was processed
- strict dialog guard (unexpected modal dialog -> stop, nothing else is posted)
- labels on every equation frame (mm.id/latex/sha/style/tool) -> idempotent batches and restyling
- batch journal (<manifest>.progress.jsonl), skip of already-done items, auto-relaunch of MathMagic
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import eps as epsmod
from . import idbridge as ib
from . import latexcheck
from . import mmwin
from . import style as stylemod
from . import win32util as w

VERSION = "0.4.1"
TOOL_TAG = "mathmagic-mcp-pro/" + VERSION
_MARKER = re.compile(r"^\[\[MM:([A-Za-z0-9_-]{1,40})\]\]$")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_FORBIDDEN = re.compile(r"\\(?:write18|input|include|openout|read|catcode|def|special|immediate|loop|csname)\b", re.I)
MAX_BATCH = 5000
RECOVERABLE = {"MATHMAGIC_NOT_READY", "NEW_DOCUMENT_TIMEOUT", "SAVE_DIALOG_TIMEOUT", "MATHMAGIC_NOT_RESPONDING"}
STATE_PATH = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MathMagicMCP" / "state.json"
DEFAULT_VERIFY_LATEX = os.environ.get("MATHMAGIC_VERIFY_LATEX", "1") not in ("0", "false", "False")
DEFAULT_FIX_QUIRKS = os.environ.get("MATHMAGIC_FIX_QUIRKS", "1") not in ("0", "false", "False")


def _opt(value, default):
    return default if value is None else bool(value)


def validate_latex(latex: str) -> None:
    if not isinstance(latex, str) or not latex.strip():
        raise ValueError("LaTeX expression is empty")
    if len(latex) > 4000:
        raise ValueError("LaTeX expression exceeds 4000 characters")
    if "\x00" in latex or _FORBIDDEN.search(latex):
        raise ValueError("Potentially unsafe or unsupported TeX command")
    if any(ord(c) < 32 and c not in "\t" for c in latex):
        raise ValueError("Control characters are not allowed in LaTeX input")
    depth = 0
    for ch in latex:
        depth += (ch == "{") - (ch == "}")
        if depth < 0:
            raise ValueError("Unbalanced braces")
    if depth:
        raise ValueError("Unbalanced braces")


def validate_marker(marker: str) -> str:
    m = _MARKER.match(marker or "")
    if not m:
        raise ValueError("Marker must look like [[MM:ID]] (ID: letters, digits, _ or -; max 40)")
    return m.group(1)


def read_manifest(path: str) -> list[dict]:
    p = Path(path).resolve()
    if p.suffix.lower() != ".json" or not p.is_file() or p.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("Manifest must be an existing .json file up to 10 MB")
    data = json.loads(p.read_text(encoding="utf-8-sig"))
    items = data.get("equations") if isinstance(data, dict) else None
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_BATCH:
        raise ValueError(f"'equations' must contain 1..{MAX_BATCH} entries")
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not {"marker", "latex"} <= set(item):
            raise ValueError("Each equation needs marker and latex (id optional)")
        validate_marker(item["marker"]); validate_latex(item["latex"])
        if item["marker"] in seen:
            raise ValueError("Duplicate marker: " + item["marker"])
        if "size_pt" in item and not 4 <= float(item["size_pt"]) <= 72:
            raise ValueError("size_pt must be between 4 and 72")
        seen.add(item["marker"])
    return items


def _sha(latex: str) -> str:
    return hashlib.sha256(latex.encode("utf-8")).hexdigest()


def _state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(**kw) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps({**_state(), **kw}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


class Pipeline:
    def __init__(self, exe_path: str, log_dir: str, mm: mmwin.MathMagicWindows | None = None,
                 idc: ib.InDesignCOM | None = None, focus_factory: Callable[[], Any] | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.exe_path = exe_path
        self.mm = mm or mmwin.MathMagicWindows(exe_path, sleep=sleep)
        self.idc = idc or ib.InDesignCOM()
        self.focus_factory = focus_factory or w.FocusRecorder
        self.log_dir = Path(log_dir)
        self.sleep = sleep
        self.wait_keys = w.wait_modifiers_released   # read-only: user's Alt/Ctrl/Shift/Win must be up before typing

    # ------------------------------------------------------------------ helpers
    def _log(self, event: dict) -> None:
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            path = self.log_dir / ("mm-" + datetime.now(timezone.utc).strftime("%Y%m%d") + ".jsonl")
            with path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "v": VERSION, **event}, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _docs(self) -> dict:
        return self.idc.run(ib.jsx_documents())

    def _doc_name(self, doc_name: str) -> str:
        st = self._docs()
        names = [d["name"] for d in st.get("documents", [])]
        if not names:
            raise ib.InDesignError("NO_DOCUMENT_OPEN")
        if doc_name:
            if doc_name not in names:
                raise ib.InDesignError(f"DOCUMENT_NOT_OPEN: {doc_name}; open: {names}")
            return doc_name
        return st.get("active") or names[0]

    def _eps_dir(self, doc: str, eps_dir: str) -> Path:
        if eps_dir:
            return Path(eps_dir).resolve()
        path = next((d.get("path") for d in self._docs().get("documents", []) if d["name"] == doc), "")
        if not path:
            raise ValueError("Save the InDesign document first or pass eps_dir")
        p = Path(path)
        return p.parent / (p.stem + ".mathmagic-eps")

    @staticmethod
    def _labels(eq_id: str, latex: str) -> dict:
        return {"id": eq_id, "latex": latex, "sha": _sha(latex), "style": _state().get("style", "default"), "tool": TOOL_TAG}

    def _result(self, status: str, ok: bool, t0: float, focus, **extra) -> dict:
        res = {"ok": ok, "status": status, "seconds": round(time.monotonic() - t0, 2)}
        if focus is not None:
            res["focus"] = focus.summary()
        res.update({k: v for k, v in extra.items() if v is not None})
        return res

    def _verify_marker(self, doc: str, marker: str, wait_s: float = 0.0, not_link: str | None = None,
                       check_edit: bool = True) -> dict:
        end = time.monotonic() + wait_s
        while True:
            info = self.idc.run(ib.jsx_equation_at_marker(doc, marker, check_edit))
            eq = info.get("equation")
            good = bool(eq and not eq.get("placeholder") and (not_link is None or eq.get("link") != not_link))
            if good or time.monotonic() >= end:
                return {"verified": good, **info}
            self.sleep(0.12)

    # ------------------------------------------------------------------ read-only
    def status(self) -> dict:
        res: dict = {"ok": True, "version": VERSION, "mathmagic": self.mm.status() if w.IS_WINDOWS else {"running": False}}
        res["indesign_running"] = self.idc.running()
        if res["indesign_running"]:
            try:
                st = self.idc.run(ib.jsx_status())
                res["indesign"] = {"documents": st.get("documents"), "active": st.get("active"),
                                   "selection": st.get("selection"), "mathmagic_actions": st.get("actions")}
            except ib.InDesignError as exc:
                res["indesign_error"] = str(exc)
        res["style_state"] = _state()
        res["foreground"] = w.foreground() if w.IS_WINDOWS else None
        return res

    def verify(self, marker: str, doc_name: str = "") -> dict:
        validate_marker(marker)
        info = self._verify_marker(self._doc_name(doc_name), marker)
        eq = info.get("equation") or {}
        info["assessment"] = ("NATIVE_MATHMAGIC_EQUATION" if info["verified"] and eq.get("edit_equation_enabled")
                              else "PLACEHOLDER_ONLY" if eq.get("placeholder") else "NO_EQUATION" if not eq else "UNRECOGNIZED")
        if eq.get("labels", {}).get("latex"):
            eq["labels"]["latex_matches_sha"] = _sha(eq["labels"]["latex"]) == eq["labels"].get("sha")
        return info

    def list_equations(self, doc_name: str = "", include_latex: bool = False, deep: bool = False) -> dict:
        doc = self._doc_name(doc_name)
        res = self.idc.run(ib.jsx_list_equations(doc, include_latex, deep), timeout=120)
        eqs = res.get("equations", [])
        res["summary"] = {"total": len(eqs), "tagged": sum(bool(e.get("id")) for e in eqs),
                          "placeholders": sum(bool(e.get("placeholder")) for e in eqs),
                          "not_embedded": sum(not e.get("embedded") for e in eqs),
                          "styles": sorted({e.get("style") or "untagged" for e in eqs})}
        res["document"] = doc
        return res

    def capture_editor(self, out_png: str) -> dict:
        docs = self.mm.all_documents()
        if not docs:
            return {"ok": False, "error": "No open MathMagic equation window"}
        return {"ok": True, "window": docs[0].title, **w.capture_png(docs[0].frame, str(Path(out_png).resolve()))}

    # ------------------------------------------------------------------ style
    def get_style(self) -> dict:
        cur = stylemod.current_default()
        fonts = stylemod.installed_fonts()
        if cur.get("ok"):
            cur["fonts_installed"] = {f: stylemod.font_installed(f, fonts) for f in cur["fonts_used"]}
        return {"ok": True, "current_default": cur, "stylesets": stylemod.list_stylesets(),
                "last_applied_by_mcp": _state(), "styleset_dir": str(stylemod.styles_dir())}

    def set_style(self, name: str, font: str | None = None, size_pt: float | None = None, variable_italic: bool | None = None,
                  variable_font: str | None = None, number_font: str | None = None, greek_font: str | None = None,
                  make_default: bool = True, overwrite: bool = False, probe_latex: str = r"\frac{a}{b}+x^2") -> dict:
        fonts = stylemod.installed_fonts()
        missing = [f for f in (font, variable_font, number_font, greek_font) if f and not stylemod.font_installed(f, fonts)]
        if missing:
            return {"ok": False, "status": "FONT_NOT_INSTALLED", "missing": missing}
        cur = stylemod.current_default()
        if not cur.get("ok"):
            return {"ok": False, "status": "NO_DEFAULT_STYLE", **cur}
        base_text = stylemod.read_file(Path(cur["file"]))
        backup_name = "MCP-yedek-" + datetime.now().strftime("%Y%m%d-%H%M%S")
        stylemod.write_styleset(backup_name, stylemod.build_style(base_text, backup_name))
        text = stylemod.build_style(base_text, name, font, size_pt, variable_italic, variable_font, number_font, greek_font)
        path = stylemod.write_styleset(name, text, overwrite=overwrite)
        applied = self.mm.apply_styleset(name, make_default=make_default, apply_current=True)
        _save_state(style=name, style_size_pt=size_pt, style_font=font, style_applied_at=datetime.now().isoformat(timespec="seconds"))
        probe = self._probe_style(probe_latex)
        return {"ok": bool(applied.get("ok")) and probe.get("ok", False), "styleset": name, "file": str(path),
                "backup_styleset": backup_name, "applied": applied, "probe": probe,
                "note": "New equations use this StyleSet. Existing equations: mathmagic_rerender_equations."}

    def apply_styleset(self, name: str, make_default: bool = True) -> dict:
        applied = self.mm.apply_styleset(name, make_default=make_default, apply_current=True)
        try:   # keep size/font in state consistent with the applied StyleSet (was stale after a restore)
            info = next((s for s in stylemod.list_stylesets() if s.get("name") == name), {})
        except OSError:
            info = {}
        _save_state(style=name, style_size_pt=info.get("base_size_pt"), style_font=(info.get("variable") or {}).get("font"),
                    style_applied_at=datetime.now().isoformat(timespec="seconds"))
        return {**applied, "probe": self._probe_style(r"\frac{a}{b}+x^2")}

    def _probe_style(self, latex: str) -> dict:
        out = Path(os.environ.get("TEMP", str(Path.home()))) / "MathMagicMCP" / f"style-probe-{int(time.time())}.eps"
        r = self.render(latex, str(out), overwrite=True)
        if not r.get("ok"):
            return {"ok": False, "render": r}
        info = r["file_info"]
        return {"ok": True, "eps_fonts": info.get("fonts"), "height_pt": round(info["bbox"][3] - info["bbox"][1], 2) if info.get("bbox") else None,
                "font_warning": any(a.get("acknowledged") == "font_warning" for a in r.get("acknowledged_dialogs", []))}

    # ------------------------------------------------------------------ MathMagic lifecycle
    def launch(self) -> dict:
        focus = self.focus_factory(); t0 = time.monotonic()
        res = self.mm.launch_no_activate()
        res.update({"seconds": round(time.monotonic() - t0, 2), "focus": focus.summary()})
        if res.get("status") == "LICENSE_REQUIRED":
            res["note"] = "Authorize MathMagic (or press Try) yourself; this tool never touches the license dialog."
        return res

    def dismiss_dialogs(self) -> dict:
        handled: list = []
        for _ in range(5):
            try:
                handled.extend(self.mm.guard_dialogs(auto_ack=True))
                break
            except mmwin.MathMagicError as exc:
                if exc.status != "MATHMAGIC_ERROR":
                    return {"ok": False, "status": exc.status, "error": str(exc), "acknowledged": handled}
                handled.append({"acknowledged": "error_box", "text": str(exc)})
        return {"ok": True, "acknowledged": handled, "remaining_dialogs": [d.as_dict() for d in self.mm.dialogs()]}

    # ------------------------------------------------------------------ rendering
    def render(self, latex: str, out_path: str, overwrite: bool = False, size_pt: float | None = None,
               verify_latex: bool | None = None, capture_png: str = "", ams: bool = False, fast: bool = True,
               fix_quirks: bool | None = None) -> dict:
        """Render LaTeX to any MathMagic Save As format chosen by the file extension (.eps .pdf .svg .png .mml .tex ...)."""
        validate_latex(latex)
        verify_latex = _opt(verify_latex, DEFAULT_VERIFY_LATEX)
        rewrites: list = []
        if _opt(fix_quirks, DEFAULT_FIX_QUIRKS):
            latex, rewrites = latexcheck.fix_mathmagic_quirks(latex)
        out = Path(out_path).resolve()
        keyword = mmwin.format_keyword(str(out), ams)
        if out.exists() and not overwrite:
            raise ValueError("out_path exists; pass overwrite=true to replace it")
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            out.unlink()
        t0 = time.monotonic(); focus = self.focus_factory(); acks: list = []; check = None; shot = None
        keys: list = []; empty_retries = 0
        tex = out.with_suffix(".verify.tex")
        try:
            main = self.mm.ensure_ready(prefer_linked=False, auto_launch=True)
            for attempt in (1, 2):
                doc = self.mm.work_document(main, on_tick=focus.sample)
                keys.append(self.wait_keys())
                if fast:
                    self.mm.queue_latex(doc, latex, size_pt)  # Save As below is the ordered barrier
                else:
                    self.mm.write_latex(doc, latex, True, size_pt)
                self.mm.save_as(doc, str(out), keyword, on_tick=focus.sample, acks=acks)
                check = None
                if verify_latex:
                    if tex.exists():
                        tex.unlink()
                    self.mm.save_as(doc, str(tex), "LaTeX", on_tick=focus.sample, acks=acks)
                    check = latexcheck.compare(latex, tex.read_text(encoding="utf-8", errors="replace"))
                info = epsmod.inspect_eps(out) if out.suffix.lower() == ".eps" else {"size": out.stat().st_size}
                # Empty equation: typed characters were lost (live E2E: user holding Alt for Alt+Tab). Retry once.
                empty = (check is not None and not check.get("exported")) or (out.suffix.lower() == ".eps" and
                                                                               info.get("is_mathmagic") and not info.get("fonts"))
                if not empty or attempt == 2:
                    break
                empty_retries += 1
                for f in (out, tex):
                    if f.exists():
                        f.unlink()
            if capture_png:
                shot = w.capture_png(doc.frame, str(Path(capture_png).resolve()))
            format_ok = mmwin.output_matches_format(str(out), keyword)
            ok = format_ok and ((info.get("is_mathmagic") and info.get("has_mmf_data")) if out.suffix.lower() == ".eps" else info["size"] > 0)
            if empty or (check and check["verdict"] == "DIFFERENT"):
                ok = False
            status = ("RENDERED" if ok else "FORMAT_MISMATCH" if not format_ok else "EMPTY_RENDER" if empty
                      else "LATEX_MISMATCH" if check and check["verdict"] == "DIFFERENT" else "OUTPUT_NOT_VALID")
            held = [k for r in keys for k in r.get("held", [])]
            res = self._result(status, bool(ok), t0, focus, file=str(out), format=keyword, file_info=info,
                               latex_check=check, latex_rewrites=rewrites or None, acknowledged_dialogs=acks, capture=shot,
                               empty_render_retries=empty_retries or None,
                               user_modifier_keys_waited=({"keys": sorted(set(held)),
                                                           "seconds": round(sum(r.get("waited_s", 0) for r in keys), 2)}
                                                          if held else None))
        except mmwin.MathMagicError as exc:
            res = self._result(exc.status, False, t0, focus, error=str(exc), details=exc.details, acknowledged_dialogs=acks)
        self._log({"op": "render", "format": keyword, "latex_sha256": _sha(latex), "status": res["status"], "seconds": res["seconds"]})
        return res

    def place_eps(self, eps_path: str, marker: str, doc_name: str = "", embed: bool = True, default_baseline: bool = True,
                  replace: bool = False, remove_marker: bool = False, labels: dict | None = None) -> dict:
        mid = validate_marker(marker)
        p = Path(eps_path).resolve()
        if not p.is_file() or p.suffix.lower() != ".eps":
            raise ValueError("eps_path must be an existing .eps file")
        info = epsmod.inspect_eps(p)
        t0 = time.monotonic(); focus = self.focus_factory()
        try:
            doc = self._doc_name(doc_name)
            r = self.idc.run(ib.jsx_place_eps(doc, marker, str(p), embed, default_baseline, replace, info["descent_pt"],
                                              labels or {"id": mid, "tool": TOOL_TAG}, remove_marker))
            if not r.get("ok"):
                return self._result(r.get("error", "PLACE_FAILED"), False, t0, focus, detail=r)
            eq = r.get("equation") or {}
            # Primary proof: the placed file IS a MathMagic EPS with embedded MMF equation data (what the plugin edits).
            # The plugin's Edit Equation flag is reported too, but it is False whenever the plugin is busy with another
            # MathMagic session (verified live), so it cannot be the only criterion.
            mm_file = bool(info.get("is_mathmagic") and info.get("has_mmf_data"))
            edit = eq.get("edit_equation_enabled")
            ok = bool(eq) and not eq.get("placeholder") and mm_file
            eq["plugin_check"] = {True: "edit_equation_enabled", False: "plugin_busy_or_not_recognized",
                                  None: "not_checked (object not selectable, e.g. overset text)"}[edit]
            res = self._result("PLACED_VERIFIED" if ok else "PLACED_NOT_RECOGNIZED", ok, t0, focus, marker=marker, document=doc,
                               baseline=r.get("baseline"), equation=eq, eps_info=info, marker_removed=r.get("marker_removed", False),
                               warning="anchored in overset text" if eq.get("overset") else None)
        except ib.InDesignError as exc:
            res = self._result("INDESIGN_ERROR", False, t0, focus, error=str(exc))
        self._log({"op": "place_eps", "marker": marker, "status": res["status"], "seconds": res["seconds"]})
        return res

    def create_offline(self, latex: str, marker: str, doc_name: str = "", eps_dir: str = "", replace: bool = False,
                       remove_marker: bool = False, size_pt: float | None = None, verify_latex: bool | None = None,
                       eq_id: str = "", capture_png: str = "", _doc: str = "", _dir: Path | None = None) -> dict:
        validate_latex(latex); mid = validate_marker(marker)
        eq_id = eq_id or mid
        t0 = time.monotonic()
        doc = _doc or self._doc_name(doc_name)
        target = (_dir or self._eps_dir(doc, eps_dir)) / f"{mid}-{_sha(latex)[:10]}.eps"
        rendered = self.render(latex, str(target), overwrite=True, size_pt=size_pt, verify_latex=verify_latex,
                               capture_png=capture_png)
        if not rendered["ok"]:
            return {**rendered, "marker": marker, "mode": "offline"}
        placed = self.place_eps(str(target), marker, doc, True, True, replace, remove_marker, self._labels(eq_id, latex))
        took = bool(rendered.get("focus", {}).get("took_focus_from_user") or placed.get("focus", {}).get("took_focus_from_user"))
        return {"ok": placed["ok"], "status": "INSERTED_VERIFIED" if placed["ok"] else placed["status"], "mode": "offline",
                "marker": marker, "id": eq_id, "document": doc, "seconds": round(time.monotonic() - t0, 2), "eps": str(target),
                "render_seconds": rendered["seconds"], "place_seconds": placed["seconds"], "equation": placed.get("equation"),
                "baseline": placed.get("baseline"), "latex_check": rendered.get("latex_check"),
                "latex_rewrites": rendered.get("latex_rewrites"),
                "focus": {"foreground_start": rendered.get("focus", {}).get("foreground_start"), "took_focus_from_user": took,
                          "user_switched_apps": bool(rendered.get("focus", {}).get("user_switched_apps"))},
                "empty_render_retries": rendered.get("empty_render_retries"),
                "user_modifier_keys_waited": rendered.get("user_modifier_keys_waited"),
                "acknowledged_dialogs": rendered.get("acknowledged_dialogs"), "marker_removed": placed.get("marker_removed"),
                "error": placed.get("error") or (placed.get("detail") or {}).get("error")}

    def create_plugin(self, latex: str, marker: str, doc_name: str = "", remove_marker: bool = False,
                      size_pt: float | None = None, eq_id: str = "", _doc: str = "") -> dict:
        validate_latex(latex); mid = validate_marker(marker)
        t0 = time.monotonic(); focus = self.focus_factory(); acks: list = []
        self.mm.scope_pid = None  # the plugin may start its own MathMagic process: watch all of them
        try:
            doc = _doc or self._doc_name(doc_name)
            self.mm.guard_dialogs(strict=True)
            before = {d.frame for d in self.mm.all_documents()}
            sel = self.idc.run(ib.jsx_select_marker(doc, marker))
            if not sel.get("ok"):
                return self._result("MARKER_ERROR", False, t0, focus, detail=sel)
            if sel.get("new_equation_enabled") is False:
                return self._result("NEW_EQUATION_DISABLED", False, t0, focus)
            inv = self.idc.run(ib.jsx_invoke("New Equation"), timeout=60)
            if not inv.get("ok"):
                return self._result("PLUGIN_ACTION_FAILED", False, t0, focus, detail=inv)
            editor = self.mm.wait_linked_document(before, timeout=25, on_tick=focus.sample, acks=acks)
            keeper = self.mm.ensure_keeper(editor, on_tick=focus.sample)
            typed = latexcheck.fix_mathmagic_quirks(latex)[0] if DEFAULT_FIX_QUIRKS else latex
            self.mm.queue_latex(editor, typed, size_pt)          # Update below is the ordered barrier
            self.mm.update_linked(editor, timeout=25, on_tick=focus.sample, acks=acks)
            ver = self._verify_marker(doc, marker, wait_s=10)
            if ver["verified"]:
                self.idc.run(ib.jsx_tag_at_marker(doc, marker, self._labels(eq_id or mid, latex)))
            removed = bool(ver["verified"] and remove_marker and self.idc.run(ib.jsx_remove_marker(doc, marker)).get("ok"))
            res = self._result("INSERTED_VERIFIED" if ver["verified"] else "UPDATE_SENT_NOT_VERIFIED", ver["verified"], t0, focus,
                               mode="plugin", marker=marker, id=eq_id or mid, document=doc, equation=ver.get("equation"),
                               acknowledged_dialogs=acks, marker_removed=removed, keeper_document_created=keeper)
        except (mmwin.MathMagicError, ib.InDesignError) as exc:
            res = self._result(getattr(exc, "status", "INDESIGN_ERROR"), False, t0, focus, mode="plugin", marker=marker,
                               error=str(exc), details=getattr(exc, "details", None), acknowledged_dialogs=acks)
            if res["status"] in ("EDITOR_TIMEOUT", "LICENSE_REQUIRED"):
                res["hint"] = ("If the plugin already inserted an empty placeholder, run mathmagic_edit_equation (mode=plugin) "
                               "or mathmagic_create_equation (mode=offline, which replaces placeholders) on the same marker.")
        self._log({"op": "create_plugin", "marker": marker, "latex_sha256": _sha(latex), "status": res["status"], "seconds": res["seconds"]})
        return res

    def edit_plugin(self, latex: str, marker: str, doc_name: str = "", size_pt: float | None = None) -> dict:
        validate_latex(latex); mid = validate_marker(marker)
        t0 = time.monotonic(); focus = self.focus_factory(); acks: list = []
        self.mm.scope_pid = None
        try:
            doc = self._doc_name(doc_name)
            self.mm.guard_dialogs(strict=True)
            sel = self.idc.run(ib.jsx_select_equation(doc, marker))
            if not sel.get("ok"):
                return self._result("NO_EQUATION_AT_MARKER", False, t0, focus, detail=sel)
            old_link = sel.get("link")
            before = {d.frame for d in self.mm.all_documents()}
            inv = self.idc.run(ib.jsx_invoke("Edit Equation"), timeout=60)
            if not inv.get("ok"):
                return self._result("PLUGIN_ACTION_FAILED", False, t0, focus, detail=inv)
            editor = self.mm.wait_linked_document(before, timeout=25, on_tick=focus.sample, acks=acks)
            self.mm.ensure_keeper(editor, on_tick=focus.sample)
            self.mm.queue_latex(editor, latexcheck.fix_mathmagic_quirks(latex)[0] if DEFAULT_FIX_QUIRKS else latex, size_pt)
            self.mm.update_linked(editor, timeout=25, on_tick=focus.sample, acks=acks)
            ver = self._verify_marker(doc, marker, wait_s=10, not_link=old_link)
            if ver["verified"]:
                self.idc.run(ib.jsx_tag_at_marker(doc, marker, self._labels(mid, latex)))
            res = self._result("EDITED_VERIFIED" if ver["verified"] else "UPDATE_SENT_NOT_VERIFIED", ver["verified"], t0, focus,
                               mode="plugin", marker=marker, previous_link=old_link, equation=ver.get("equation"), acknowledged_dialogs=acks)
        except (mmwin.MathMagicError, ib.InDesignError) as exc:
            res = self._result(getattr(exc, "status", "INDESIGN_ERROR"), False, t0, focus, mode="plugin", marker=marker,
                               error=str(exc), details=getattr(exc, "details", None))
        self._log({"op": "edit_plugin", "marker": marker, "latex_sha256": _sha(latex), "status": res["status"], "seconds": res["seconds"]})
        return res

    # ------------------------------------------------------------------ batch / restyle
    def batch(self, manifest_path: str, mode: str = "offline", doc_name: str = "", start_index: int = 0,
              time_budget_s: float = 120.0, stop_on_error: bool = True, remove_markers: bool = False, eps_dir: str = "",
              replace: bool = False, skip_existing: bool = True, save_every: int = 0, size_pt: float | None = None,
              verify_latex: bool | None = None) -> dict:
        if mode not in ("offline", "plugin"):
            raise ValueError("mode must be offline or plugin")
        items = read_manifest(manifest_path)
        if not 0 <= start_index < len(items):
            raise ValueError("start_index out of range")
        budget = max(5.0, min(float(time_budget_s), 1800.0))
        journal = Path(manifest_path).resolve().with_suffix(".progress.jsonl")
        doc = self._doc_name(doc_name)
        out_dir = self._eps_dir(doc, eps_dir) if mode == "offline" else None
        t0 = time.monotonic(); results = []; index = start_index; taken = 0; done_since_save = 0; relaunches = 0
        while index < len(items) and time.monotonic() - t0 < budget:
            item = items[index]; sha = _sha(item["latex"]); eid = item.get("id") or validate_marker(item["marker"])
            r = None
            if skip_existing:
                cur = self.idc.run(ib.jsx_equation_at_marker(doc, item["marker"], False))
                eq = cur.get("equation")
                if cur.get("marker_count") != 1:
                    r = {"ok": False, "status": "MARKER_ERROR", "error": f"marker count {cur.get('marker_count')}"}
                elif eq and not eq.get("placeholder"):
                    if eq.get("labels", {}).get("sha") == sha and not replace:
                        r = {"ok": True, "status": "SKIPPED_ALREADY_DONE"}
                    elif not replace:
                        r = {"ok": True, "status": "SKIPPED_EXISTING_EQUATION"}
            if r is None:
                isz = item.get("size_pt", size_pt)
                for attempt in (1, 2):
                    if mode == "offline":
                        r = self.create_offline(item["latex"], item["marker"], doc, "", replace, remove_markers, isz,
                                                verify_latex, eid, _doc=doc, _dir=out_dir)
                    else:
                        r = self.create_plugin(item["latex"], item["marker"], doc, remove_markers, isz, eid, _doc=doc)
                    if r["ok"] or r.get("status") not in RECOVERABLE or attempt == 2:
                        break
                    relaunch = self.mm.launch_no_activate()         # MathMagic exited/crashed: restart once
                    relaunches += 1
                    if not relaunch.get("ok"):
                        r = {**r, "status": relaunch.get("status", "LAUNCH_FAILED"), "ok": False}
                        break
                taken += bool(r.get("focus", {}).get("took_focus_from_user"))
                if r["ok"]:
                    done_since_save += 1
            entry = {"index": index, "id": eid, "marker": item["marker"], "ok": r["ok"], "status": r["status"],
                     "seconds": r.get("seconds"), "error": r.get("error")}
            if r.get("latex_check"):
                entry["latex_check"] = r["latex_check"]["verdict"]
                if r["latex_check"]["verdict"] == "DIFFERENT" or r["status"] == "EMPTY_RENDER":
                    entry["latex_exported"] = (r["latex_check"].get("exported") or "")[:300]   # what MathMagic built
            for key in ("empty_render_retries", "user_modifier_keys_waited", "latex_rewrites"):
                if r.get(key):
                    entry[key] = r[key]
            if (r.get("focus") or {}).get("user_switched_apps"):
                entry["user_switched_apps"] = True
            results.append(entry)
            try:
                with journal.open("a", encoding="utf-8") as fp:
                    fp.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "sha": sha, **entry}, ensure_ascii=False) + "\n")
            except OSError:
                pass
            index += 1
            if save_every and done_since_save >= save_every:
                self.idc.run(ib.jsx_save_document(doc)); done_since_save = 0
            if not r["ok"] and (stop_on_error or r.get("status") == "LICENSE_REQUIRED"):
                break
        if save_every and done_since_save:
            self.idc.run(ib.jsx_save_document(doc))
        elapsed = time.monotonic() - t0
        worked = [x for x in results if not str(x["status"]).startswith("SKIPPED")]
        return {"ok": all(x["ok"] for x in results), "mode": mode, "document": doc, "processed": len(results),
                "inserted": sum(x["status"] == "INSERTED_VERIFIED" for x in results),
                "skipped": sum(str(x["status"]).startswith("SKIPPED") for x in results),
                "failed": sum(not x["ok"] for x in results), "next_index": index if index < len(items) else None,
                "total": len(items), "seconds": round(elapsed, 2),
                "seconds_per_inserted": round(sum(x["seconds"] or 0 for x in worked) / max(len(worked), 1), 2),
                "items_taking_focus_from_user_app": taken, "mathmagic_relaunches": relaunches, "journal": str(journal),
                "results": results,
                "note": "Call again with start_index=next_index (finished items are skipped automatically)." if index < len(items) else "Manifest finished."}

    def rerender(self, doc_name: str = "", ids: list[str] | None = None, eps_dir: str = "", time_budget_s: float = 120.0,
                 only_style_differs: bool = True) -> dict:
        """Re-render tagged equations from their stored LaTeX with the current StyleSet and replace them in place."""
        doc = self._doc_name(doc_name)
        eqs = self.idc.run(ib.jsx_list_equations(doc, True), timeout=120).get("equations", [])
        current_style = _state().get("style", "default")
        todo = [e for e in eqs if e.get("id") and e.get("latex") and (not ids or e["id"] in ids)
                and (not only_style_differs or e.get("style") != current_style)]
        out_dir = self._eps_dir(doc, eps_dir)
        t0 = time.monotonic(); results = []
        for e in todo:
            if time.monotonic() - t0 > max(5.0, min(time_budget_s, 1800.0)):
                break
            target = out_dir / f"{e['id']}-{_sha(e['latex'])[:10]}-{re.sub(r'[^A-Za-z0-9_-]', '_', current_style)[:20]}.eps"
            r = self.render(e["latex"], str(target), overwrite=True)
            if r["ok"]:
                info = r["file_info"]
                p = self.idc.run(ib.jsx_replace_by_id(doc, e["id"], str(target), True, True, info.get("descent_pt"),
                                                      self._labels(e["id"], e["latex"])))
                ok = bool(p.get("ok"))
                results.append({"id": e["id"], "ok": ok, "status": "RESTYLED" if ok else p.get("error"), "seconds": r["seconds"]})
            else:
                results.append({"id": e["id"], "ok": False, "status": r["status"], "error": r.get("error")})
                break
        remaining = len(todo) - len(results)
        return {"ok": all(x["ok"] for x in results), "document": doc, "style": current_style, "candidates": len(todo),
                "restyled": sum(x["ok"] for x in results), "remaining": remaining, "seconds": round(time.monotonic() - t0, 2),
                "results": results, "note": "Untagged equations (made before v0.4 or by hand) cannot be re-rendered automatically."}

    def cleanup_marker(self, marker: str, doc_name: str = "", require_equation: bool = True) -> dict:
        validate_marker(marker)
        doc = self._doc_name(doc_name)
        if require_equation:
            ver = self._verify_marker(doc, marker)
            if not ver["verified"]:
                return {"ok": False, "status": "NO_VERIFIED_EQUATION", "detail": ver}
        return {"ok": bool(self.idc.run(ib.jsx_remove_marker(doc, marker)).get("ok")), "marker": marker}
