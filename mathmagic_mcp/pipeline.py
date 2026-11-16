"""High-level MathMagic + InDesign workflows for v0.3 (message adapter, no keyboard/mouse/clipboard).

Two creation modes:
- "plugin":  InDesign plugin New Equation -> MathMagic linked editor (messages) -> Update.
             Verified end-to-end. The *plugin itself* brings MathMagic, then InDesign, to the front.
- "offline": MathMagic renders an EPS file via messages + Save As dialog (no plugin), then the EPS is
             placed inline at the marker by InDesign scripting, embedded, and baseline-aligned.
             Designed to avoid any foreground change; verify with the returned focus report.
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
from . import mmwin
from . import win32util as w

_MARKER = re.compile(r"^\[\[MM:([A-Za-z0-9_-]{1,40})\]\]$")
_FORBIDDEN = re.compile(r"\\(?:write18|input|include|openout|read|catcode|def|special|immediate|loop|csname)\b", re.I)
MAX_BATCH = 2000


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
    if p.suffix.lower() != ".json" or not p.is_file() or p.stat().st_size > 5 * 1024 * 1024:
        raise ValueError("Manifest must be an existing .json file up to 5 MB")
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
        seen.add(item["marker"])
    return items


def _sha(latex: str) -> str:
    return hashlib.sha256(latex.encode("utf-8")).hexdigest()


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

    # ------------------------------------------------------------------ helpers
    def _log(self, event: dict) -> str | None:
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            path = self.log_dir / ("mm-v03-" + datetime.now(timezone.utc).strftime("%Y%m%d") + ".jsonl")
            with path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), **event}, ensure_ascii=False) + "\n")
            return str(path)
        except OSError:
            return None

    def _doc_name(self, doc_name: str) -> str:
        st = self.idc.run(ib.jsx_documents())
        names = [d["name"] for d in st.get("documents", [])]
        if not names:
            raise ib.InDesignError("NO_DOCUMENT_OPEN")
        if doc_name:
            if doc_name not in names:
                raise ib.InDesignError(f"DOCUMENT_NOT_OPEN: {doc_name}; open: {names}")
            return doc_name
        return st.get("active") or names[0]

    def _result(self, status: str, ok: bool, t0: float, focus, **extra) -> dict:
        res = {"ok": ok, "status": status, "seconds": round(time.monotonic() - t0, 2)}
        if focus is not None:
            res["focus"] = focus.summary()
        res.update(extra)
        return res

    def _verify_marker(self, doc: str, marker: str, wait_s: float = 0.0, not_link: str | None = None) -> dict:
        end = time.monotonic() + wait_s
        while True:
            info = self.idc.run(ib.jsx_equation_at_marker(doc, marker))
            eq = info.get("equation")
            good = bool(eq and not eq.get("placeholder") and (not_link is None or eq.get("link") != not_link))
            if good or time.monotonic() >= end:
                return {"verified": good, **info}
            self.sleep(0.15)

    # ------------------------------------------------------------------ read-only tools
    def status(self) -> dict:
        res: dict = {"ok": True, "mathmagic": self.mm.status() if w.IS_WINDOWS else {"running": False}}
        res["indesign_running"] = self.idc.running()
        if res["indesign_running"]:
            try:
                st = self.idc.run(ib.jsx_status())
                res["indesign"] = {"documents": st.get("documents"), "active": st.get("active"),
                                   "selection": st.get("selection"), "mathmagic_actions": st.get("actions")}
            except ib.InDesignError as exc:
                res["indesign_error"] = str(exc)
        res["foreground"] = w.foreground() if w.IS_WINDOWS else None
        return res

    def verify(self, marker: str, doc_name: str = "") -> dict:
        validate_marker(marker)
        doc = self._doc_name(doc_name)
        info = self._verify_marker(doc, marker)
        eq = info.get("equation") or {}
        info["assessment"] = ("NATIVE_MATHMAGIC_EQUATION" if info["verified"] and eq.get("edit_equation_enabled")
                              else "PLACEHOLDER_ONLY" if eq.get("placeholder") else "NO_EQUATION" if not eq else "UNRECOGNIZED")
        info["note"] = "Checks object type, link and plugin recognition; mathematical content is checked visually or via capture."
        return info

    def capture_editor(self, out_png: str) -> dict:
        docs = self.mm.all_documents()
        if not docs:
            return {"ok": False, "error": "No open MathMagic equation window"}
        doc = docs[0]
        return {"ok": True, "window": doc.title, **w.capture_png(doc.frame, str(Path(out_png).resolve()))}

    # ------------------------------------------------------------------ mutating tools
    def launch(self) -> dict:
        focus = self.focus_factory(); t0 = time.monotonic()
        res = self.mm.launch_no_activate()
        res.update({"seconds": round(time.monotonic() - t0, 2), "focus": focus.summary()})
        if res.get("status") == "LICENSE_REQUIRED":
            res["note"] = "Authorize MathMagic (or press Try) yourself; this tool never touches the license dialog."
        return res

    def dismiss_dialogs(self) -> dict:
        try:
            handled = self.mm.guard_dialogs(auto_ack=True)
        except mmwin.MathMagicError as exc:
            return {"ok": False, "status": exc.status, "error": str(exc), **exc.details}
        remaining = [d.as_dict() for d in self.mm.dialogs()]
        return {"ok": True, "acknowledged": handled, "remaining_dialogs": remaining}

    def create_plugin(self, latex: str, marker: str, doc_name: str = "", remove_marker: bool = False,
                      capture_png: str = "") -> dict:
        validate_latex(latex); validate_marker(marker)
        t0 = time.monotonic(); focus = self.focus_factory(); acks: list = []
        try:
            doc = self._doc_name(doc_name)
            self.mm.guard_dialogs()
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
            self.mm.write_latex(editor, latex, replace=True)
            shot = w.capture_png(editor.frame, capture_png) if capture_png else None
            self.mm.update_linked(editor, timeout=25, on_tick=focus.sample, acks=acks)
            ver = self._verify_marker(doc, marker, wait_s=10)
            removed = False
            if ver["verified"] and remove_marker:
                removed = bool(self.idc.run(ib.jsx_remove_marker(doc, marker)).get("ok"))
            status = "INSERTED_VERIFIED" if ver["verified"] else "UPDATE_SENT_NOT_VERIFIED"
            res = self._result(status, ver["verified"], t0, focus, mode="plugin", marker=marker, document=doc,
                               equation=ver.get("equation"), acknowledged_dialogs=acks, marker_removed=removed,
                               capture=shot, keeper_document_created=keeper)
        except (mmwin.MathMagicError, ib.InDesignError) as exc:
            res = self._result(getattr(exc, "status", "INDESIGN_ERROR"), False, t0, focus, mode="plugin",
                               marker=marker, error=str(exc), details=getattr(exc, "details", None), acknowledged_dialogs=acks)
            if res["status"] in ("EDITOR_TIMEOUT", "LICENSE_REQUIRED"):
                res["hint"] = ("If the plugin already inserted an empty placeholder before the marker, run "
                               "mathmagic_edit_equation (mode=plugin) on the same marker once MathMagic is ready.")
        self._log({"op": "create_plugin", "marker": marker, "latex_sha256": _sha(latex),
                   **{k: res.get(k) for k in ("status", "seconds")}})
        return res

    def edit_plugin(self, latex: str, marker: str, doc_name: str = "") -> dict:
        validate_latex(latex); validate_marker(marker)
        t0 = time.monotonic(); focus = self.focus_factory(); acks: list = []
        try:
            doc = self._doc_name(doc_name)
            self.mm.guard_dialogs()
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
            self.mm.write_latex(editor, latex, replace=True)
            self.mm.update_linked(editor, timeout=25, on_tick=focus.sample, acks=acks)
            ver = self._verify_marker(doc, marker, wait_s=10, not_link=old_link)
            res = self._result("EDITED_VERIFIED" if ver["verified"] else "UPDATE_SENT_NOT_VERIFIED", ver["verified"],
                               t0, focus, mode="plugin", marker=marker, previous_link=old_link,
                               equation=ver.get("equation"), acknowledged_dialogs=acks)
        except (mmwin.MathMagicError, ib.InDesignError) as exc:
            res = self._result(getattr(exc, "status", "INDESIGN_ERROR"), False, t0, focus, mode="plugin",
                               marker=marker, error=str(exc), details=getattr(exc, "details", None))
        self._log({"op": "edit_plugin", "marker": marker, "latex_sha256": _sha(latex),
                   **{k: res.get(k) for k in ("status", "seconds")}})
        return res

    def render_eps(self, latex: str, out_path: str, overwrite: bool = False, capture_png: str = "") -> dict:
        validate_latex(latex)
        out = Path(out_path).resolve()
        if out.suffix.lower() != ".eps":
            raise ValueError("out_path must end with .eps")
        if out.exists() and not overwrite:
            raise ValueError("out_path exists; pass overwrite=true to replace it")
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            out.unlink()
        t0 = time.monotonic(); focus = self.focus_factory(); acks: list = []
        try:
            self.mm.guard_dialogs()
            if not self.mm.mains():
                launched = self.mm.launch_no_activate()
                if not launched.get("ok"):
                    raise mmwin.MathMagicError(launched.get("status", "LAUNCH_FAILED"),
                                               "MathMagic could not be started without user action", launch=launched)
            main = self.mm.pick_main(prefer_linked=False)
            doc = self.mm.work_document(main, on_tick=focus.sample)  # kept open: MathMagic InD quits on last close
            self.mm.write_latex(doc, latex, replace=True)
            shot = w.capture_png(doc.frame, capture_png) if capture_png else None
            self.mm.save_as(doc, str(out), "EPS", on_tick=focus.sample, acks=acks)
            info = epsmod.inspect_eps(out)
            ok = info["is_mathmagic"] and info["has_mmf_data"]
            res = self._result("EPS_RENDERED" if ok else "EPS_NOT_MATHMAGIC", ok, t0, focus, mode="offline",
                               eps=str(out), eps_info=info, acknowledged_dialogs=acks, capture=shot)
        except mmwin.MathMagicError as exc:
            res = self._result(exc.status, False, t0, focus, mode="offline", error=str(exc), details=exc.details)
        self._log({"op": "render_eps", "latex_sha256": _sha(latex), **{k: res.get(k) for k in ("status", "seconds")}})
        return res

    def place_eps(self, eps_path: str, marker: str, doc_name: str = "", embed: bool = True,
                  default_baseline: bool = True, replace: bool = False, remove_marker: bool = False) -> dict:
        validate_marker(marker)
        p = Path(eps_path).resolve()
        if not p.is_file() or p.suffix.lower() != ".eps":
            raise ValueError("eps_path must be an existing .eps file")
        info = epsmod.inspect_eps(p)
        t0 = time.monotonic(); focus = self.focus_factory()
        try:
            doc = self._doc_name(doc_name)
            res_js = self.idc.run(ib.jsx_place_eps(doc, marker, str(p), embed, default_baseline, replace, info["descent_pt"]))
            if not res_js.get("ok"):
                return self._result("PLACE_FAILED", False, t0, focus, detail=res_js)
            ver = self._verify_marker(doc, marker)
            removed = False
            if ver["verified"] and remove_marker:
                removed = bool(self.idc.run(ib.jsx_remove_marker(doc, marker)).get("ok"))
            res = self._result("PLACED_VERIFIED" if ver["verified"] else "PLACED_NOT_VERIFIED", ver["verified"], t0, focus,
                               marker=marker, document=doc, placed=res_js, equation=ver.get("equation"),
                               eps_info=info, marker_removed=removed)
        except ib.InDesignError as exc:
            res = self._result("INDESIGN_ERROR", False, t0, focus, error=str(exc))
        self._log({"op": "place_eps", "marker": marker, **{k: res.get(k) for k in ("status", "seconds")}})
        return res

    def _eps_dir(self, doc: str, eps_dir: str) -> Path:
        if eps_dir:
            return Path(eps_dir).resolve()
        st = self.idc.run(ib.jsx_documents())
        path = next((d.get("path") for d in st.get("documents", []) if d["name"] == doc), "")
        if not path:
            raise ValueError("Save the InDesign document first or pass eps_dir")
        p = Path(path)
        return p.parent / (p.stem + ".mathmagic-eps")

    def create_offline(self, latex: str, marker: str, doc_name: str = "", eps_dir: str = "",
                       replace: bool = False, remove_marker: bool = False, capture_png: str = "") -> dict:
        validate_latex(latex); mid = validate_marker(marker)
        t0 = time.monotonic()
        doc = self._doc_name(doc_name)
        target = self._eps_dir(doc, eps_dir) / f"{mid}-{_sha(latex)[:10]}.eps"
        rendered = self.render_eps(latex, str(target), overwrite=True, capture_png=capture_png)
        if not rendered["ok"]:
            return {**rendered, "marker": marker}
        placed = self.place_eps(str(target), marker, doc, embed=True, default_baseline=True,
                                replace=replace, remove_marker=remove_marker)
        changes = rendered["focus"]["foreground_changes"] + placed.get("focus", {}).get("foreground_changes", [])
        took = bool(rendered["focus"].get("took_focus_from_user") or placed.get("focus", {}).get("took_focus_from_user"))
        return {"ok": placed["ok"], "status": "INSERTED_VERIFIED" if placed["ok"] else placed["status"], "mode": "offline",
                "marker": marker, "document": doc, "seconds": round(time.monotonic() - t0, 2), "eps": str(target),
                "render_seconds": rendered["seconds"], "place_seconds": placed["seconds"],
                "equation": placed.get("equation"), "baseline": (placed.get("placed") or {}).get("baseline"),
                "focus": {"foreground_start": rendered["focus"].get("foreground_start"), "foreground_changed": bool(changes),
                          "took_focus_from_user": took, "foreground_changes": changes},
                "acknowledged_dialogs": rendered.get("acknowledged_dialogs"), "marker_removed": placed.get("marker_removed")}

    def batch(self, manifest_path: str, mode: str = "offline", doc_name: str = "", start_index: int = 0,
              time_budget_s: float = 45.0, stop_on_error: bool = True, remove_markers: bool = False,
              eps_dir: str = "", replace: bool = False) -> dict:
        if mode not in ("offline", "plugin"):
            raise ValueError("mode must be offline or plugin")
        items = read_manifest(manifest_path)
        if not 0 <= start_index < len(items):
            raise ValueError("start_index out of range")
        budget = max(5.0, min(float(time_budget_s), 600.0))
        t0 = time.monotonic(); results = []; index = start_index; focus_changes = 0; focus_taken = 0
        while index < len(items) and time.monotonic() - t0 < budget:
            item = items[index]
            if mode == "offline":
                r = self.create_offline(item["latex"], item["marker"], doc_name, eps_dir, replace, remove_markers)
            else:
                r = self.create_plugin(item["latex"], item["marker"], doc_name, remove_markers)
            focus_changes += bool(r.get("focus", {}).get("foreground_changed"))
            focus_taken += bool(r.get("focus", {}).get("took_focus_from_user"))
            results.append({"index": index, "id": item.get("id"), "marker": item["marker"], "ok": r["ok"],
                            "status": r["status"], "seconds": r.get("seconds"), "error": r.get("error")})
            index += 1
            if not r["ok"] and stop_on_error:
                break
        done = [r for r in results if r["ok"]]
        elapsed = time.monotonic() - t0
        return {"ok": all(r["ok"] for r in results), "mode": mode, "processed": len(results), "succeeded": len(done),
                "next_index": index if index < len(items) else None, "total": len(items),
                "seconds": round(elapsed, 2), "seconds_per_equation": round(elapsed / max(len(results), 1), 2),
                "items_with_foreground_change": focus_changes, "items_taking_focus_from_user_app": focus_taken,
                "results": results,
                "note": "Call again with start_index=next_index to continue." if index < len(items) else "Manifest finished."}

    def cleanup_marker(self, marker: str, doc_name: str = "", require_equation: bool = True) -> dict:
        validate_marker(marker)
        doc = self._doc_name(doc_name)
        if require_equation:
            ver = self._verify_marker(doc, marker)
            if not ver["verified"]:
                return {"ok": False, "status": "NO_VERIFIED_EQUATION", "detail": ver}
        return {"ok": bool(self.idc.run(ib.jsx_remove_marker(doc, marker)).get("ok")), "marker": marker}
