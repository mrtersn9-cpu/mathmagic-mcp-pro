"""MathMagic Pro 9.31 (InDesign edition) window model and message-only editor operations.

Verified on the user's machine (16.11.2026):
- MFC MDI app; menu command IDs below drive the editor without focus.
- WM_CHAR typed into the equation view, Select All + Convert TeX turn it into an equation.
- In InDesign-linked mode, Ctrl+S is "Update" (32880) and returns the equation.
- MathMagic InD quits when its last document closes -> a work document is kept open.
- Posting commands while a modal dialog is opening can crash MathMagic (0xc000041d) ->
  every wait loop stops on unexpected dialogs and nothing is posted while one is open.
Never: SetFocus/SetForegroundWindow, SendInput/keybd_event, clipboard.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from . import win32util as w

CMD = {
    "new": 57600, "open": 57601, "close_doc": 32901, "save": 57603, "save_as": 57604, "save_copy": 32881,
    "update": 32880, "select_all": 57642, "delete": 32825, "convert_tex": 32922, "styleset": 32900,
}
SIZE_CMDS = {6: 32862, 7: 32863, 8: 32864, 9: 32865, 10: 32866, 11: 32867, 12: 32868, 14: 32869, 18: 32870, 24: 32871}
SIZE_PLUS_01, SIZE_MINUS_01 = 32913, 32915
LINKED_PREFIX = "From InDesign"
SAVE_TYPE_COMBO, SAVE_NAME_FIELD = 1136, 1148
STYLESET_LIST, STYLESET_MAKE_DEFAULT = 1113, 1112
IDOK, IDCANCEL, IDYES, IDNO = 1, 2, 6, 7
WM_NULL, WM_MDIACTIVATE = 0x0000, 0x0222
LB_FINDSTRINGEXACT, LB_SETCURSEL, LBN_SELCHANGE = 0x01A2, 0x0186, 1
BM_CLICK = 0x00F5

# file extension -> Save As type keyword (matched against the dialog's type list)
FORMATS = {".eps": "MathMagic EPS", ".pdf": "MathMagic PDF", ".wmf": "MathMagic WMF", ".mmf": "MathMagic file",
           ".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".gif": "GIF", ".bmp": "BMP", ".svg": "SVG",
           ".mml": "MathML", ".mathml": "MathML", ".xml": "MathML", ".html": "MathML", ".htm": "MathML",
           ".tex": "LaTeX", ".amath": "AsciiMath", ".mathtxt": "Speech Text"}
AUTO_ACK = ("font_warning", "tip")


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
    has_styleset_list: bool = False
    buttons: list[str] = field(default_factory=list)

    @property
    def kind(self) -> str:
        return classify_dialog(self.title, self.texts, self.has_save_type_combo, self.has_styleset_list, self.buttons)

    def as_dict(self) -> dict:
        return {"hwnd": self.hwnd, "pid": self.pid, "title": self.title, "kind": self.kind, "texts": self.texts[:6]}


OK_BUTTONS = {"ok", "tamam"}


def classify_dialog(title: str, texts: list[str], has_save_type_combo: bool = False, has_styleset_list: bool = False,
                    buttons: list[str] | None = None) -> str:
    joined = "\n".join(texts).lower()
    if title == "Authorization" or "license code" in joined:
        return "license"
    if title == "Tip of the Day":
        return "tip"
    if "postscript name" in joined:
        return "font_warning"
    if has_save_type_combo:
        return "save_as"
    if has_styleset_list or title == "StyleSet":
        return "styleset"
    if "save changes" in joined or "değişiklik" in joined or ("kaydet" in joined and "?" in joined):
        return "save_changes"
    if any(k in joined for k in ("failed", "error no", "cannot ", "could not", "başarısız", "improper", "invalid")) and len(texts) <= 4:
        return "error_box"
    labels = [b.replace("&", "").strip().lower() for b in (buttons or [])]
    if len(labels) == 1 and labels[0] in OK_BUTTONS and title in ("MathMagic Pro", "MathMagic"):
        return "error_box"  # single-OK message box from MathMagic: informational, safe to acknowledge and report
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


def output_matches_format(path: str, keyword: str) -> bool:
    """Check the written file's signature against the requested format (catches a type switch that did not happen)."""
    with open(path, "rb") as stream:
        head = stream.read(512)
    text = head.decode("latin-1").lstrip("﻿").lstrip()
    checks = {
        "MathMagic EPS": head.startswith(b"%!PS-Adobe"), "MathMagic PDF": head.startswith(b"%PDF"),
        "PNG": head.startswith(b"\x89PNG"), "JPEG": head.startswith(b"\xff\xd8"), "GIF": head.startswith(b"GIF8"),
        "BMP": head.startswith(b"BM"), "SVG": "<svg" in text or text.startswith("<?xml"),
        "MathML": "<math" in text or text.startswith(("<?xml", "<!DOCTYPE", "<html")),
        "MathMagic WMF": head[:4] in (b"\xd7\xcd\xc6\x9a", b"\x01\x00\x09\x00"),
    }
    if keyword in checks:
        return checks[keyword]
    return not head.startswith(b"%!PS-Adobe")  # text formats (LaTeX, AsciiMath, Speech, MMF) must not be EPS


def format_keyword(path: str, ams: bool = False) -> str:
    ext = Path(path).suffix.lower()
    if ext not in FORMATS:
        raise ValueError(f"Unsupported output extension {ext!r}; use one of {sorted(FORMATS)}")
    return "AMS LaTeX" if ext == ".tex" and ams else FORMATS[ext]


class MathMagicWindows:
    def __init__(self, exe_path: str, sleep: Callable[[float], None] = time.sleep):
        self.exe_path = os.path.normcase(os.path.abspath(exe_path))
        self.exe_name = os.path.basename(exe_path)
        self.sleep = sleep
        # When set, the dialog guard only looks at this MathMagic process: a license dialog of ANOTHER
        # MathMagic process (e.g. one the InDesign plugin just started) must not block offline work.
        self.scope_pid: int | None = None

    # ------------------------------------------------------------ discovery (read-only)
    def _is_mm(self, hwnd: int) -> bool:
        path = w.image_path(w.pid_of(hwnd))
        return bool(path) and os.path.normcase(os.path.abspath(path)) == self.exe_path

    def visible_top(self) -> list[int]:
        """Visible top-level windows of MathMagic processes. Filters by pid (cheap) instead of querying the
        image path of every desktop window; the pid set is cached for 1 s (wait loops poll every ~30 ms)."""
        pids = self._pid_set()
        if not pids:
            return []
        return w.top_windows(lambda h: w.is_visible(h) and w.pid_of(h) in pids)

    def _pid_set(self) -> set[int]:
        now = time.monotonic()
        cache = getattr(self, "_pid_cache", None)
        if cache and now - cache[0] < 1.0:
            return cache[1]
        pids = {pid for pid in self.pids() if self._pid_is_mm(pid)}
        self._pid_cache = (now, pids)
        return pids

    def _pid_is_mm(self, pid: int) -> bool:
        path = w.image_path(pid)
        return bool(path) and os.path.normcase(os.path.abspath(path)) == self.exe_path

    def pids(self) -> list[int]:
        return sorted(pid for pid, name in w.process_names().items() if name.lower() == self.exe_name.lower())

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
            has_list = any(w.ctrl_id(k) == STYLESET_LIST and w.class_name(k) == "ListBox" for k in kids)
            buttons = [w.text(k) for k in kids if w.class_name(k) == "Button" and w.is_visible(k) and w.text(k).strip()]
            result.append(Dialog(h, w.pid_of(h), w.text(h), texts, has_combo, has_list, buttons))
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

    def responsive(self, hwnd: int, timeout_ms: int = 2000) -> bool:
        return w.send_timeout(hwnd, WM_NULL, 0, 0, timeout_ms)

    def status(self) -> dict:
        dialogs = [d.as_dict() for d in self.dialogs()]
        mains = self.mains()
        return {"running": bool(self.pids()), "pids": self.pids(), "main_windows": mains,
                "responsive": all(self.responsive(m["hwnd"]) for m in mains) if mains else None,
                "documents": [{"title": d.title, "linked": d.linked} for d in self.all_documents()],
                "dialogs": dialogs, "license_blocked": any(d["kind"] == "license" for d in dialogs)}

    # ------------------------------------------------------------ dialog guard
    def guard_dialogs(self, auto_ack: bool = True, strict: bool = False, allowed: Iterable[str] = ()) -> list[dict]:
        """Acknowledge known harmless dialogs. Raise on the license dialog and, in strict mode,
        on any dialog whose kind is not explicitly allowed (prevents posting into modal states)."""
        handled = []
        allowed = set(allowed)
        for d in self.dialogs():
            if self.scope_pid and d.pid != self.scope_pid:
                continue
            kind = d.kind
            if kind == "license":
                raise MathMagicError("LICENSE_REQUIRED", "MathMagic Authorization dialog is open; a person must authorize or press Try.",
                                     dialog=d.as_dict())
            if kind in AUTO_ACK and auto_ack:
                w.post(d.hwnd, w.WM_COMMAND, IDCANCEL, 0)  # font warning's only button is id 2; Tip closes on cancel
                handled.append({"acknowledged": kind, "text": (d.texts[-1] if d.texts else "")[:160]})
            elif kind == "error_box":
                raise MathMagicError("MATHMAGIC_ERROR", " | ".join(self._drain_error_boxes(d))[:500], dialog=d.as_dict())
            elif strict and kind not in allowed and kind not in AUTO_ACK:
                raise MathMagicError("UNEXPECTED_DIALOG", f"Unexpected MathMagic dialog ({kind}): {d.title}", dialog=d.as_dict())
        return handled

    def _drain_error_boxes(self, first: Dialog, rounds: int = 4) -> list[str]:
        """Acknowledge an error box and any follow-up boxes MathMagic shows right after it; return their messages."""
        messages, current = [], [first]
        for _ in range(rounds):
            for d in current:
                messages.append(next((t for t in d.texts if len(t.strip()) > 8 and t.strip() not in ("Tamam", "OK")), d.title).strip())
                w.post(d.hwnd, w.WM_COMMAND, IDCANCEL, 0)
            self.sleep(0.4)
            current = [d for d in self.dialogs() if d.kind == "error_box"]
            if not current:
                break
        return messages

    def wait_for(self, predicate: Callable[[], object], timeout: float, on_tick: Callable[[], None] | None = None,
                 auto_ack: bool = True, acks: list | None = None, interval: float = 0.03,
                 strict: bool = True, allowed: Iterable[str] = ()):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if on_tick:
                on_tick()
            handled = self.guard_dialogs(auto_ack, strict, allowed)
            if acks is not None:
                acks.extend(handled)
            value = predicate()
            if value:
                return value
            self.sleep(interval)
        return None

    # ------------------------------------------------------------ process lifecycle
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
            acked.extend(self.guard_dialogs(auto_ack=True))
            if st["main_windows"] and all(m["enabled"] for m in st["main_windows"]):
                return {"ok": True, "status": "READY", "shell_code": code, "acknowledged": acked, **st}
            self.sleep(0.25)
        return {"ok": False, "status": "TIMEOUT", "shell_code": code, **self.status()}

    def ensure_ready(self, prefer_linked: bool = False, auto_launch: bool = True) -> int:
        """Return an enabled, responsive main window; launch MathMagic (no activation) if needed.
        Scopes the dialog guard to that MathMagic process."""
        self.scope_pid = None
        if not any(m["enabled"] for m in self.mains()):
            self.guard_dialogs(strict=True)
            if auto_launch:
                res = self.launch_no_activate()
                if not res.get("ok"):
                    raise MathMagicError(res.get("status", "LAUNCH_FAILED"), "MathMagic could not be started without user action",
                                         launch={k: res.get(k) for k in ("status", "dialogs")})
        main = self.pick_main(prefer_linked)
        self.scope_pid = w.pid_of(main)
        self.guard_dialogs(strict=True)
        if not self.responsive(main, 5000):
            raise MathMagicError("MATHMAGIC_NOT_RESPONDING", "MathMagic does not respond to window messages")
        return main

    def pick_main(self, prefer_linked: bool = False) -> int:
        mains = [m for m in self.mains() if m["enabled"]]
        if not mains:
            self.guard_dialogs(auto_ack=False)
            raise MathMagicError("MATHMAGIC_NOT_READY", "No enabled MathMagic main window. Launch MathMagic (mathmagic_launch).")
        mains.sort(key=lambda m: m["linked_mode"] != prefer_linked)
        return mains[0]["hwnd"]

    # ------------------------------------------------------------ documents
    def activate(self, doc: Document) -> None:
        """Make doc the active MDI child; menu commands go to the active child. Never changes the Windows foreground."""
        mdi = w.find_child_class(doc.main, "MDIClient")
        if mdi:
            w.send_timeout(mdi, WM_MDIACTIVATE, doc.frame, 0)

    def new_document(self, main: int, timeout: float = 5.0, on_tick=None) -> Document:
        before = {d.frame for d in self.documents(main)}
        w.post(main, w.WM_COMMAND, CMD["new"], 0)
        doc = self.wait_for(lambda: next((d for d in self.documents(main) if d.frame not in before and d.view), None),
                            timeout, on_tick)
        if not doc:
            raise MathMagicError("NEW_DOCUMENT_TIMEOUT", "MathMagic did not open a new equation window")
        return doc

    RECYCLE_EVERY = int(os.environ.get("MATHMAGIC_RECYCLE_EVERY", "25"))

    def work_document(self, main: int, on_tick=None) -> Document:
        """Reusable unlinked document. Every RECYCLE_EVERY uses it is replaced by a fresh one (new first, then the
        old one is closed without saving) - MathMagic slows down as a document's edit history grows (measured:
        ~1.9-2.6 s -> ~1.4-1.9 s per render after recycling)."""
        uses = getattr(self, "_work_uses", 0) + 1
        self._work_uses = uses
        doc = next((d for d in self.documents(main) if not d.linked and d.view), None)
        if doc and self.RECYCLE_EVERY and uses % self.RECYCLE_EVERY == 0:
            fresh = self.new_document(main, on_tick=on_tick)
            for old in [d for d in self.documents(main) if not d.linked and d.frame != fresh.frame]:
                self.close_document(old, discard=True)
            return fresh
        return doc or self.new_document(main, on_tick=on_tick)

    def ensure_keeper(self, linked_doc: Document, on_tick=None) -> bool:
        if any(not d.linked for d in self.documents(linked_doc.main)):
            return False
        self.new_document(linked_doc.main, on_tick=on_tick)
        self.activate(linked_doc)
        return True

    def wait_linked_document(self, before: set[int], timeout: float = 20.0, on_tick=None, acks=None) -> Document:
        doc = self.wait_for(lambda: next((d for d in self.all_documents()
                                          if d.linked and d.frame not in before and d.view and w.is_enabled(d.main)), None),
                            timeout, on_tick, acks=acks)
        if not doc:
            raise MathMagicError("EDITOR_TIMEOUT", "No InDesign-linked MathMagic editor window appeared", status=self.status())
        return doc

    # ------------------------------------------------------------ editing (messages only)
    def queue_latex(self, doc: Document, latex: str, size_pt: float | None = None) -> None:
        """Post the whole edit in one FIFO burst: clear, type, select, convert (+ optional size).
        Posted messages to one thread are processed in order, so nothing waits per character."""
        self.activate(doc)
        w.post(doc.main, w.WM_COMMAND, CMD["select_all"], 0)
        w.post(doc.main, w.WM_COMMAND, CMD["delete"], 0)
        if not w.post_chars(doc.view, latex):
            raise MathMagicError("TYPE_FAILED", "MathMagic message queue rejected WM_CHAR")
        w.post(doc.main, w.WM_COMMAND, CMD["select_all"], 0)
        w.post(doc.main, w.WM_COMMAND, CMD["convert_tex"], 0)
        if size_pt is not None:
            for cmd in size_commands(size_pt):
                w.post(doc.main, w.WM_COMMAND, CMD["select_all"], 0)
                w.post(doc.main, w.WM_COMMAND, cmd, 0)

    def write_latex(self, doc: Document, latex: str, replace: bool = True, size_pt: float | None = None) -> None:
        """Synchronous variant (SendMessageTimeout per message, ~30 ms/char): returns only after MathMagic
        processed everything. Used when the next step is not itself an ordered barrier (e.g. a capture)."""
        self.activate(doc)
        if replace:
            w.send_timeout(doc.main, w.WM_COMMAND, CMD["select_all"])
            w.send_timeout(doc.main, w.WM_COMMAND, CMD["delete"])
        if not w.type_chars(doc.view, latex):
            raise MathMagicError("TYPE_FAILED", "MathMagic did not accept WM_CHAR input in time")
        w.send_timeout(doc.main, w.WM_COMMAND, CMD["select_all"])
        if not w.send_timeout(doc.main, w.WM_COMMAND, CMD["convert_tex"], timeout_ms=8000):
            raise MathMagicError("CONVERT_TIMEOUT", "Convert TeX to equation did not finish in time")
        for cmd in (size_commands(size_pt) if size_pt is not None else []):
            w.send_timeout(doc.main, w.WM_COMMAND, CMD["select_all"])
            w.send_timeout(doc.main, w.WM_COMMAND, cmd)

    def apply_size(self, doc: Document, size_pt: float) -> None:
        """Select all and post the size commands (FIFO; the next Save As is the ordered barrier). Re-applied on a
        reopened native .mmf so the whole equation carries the requested size. Note (measured live): the height of
        a wide hat / arc is a StyleSet spacing value (Over/Under templates > Embellishment height), not a function
        of the point size - it stays ~2-3 pt; adjust the StyleSet for very large sizes."""
        self.activate(doc)
        for cmd in size_commands(size_pt):
            w.post(doc.main, w.WM_COMMAND, CMD["select_all"], 0)
            w.post(doc.main, w.WM_COMMAND, cmd, 0)

    def update_linked(self, doc: Document, timeout: float = 20.0, on_tick=None, acks: list | None = None) -> None:
        if not doc.linked:
            raise MathMagicError("NOT_LINKED", "Update requires an InDesign-linked MathMagic window")
        self.activate(doc)
        w.post(doc.main, w.WM_COMMAND, CMD["update"], 0)
        closed = self.wait_for(lambda: not w.is_window(doc.frame), timeout, on_tick, acks=acks)
        if not closed:
            raise MathMagicError("UPDATE_TIMEOUT", "Linked equation window did not close after Update",
                                 dialogs=[d.as_dict() for d in self.dialogs()])

    def save_as(self, doc: Document, out_path: str, type_keyword: str = "MathMagic EPS", timeout: float = 10.0,
                on_tick=None, acks: list | None = None) -> str:
        out = str(Path(out_path).resolve())
        self.activate(doc)
        find_dialog = lambda: next((d for d in self.dialogs() if d.kind == "save_as"), None)  # noqa: E731
        commands = [CMD["save_copy"]] if doc.linked else [CMD["save_as"]]
        if not doc.linked and w.text(doc.frame).startswith("Equation-"):
            commands.append(CMD["save"])
        dlg = None
        for i, command in enumerate(commands):
            w.post(doc.main, w.WM_COMMAND, command, 0)
            dlg = self.wait_for(find_dialog, timeout if i == len(commands) - 1 else 4.0, on_tick, acks=acks,
                                allowed=("save_as",))
            if dlg:
                break
        if not dlg:
            raise MathMagicError("SAVE_DIALOG_TIMEOUT", "Save As dialog did not appear")
        kids = w.descendants(dlg.hwnd)
        combo = next(k for k in kids if w.ctrl_id(k) == SAVE_TYPE_COMBO and w.class_name(k) == "ComboBox")
        items = w.combo_items(combo)
        index = next((i for i, item in enumerate(items) if item.startswith(type_keyword)), None)
        if index is None:
            w.post(dlg.hwnd, w.WM_COMMAND, IDCANCEL, 0)
            raise MathMagicError("SAVE_TYPE_NOT_FOUND", f"No '{type_keyword}' entry in Save As types", types=items)
        w.send(combo, w.CB_SETCURSEL, index, 0)
        owner = w.parent(combo)
        for code in (9, w.CBN_SELCHANGE, 8):  # CBN_SELENDOK, CBN_SELCHANGE, CBN_CLOSEUP: verified to switch the type
            w.send(owner, w.WM_COMMAND, (code << 16) | SAVE_TYPE_COMBO, combo)
        name_edit = next((k for k in kids if w.ctrl_id(k) == SAVE_NAME_FIELD and w.class_name(k) == "Edit"), 0)
        if not name_edit:
            w.post(dlg.hwnd, w.WM_COMMAND, IDCANCEL, 0)
            raise MathMagicError("SAVE_FIELD_NOT_FOUND", "File name field not found in Save As dialog")
        w.set_text(name_edit, out)
        w.post(dlg.hwnd, w.WM_COMMAND, IDOK, 0)
        state = {"size": -1, "stable": 0}

        def ready() -> bool:
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
        try:
            done = self.wait_for(ready, timeout + 10, on_tick, acks=acks, interval=0.05, allowed=("save_as",))
        except MathMagicError:
            for d in self.dialogs():
                if d.kind == "save_as":
                    w.post(d.hwnd, w.WM_COMMAND, IDCANCEL, 0)
            raise
        if not done:
            for d in self.dialogs():
                if d.kind == "save_as":
                    w.post(d.hwnd, w.WM_COMMAND, IDCANCEL, 0)
            raise MathMagicError("SAVE_TIMEOUT", "File was not written", dialogs=[d.as_dict() for d in self.dialogs()])
        return out

    def open_file(self, main: int, path: str, timeout: float = 15.0, on_tick=None, acks: list | None = None) -> Document:
        """File > Open by window messages (absolute path typed into the file-name field); returns the new window.
        Used for MathMagic's native .mmf text files (e.g. wide hat / arc accents the TeX importer cannot build)."""
        target = str(Path(path).resolve())
        if not os.path.isfile(target):
            raise MathMagicError("OPEN_FILE_NOT_FOUND", f"File not found: {target}")
        before = {d.frame for d in self.documents(main)}

        def cancel_file_dialogs():
            for d in self.dialogs():
                if d.kind == "save_as":
                    w.post(d.hwnd, w.WM_COMMAND, IDCANCEL, 0)

        w.post(main, w.WM_COMMAND, CMD["open"], 0)
        dlg = self.wait_for(lambda: next((d for d in self.dialogs() if d.kind == "save_as"), None), 10.0, on_tick,
                            acks=acks, allowed=("save_as",))
        if not dlg:
            raise MathMagicError("OPEN_DIALOG_TIMEOUT", "Open dialog did not appear")
        name_edit = next((k for k in w.descendants(dlg.hwnd)
                          if w.ctrl_id(k) == SAVE_NAME_FIELD and w.class_name(k) == "Edit"), 0)
        if not name_edit:
            cancel_file_dialogs()
            raise MathMagicError("OPEN_FIELD_NOT_FOUND", "File name field not found in Open dialog")
        w.set_text(name_edit, target)
        w.post(dlg.hwnd, w.WM_COMMAND, IDOK, 0)
        try:
            doc = self.wait_for(lambda: next((d for d in self.documents(main) if d.frame not in before and d.view), None),
                                timeout, on_tick, acks=acks, allowed=("save_as",))
        except MathMagicError:
            cancel_file_dialogs()
            raise
        if not doc:
            cancel_file_dialogs()
            raise MathMagicError("OPEN_TIMEOUT", "MathMagic did not open the file", dialogs=[d.as_dict() for d in self.dialogs()])
        return doc

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

    # ------------------------------------------------------------ inventory
    def menu_inventory(self) -> list[dict]:
        main = self.pick_main(prefer_linked=False)
        items = []
        for path, cid, disabled in w.menu_items(main):
            items.append({"id": cid, "path": path, "class": classify_command(path, cid), "disabled": disabled,
                          "mcp_use": USED_BY_MCP.get(cid)})
        return items

    # ------------------------------------------------------------ StyleSet
    def apply_styleset(self, name: str, make_default: bool = True, apply_current: bool = True,
                       timeout: float = 8.0, on_tick=None) -> dict:
        """Select a StyleSet in Edit > StyleSet... and press Make Default / Apply (messages only)."""
        main = self.ensure_ready(auto_launch=True)
        doc = self.work_document(main, on_tick)
        self.activate(doc)
        w.post(main, w.WM_COMMAND, CMD["styleset"], 0)
        dlg = self.wait_for(lambda: next((d for d in self.dialogs() if d.kind == "styleset"), None), timeout, on_tick,
                            allowed=("styleset",))
        if not dlg:
            raise MathMagicError("STYLESET_DIALOG_TIMEOUT", "StyleSet dialog did not appear")
        kids = w.descendants(dlg.hwnd)
        lst = next(k for k in kids if w.ctrl_id(k) == STYLESET_LIST and w.class_name(k) == "ListBox")
        items = w.listbox_items(lst)
        index = next((i for i, item in enumerate(items) if item == name), -1)
        if index < 0:
            w.post(dlg.hwnd, w.WM_COMMAND, IDCANCEL, 0)
            raise MathMagicError("STYLESET_NOT_FOUND", f"StyleSet '{name}' is not listed", available=items)
        w.send(lst, LB_SETCURSEL, index, 0)
        w.send(dlg.hwnd, w.WM_COMMAND, (LBN_SELCHANGE << 16) | STYLESET_LIST, lst)
        steps = []
        if make_default:
            button = next(k for k in kids if w.ctrl_id(k) == STYLESET_MAKE_DEFAULT and w.class_name(k) == "Button")
            w.post(button, BM_CLICK, 0, 0)
            steps.append("make_default")
            # a confirmation box may appear; accept only a Yes/OK question owned by MathMagic
            self.sleep(0.4)
            for d in self.dialogs():
                if d.hwnd != dlg.hwnd and d.kind == "unknown":
                    steps.append({"confirmation": d.texts[:4]})
                    w.post(d.hwnd, w.WM_COMMAND, IDYES if any(t.lower() in ("&yes", "yes", "&evet", "evet") for t in d.texts) else IDOK, 0)
                    self.sleep(0.3)
        w.post(dlg.hwnd, w.WM_COMMAND, IDOK if apply_current else IDCANCEL, 0)
        steps.append("apply_current" if apply_current else "closed")
        closed = self.wait_for(lambda: not w.is_window(dlg.hwnd), timeout, on_tick, strict=False)
        if not closed:
            raise MathMagicError("STYLESET_DIALOG_STUCK", "StyleSet dialog did not close", dialogs=[x.as_dict() for x in self.dialogs()])
        return {"ok": True, "styleset": name, "steps": steps}


USED_BY_MCP = {57600: "new work document", 57601: "open native .mmf (wide hat / arc accents)", 57603: "save (untitled fallback)", 57604: "save as (render/export)",
               32881: "save a copy (linked)", 32880: "update to InDesign", 57642: "select all", 32825: "delete",
               32922: "convert TeX to equation", 32900: "StyleSet (set_style/apply_styleset)",
               **{cid: f"size {pt} pt" for pt, cid in SIZE_CMDS.items()}, SIZE_PLUS_01: "size +0.1 pt", SIZE_MINUS_01: "size -0.1 pt"}


def classify_command(path: str, cid: int) -> str:
    """Classify a MathMagic menu command for automation (based on the live menu inventory)."""
    low = path.lower()
    if cid in USED_BY_MCP:
        return "used_by_mcp"
    if any(k in low for k in ("copy", "cut", "paste", "make a clip")):
        return "excluded_clipboard"
    if low.startswith("help") or any(k in low for k in ("wolfram", "speak", "print", "authorization", "register", "update...", "exit")):
        return "excluded_external_or_license"
    if path.rstrip().endswith("...") or "..." in path.split("\t")[0]:
        return "dialog_only"
    if low.startswith(("view", "window")):
        return "ui_only_not_needed"
    return "message_safe_available"


def size_commands(size_pt: float) -> list[int]:
    """Menu commands that set the selection to size_pt using fixed sizes plus 0.1 pt steps."""
    if not 4 <= size_pt <= 72:
        raise ValueError("size_pt must be between 4 and 72")
    base = max((s for s in SIZE_CMDS if s <= size_pt), default=min(SIZE_CMDS))
    steps = round((size_pt - base) * 10)
    if steps > 60:
        raise ValueError("size_pt too far from a menu size; use a StyleSet base size instead")
    cmds = [SIZE_CMDS[base]]
    cmds += [SIZE_PLUS_01] * steps if steps >= 0 else [SIZE_MINUS_01] * (-steps)
    return cmds
