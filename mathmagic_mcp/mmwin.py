"""MathMagic Pro 9.31 (InDesign edition) window model and message-only editor operations.

Verified on the user's machine (16.11.2026):
- MFC MDI app; menu command IDs below drive the editor without focus.
- WM_CHAR delivered with SendMessageTimeout types into the equation view.
- In InDesign-linked mode, Ctrl+S is "Update" (32880) and returns the equation.
Never: SetFocus/SetForegroundWindow, SendInput/keybd_event, clipboard.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import win32util as w

CMD = {
    "new": int(os.environ.get("MM_CMD_NEW", 57600)),
    "close_doc": 32901,
    "save": int(os.environ.get("MM_CMD_SAVE", 57603)),
    "save_as": int(os.environ.get("MM_CMD_SAVE_AS", 57604)),
    "save_copy": int(os.environ.get("MM_CMD_SAVE_COPY", 32881)),
    "update": int(os.environ.get("MM_CMD_UPDATE", 32880)),
    "select_all": int(os.environ.get("MM_CMD_SELECT_ALL", 57642)),
    "delete": int(os.environ.get("MM_CMD_DELETE", 32825)),
    "convert_tex": int(os.environ.get("MM_CMD_CONVERT_TEX", 32922)),
}
LINKED_PREFIX = "From InDesign"
SAVE_TYPE_COMBO = 1136
SAVE_NAME_FIELD = 1148
IDOK, IDCANCEL, IDNO = 1, 2, 7


class MathMagicError(RuntimeError):
    def __init__(self, status: str, message: str, **details):
        super().__init__(message)
        self.status = status
        self.details = details


@dataclass
class Dialog:
    hwnd: int
    pid: int
    title: str
    texts: list[str] = field(default_factory=list)
    has_save_type_combo: bool = False

    @property
    def kind(self) -> str:
        return classify_dialog(self.title, self.texts, self.has_save_type_combo)

    def as_dict(self) -> dict:
        return {"hwnd": self.hwnd, "pid": self.pid, "title": self.title, "kind": self.kind, "texts": self.texts[:6]}


def classify_dialog(title: str, texts: list[str], has_save_type_combo: bool = False) -> str:
    joined = "\n".join(texts).lower()
    if title == "Authorization" or "license code" in joined:
        return "license"
    if title == "Tip of the Day":
        return "tip"
    if "postscript name" in joined:
        return "font_warning"
    if has_save_type_combo:
        return "save_as"
    if "save changes" in joined or "değişiklik" in joined or ("kaydet" in joined and "?" in joined):
        return "save_changes"
    return "unknown"


@dataclass
class Document:
    frame: int
    view: int
    title: str
    main: int

    @property
    def linked(self) -> bool:
        return self.title.startswith(LINKED_PREFIX)


class MathMagicWindows:
    def __init__(self, exe_path: str, sleep: Callable[[float], None] = time.sleep):
        self.exe_path = os.path.normcase(os.path.abspath(exe_path))
        self.exe_name = os.path.basename(exe_path)
        self.sleep = sleep

    # ---------- discovery (read-only)
    def _is_mm(self, hwnd: int) -> bool:
        path = w.image_path(w.pid_of(hwnd))
        return bool(path) and os.path.normcase(os.path.abspath(path)) == self.exe_path

    def visible_top(self) -> list[int]:
        return w.top_windows(lambda h: w.is_visible(h) and self._is_mm(h))

    def mains(self) -> list[dict]:
        out = []
        for h in self.visible_top():
            if w.has_menu(h) and w.class_name(h) != "#32770":
                out.append({"hwnd": h, "pid": w.pid_of(h), "title": w.text(h),
                            "linked_mode": w.text(h).startswith(LINKED_PREFIX), "enabled": w.is_enabled(h)})
        return out

    def dialogs(self) -> list[Dialog]:
        result = []
        for h in self.visible_top():
            if w.class_name(h) != "#32770":
                continue
            kids = w.descendants(h)
            texts = [t for t in (w.text(k) for k in kids) if t.strip()]
            has_combo = any(w.ctrl_id(k) == SAVE_TYPE_COMBO and w.class_name(k) == "ComboBox" for k in kids)
            result.append(Dialog(h, w.pid_of(h), w.text(h), texts, has_combo))
        return result

    def documents(self, main: int) -> list[Document]:
        docs = []
        mdi = w.find_child_class(main, "MDIClient")
        child = w.first_child(mdi) if mdi else 0
        while child:
            docs.append(Document(child, w.first_child(child), w.text(child), main))
            child = w.next_sibling(child)
        return docs

    def all_documents(self) -> list[Document]:
        return [d for m in self.mains() for d in self.documents(m["hwnd"])]

    def status(self) -> dict:
        pids = sorted(pid for pid, name in w.process_names().items() if name.lower() == self.exe_name.lower())
        dialogs = [d.as_dict() for d in self.dialogs()]
        return {"running": bool(pids), "pids": pids, "main_windows": self.mains(),
                "documents": [{"title": d.title, "linked": d.linked} for d in self.all_documents()],
                "dialogs": dialogs,
                "license_blocked": any(d["kind"] == "license" for d in dialogs)}

    # ---------- dialog handling
    def guard_dialogs(self, auto_ack: bool = True) -> list[dict]:
        """Acknowledge only known harmless dialogs; raise on license / unknown modal dialogs."""
        handled = []
        for d in self.dialogs():
            kind = d.kind
            if kind == "license":
                raise MathMagicError("LICENSE_REQUIRED", "MathMagic Authorization dialog is open; a person must authorize or press Try.",
                                     dialog=d.as_dict())
            if kind in ("font_warning", "tip") and auto_ack:
                w.post(d.hwnd, w.WM_COMMAND, IDCANCEL, 0)  # font warning's only button is id 2; Tip closes on cancel
                handled.append({"acknowledged": kind, "text": (d.texts[-1] if d.texts else "")[:160]})
        return handled

    def wait_for(self, predicate: Callable[[], object], timeout: float, on_tick: Callable[[], None] | None = None,
                 auto_ack: bool = True, acks: list | None = None, interval: float = 0.04):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if on_tick:
                on_tick()
            handled = self.guard_dialogs(auto_ack)
            if acks is not None:
                acks.extend(handled)
            value = predicate()
            if value:
                return value
            self.sleep(interval)
        return None

    # ---------- launch
    def launch_no_activate(self, timeout: float = 30.0) -> dict:
        if self.mains():
            return {"ok": True, "status": "ALREADY_RUNNING", **self.status()}
        code = w.shell_open_no_activate(self.exe_path)
        end = time.monotonic() + timeout
        acked: list = []
        while time.monotonic() < end:
            st = self.status()
            if st["license_blocked"]:
                return {"ok": False, "status": "LICENSE_REQUIRED", "shell_code": code, **st}
            acked.extend(self.guard_dialogs(auto_ack=True))  # Tip of the Day keeps the main window disabled
            if st["main_windows"] and all(m["enabled"] for m in st["main_windows"]):
                return {"ok": True, "status": "READY", "shell_code": code, "acknowledged": acked, **st}
            self.sleep(0.25)
        return {"ok": False, "status": "TIMEOUT", "shell_code": code, **self.status()}

    def pick_main(self, prefer_linked: bool = False) -> int:
        mains = [m for m in self.mains() if m["enabled"]]
        if not mains:
            self.guard_dialogs(auto_ack=False)
            raise MathMagicError("MATHMAGIC_NOT_READY", "No enabled MathMagic main window. Launch MathMagic (mathmagic_launch).")
        mains.sort(key=lambda m: m["linked_mode"] != prefer_linked)
        return mains[0]["hwnd"]

    # ---------- editor operations (messages only)
    def activate(self, doc: Document) -> None:
        """Make doc the active MDI child (WM_MDIACTIVATE). Menu commands go to the active child.
        This changes MathMagic's internal active document only, never the Windows foreground."""
        mdi = w.find_child_class(doc.main, "MDIClient")
        if mdi:
            w.send_timeout(mdi, 0x0222, doc.frame, 0)

    def work_document(self, main: int, on_tick=None) -> Document:
        """Reusable unlinked document; MathMagic InD quits when its last document closes, so we keep one open."""
        doc = next((d for d in self.documents(main) if not d.linked and d.view), None)
        return doc or self.new_document(main, on_tick=on_tick)

    def ensure_keeper(self, linked_doc: Document, on_tick=None) -> bool:
        """Keep the MathMagic process alive after Update closes the linked window."""
        if any(not d.linked for d in self.documents(linked_doc.main)):
            return False
        self.new_document(linked_doc.main, on_tick=on_tick)
        self.activate(linked_doc)
        return True

    def new_document(self, main: int, timeout: float = 5.0, on_tick=None) -> Document:
        before = {d.frame for d in self.documents(main)}
        w.post(main, w.WM_COMMAND, CMD["new"], 0)
        doc = self.wait_for(lambda: next((d for d in self.documents(main) if d.frame not in before and d.view), None), timeout, on_tick)
        if not doc:
            raise MathMagicError("NEW_DOCUMENT_TIMEOUT", "MathMagic did not open a new equation window")
        return doc

    def write_latex(self, doc: Document, latex: str, replace: bool = True) -> None:
        self.activate(doc)
        if replace:
            w.send_timeout(doc.main, w.WM_COMMAND, CMD["select_all"])
            w.send_timeout(doc.main, w.WM_COMMAND, CMD["delete"])
        if not w.type_chars(doc.view, latex):
            raise MathMagicError("TYPE_FAILED", "MathMagic did not accept WM_CHAR input in time")
        w.send_timeout(doc.main, w.WM_COMMAND, CMD["select_all"])
        if not w.send_timeout(doc.main, w.WM_COMMAND, CMD["convert_tex"], timeout_ms=8000):
            raise MathMagicError("CONVERT_TIMEOUT", "Convert TeX to equation did not finish in time")

    def update_linked(self, doc: Document, timeout: float = 20.0, on_tick=None, acks: list | None = None) -> None:
        if not doc.linked:
            raise MathMagicError("NOT_LINKED", "Update requires an InDesign-linked MathMagic window")
        self.activate(doc)
        w.post(doc.main, w.WM_COMMAND, CMD["update"], 0)
        closed = self.wait_for(lambda: not w.is_window(doc.frame), timeout, on_tick, acks=acks)
        if not closed:
            raise MathMagicError("UPDATE_TIMEOUT", "Linked equation window did not close after Update",
                                 dialogs=[d.as_dict() for d in self.dialogs()])

    def save_as(self, doc: Document, out_path: str, type_keyword: str = "EPS", timeout: float = 10.0,
                on_tick=None, acks: list | None = None) -> str:
        out = str(Path(out_path).resolve())
        self.activate(doc)
        find_dialog = lambda: next((d for d in self.dialogs() if d.kind == "save_as"), None)  # noqa: E731
        commands = [CMD["save_copy"]] if doc.linked else [CMD["save_as"]]
        if not doc.linked and w.text(doc.frame).startswith("Equation-"):
            commands.append(CMD["save"])  # untitled doc: plain Save also opens Save As (verified)
        dlg = None
        for command in commands:
            w.post(doc.main, w.WM_COMMAND, command, 0)
            dlg = self.wait_for(find_dialog, 3.0, on_tick, acks=acks)
            if dlg:
                break
        if not dlg:
            raise MathMagicError("SAVE_DIALOG_TIMEOUT", "Save As dialog did not appear")
        kids = w.descendants(dlg.hwnd)
        combo = next(k for k in kids if w.ctrl_id(k) == SAVE_TYPE_COMBO and w.class_name(k) == "ComboBox")
        items = w.combo_items(combo)
        index = next((i for i, item in enumerate(items) if item.startswith(("MathMagic " + type_keyword, type_keyword))), None)
        if index is None:
            index = next((i for i, item in enumerate(items) if type_keyword.lower() in item.lower()), None)
        if index is None:
            w.post(dlg.hwnd, w.WM_COMMAND, IDCANCEL, 0)
            raise MathMagicError("SAVE_TYPE_NOT_FOUND", f"No '{type_keyword}' entry in Save As types", types=items)
        w.send(combo, w.CB_SETCURSEL, index, 0)
        w.send(w.parent(combo), w.WM_COMMAND, (w.CBN_SELCHANGE << 16) | SAVE_TYPE_COMBO, combo)
        name_edit = next((k for k in kids if w.ctrl_id(k) == SAVE_NAME_FIELD and w.class_name(k) == "Edit"), 0)
        if not name_edit:
            w.post(dlg.hwnd, w.WM_COMMAND, IDCANCEL, 0)
            raise MathMagicError("SAVE_FIELD_NOT_FOUND", "File name field not found in Save As dialog")
        w.set_text(name_edit, out)
        w.post(dlg.hwnd, w.WM_COMMAND, IDOK, 0)
        state = {"size": -1, "stable": 0}

        def ready() -> bool:
            """File written completely: dialog gone, readable, non-empty, size stable for 2 polls."""
            if w.is_window(dlg.hwnd) or not os.path.isfile(out):
                return False
            try:
                size = os.path.getsize(out)
                with open(out, "rb"):
                    pass
            except OSError:
                return False
            state["stable"] = state["stable"] + 1 if size > 0 and size == state["size"] else 0
            state["size"] = size
            return state["stable"] >= 2
        done = self.wait_for(ready, timeout + 10, on_tick, acks=acks, interval=0.08)
        if not done:
            leftovers = [d.as_dict() for d in self.dialogs()]
            for d in self.dialogs():
                if d.kind == "save_as":
                    w.post(d.hwnd, w.WM_COMMAND, IDCANCEL, 0)
            raise MathMagicError("SAVE_TIMEOUT", "File was not written", dialogs=leftovers)
        return out

    def close_document(self, doc: Document, discard: bool = True, timeout: float = 5.0) -> bool:
        w.post(doc.frame, w.WM_CLOSE, 0, 0)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if not w.is_window(doc.frame):
                return True
            for d in self.dialogs():
                if d.kind == "save_changes" and discard:
                    w.post(d.hwnd, w.WM_COMMAND, IDNO, 0)
            self.sleep(0.05)
        return False

    def wait_linked_document(self, before: set[int], timeout: float = 20.0, on_tick=None, acks=None) -> Document:
        doc = self.wait_for(lambda: next((d for d in self.all_documents()
                                          if d.linked and d.frame not in before and d.view and w.is_enabled(d.main)), None),
                            timeout, on_tick, acks=acks)
        if not doc:
            raise MathMagicError("EDITOR_TIMEOUT", "No InDesign-linked MathMagic editor window appeared",
                                 status=self.status())
        return doc
