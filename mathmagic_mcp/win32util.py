"""64-bit safe Win32 helpers used by the v0.3 message adapter.

Every function here is either read-only (enumerate / read text / sample the
foreground window / capture a window bitmap) or sends a *window message* to a
specific window. Nothing here moves focus, synthesizes keyboard or mouse input,
or touches the clipboard.
"""
from __future__ import annotations

import ctypes
import os
import struct
import time
import zlib
from ctypes import wintypes
from typing import Callable

IS_WINDOWS = os.name == "nt"

WM_SETTEXT = 0x000C
WM_CLOSE = 0x0010
WM_CHAR = 0x0102
WM_COMMAND = 0x0111
CB_GETCOUNT = 0x0146
CB_GETCURSEL = 0x0147
CB_GETLBTEXT = 0x0148
CB_GETLBTEXTLEN = 0x0149
CB_SETCURSEL = 0x014E
CBN_SELCHANGE = 1
SMTO_ABORTIFHUNG = 0x0002
SW_SHOWMINNOACTIVE = 7
PW_RENDERFULLCONTENT = 2

if IS_WINDOWS:
    _u32 = ctypes.WinDLL("user32", use_last_error=True)
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _g32 = ctypes.WinDLL("gdi32", use_last_error=True)
    _sh32 = ctypes.WinDLL("shell32", use_last_error=True)
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _sig(lib, name, restype, *argtypes):
        fn = getattr(lib, name)
        fn.restype = restype
        fn.argtypes = list(argtypes)
        return fn

    _EnumWindows = _sig(_u32, "EnumWindows", wintypes.BOOL, WNDENUMPROC, wintypes.LPARAM)
    _EnumChildWindows = _sig(_u32, "EnumChildWindows", wintypes.BOOL, wintypes.HWND, WNDENUMPROC, wintypes.LPARAM)
    _GetWindowThreadProcessId = _sig(_u32, "GetWindowThreadProcessId", wintypes.DWORD, wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    _GetWindowTextLengthW = _sig(_u32, "GetWindowTextLengthW", ctypes.c_int, wintypes.HWND)
    _GetWindowTextW = _sig(_u32, "GetWindowTextW", ctypes.c_int, wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    _GetClassNameW = _sig(_u32, "GetClassNameW", ctypes.c_int, wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    _IsWindow = _sig(_u32, "IsWindow", wintypes.BOOL, wintypes.HWND)
    _IsWindowVisible = _sig(_u32, "IsWindowVisible", wintypes.BOOL, wintypes.HWND)
    _IsWindowEnabled = _sig(_u32, "IsWindowEnabled", wintypes.BOOL, wintypes.HWND)
    _GetMenu = _sig(_u32, "GetMenu", wintypes.HMENU, wintypes.HWND)
    _GetWindow = _sig(_u32, "GetWindow", wintypes.HWND, wintypes.HWND, wintypes.UINT)
    _GetParent = _sig(_u32, "GetParent", wintypes.HWND, wintypes.HWND)
    _GetDlgCtrlID = _sig(_u32, "GetDlgCtrlID", ctypes.c_int, wintypes.HWND)
    _FindWindowExW = _sig(_u32, "FindWindowExW", wintypes.HWND, wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR)
    _GetForegroundWindow = _sig(_u32, "GetForegroundWindow", wintypes.HWND)
    _GetAsyncKeyState = _sig(_u32, "GetAsyncKeyState", ctypes.c_short, ctypes.c_int)  # read-only key state
    _PostMessageW = _sig(_u32, "PostMessageW", wintypes.BOOL, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    _SendMessageW = _sig(_u32, "SendMessageW", ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    _SendMessageTimeoutW = _sig(_u32, "SendMessageTimeoutW", ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                wintypes.LPARAM, wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t))
    _GetWindowRect = _sig(_u32, "GetWindowRect", wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    _PrintWindow = _sig(_u32, "PrintWindow", wintypes.BOOL, wintypes.HWND, wintypes.HDC, wintypes.UINT)
    _GetDC = _sig(_u32, "GetDC", wintypes.HDC, wintypes.HWND)
    _ReleaseDC = _sig(_u32, "ReleaseDC", ctypes.c_int, wintypes.HWND, wintypes.HDC)
    _CreateCompatibleDC = _sig(_g32, "CreateCompatibleDC", wintypes.HDC, wintypes.HDC)
    _CreateCompatibleBitmap = _sig(_g32, "CreateCompatibleBitmap", wintypes.HBITMAP, wintypes.HDC, ctypes.c_int, ctypes.c_int)
    _SelectObject = _sig(_g32, "SelectObject", wintypes.HGDIOBJ, wintypes.HDC, wintypes.HGDIOBJ)
    _GetDIBits = _sig(_g32, "GetDIBits", ctypes.c_int, wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                      ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT)
    _DeleteObject = _sig(_g32, "DeleteObject", wintypes.BOOL, wintypes.HGDIOBJ)
    _DeleteDC = _sig(_g32, "DeleteDC", wintypes.BOOL, wintypes.HDC)
    _OpenProcess = _sig(_k32, "OpenProcess", wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _CloseHandle = _sig(_k32, "CloseHandle", wintypes.BOOL, wintypes.HANDLE)
    _QueryFullProcessImageNameW = _sig(_k32, "QueryFullProcessImageNameW", wintypes.BOOL, wintypes.HANDLE, wintypes.DWORD,
                                       wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    _ShellExecuteW = _sig(_sh32, "ShellExecuteW", wintypes.HINSTANCE, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
                          wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int)
    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    _CreateToolhelp32Snapshot = _sig(_k32, "CreateToolhelp32Snapshot", wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD)
    _Process32FirstW = _sig(_k32, "Process32FirstW", wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    _Process32NextW = _sig(_k32, "Process32NextW", wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))


def require_windows() -> None:
    if not IS_WINDOWS:
        raise OSError("Windows is required for MathMagic/InDesign window operations")


def process_names() -> dict[int, str]:
    """pid -> executable file name for every running process (read-only)."""
    require_windows()
    snap = _CreateToolhelp32Snapshot(0x2, 0)
    result: dict[int, str] = {}
    if not snap or snap == wintypes.HANDLE(-1).value:
        return result
    try:
        entry = PROCESSENTRY32W(); entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = _Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            result[int(entry.th32ProcessID)] = entry.szExeFile
            ok = _Process32NextW(snap, ctypes.byref(entry))
    finally:
        _CloseHandle(snap)
    return result


def is_process_running(exe_name: str) -> bool:
    target = exe_name.lower()
    return any(name.lower() == target for name in process_names().values())


def pid_of(hwnd: int) -> int:
    pid = wintypes.DWORD(); _GetWindowThreadProcessId(hwnd, ctypes.byref(pid)); return int(pid.value)


def image_path(pid: int) -> str:
    handle = _OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024); size = wintypes.DWORD(1024)
        return buf.value if _QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)) else ""
    finally:
        _CloseHandle(handle)


def text(hwnd: int) -> str:
    n = _GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(max(n, 0) + 1); _GetWindowTextW(hwnd, buf, n + 1); return buf.value


def class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256); _GetClassNameW(hwnd, buf, 256); return buf.value


def is_window(hwnd: int) -> bool:
    return bool(hwnd) and bool(_IsWindow(hwnd))


def is_visible(hwnd: int) -> bool:
    return bool(_IsWindowVisible(hwnd))


def is_enabled(hwnd: int) -> bool:
    return bool(_IsWindowEnabled(hwnd))


def has_menu(hwnd: int) -> bool:
    return bool(_GetMenu(hwnd))


def ctrl_id(hwnd: int) -> int:
    return int(_GetDlgCtrlID(hwnd))


def parent(hwnd: int) -> int:
    return int(_GetParent(hwnd) or 0)


def first_child(hwnd: int) -> int:
    return int(_GetWindow(hwnd, 5) or 0)


def next_sibling(hwnd: int) -> int:
    return int(_GetWindow(hwnd, 2) or 0)


def find_child_class(hwnd: int, cls: str) -> int:
    return int(_FindWindowExW(hwnd, None, cls, None) or 0)


def top_windows(pred: Callable[[int], bool] | None = None) -> list[int]:
    found: list[int] = []

    @WNDENUMPROC
    def callback(hwnd, _):
        if pred is None or pred(int(hwnd)):
            found.append(int(hwnd))
        return True
    _EnumWindows(callback, 0)
    return found


def descendants(hwnd: int) -> list[int]:
    found: list[int] = []

    @WNDENUMPROC
    def callback(child, _):
        found.append(int(child)); return True
    _EnumChildWindows(hwnd, callback, 0)
    return found


def foreground() -> dict:
    hwnd = int(_GetForegroundWindow() or 0)
    if not hwnd:
        return {"hwnd": 0, "exe": "", "title": ""}
    path = image_path(pid_of(hwnd))
    return {"hwnd": hwnd, "exe": path.rsplit("\\", 1)[-1], "title": text(hwnd)[:80]}


def post(hwnd: int, msg: int, wparam: int = 0, lparam: int = 0) -> bool:
    return bool(_PostMessageW(hwnd, msg, wparam, lparam))


def send(hwnd: int, msg: int, wparam: int = 0, lparam: int = 0) -> int:
    return int(_SendMessageW(hwnd, msg, wparam, lparam))


def send_timeout(hwnd: int, msg: int, wparam: int = 0, lparam: int = 0, timeout_ms: int = 3000) -> bool:
    result = ctypes.c_size_t()
    return bool(_SendMessageTimeoutW(hwnd, msg, wparam, lparam, SMTO_ABORTIFHUNG, timeout_ms, ctypes.byref(result)))


def set_text(hwnd: int, value: str) -> None:
    buf = ctypes.create_unicode_buffer(value)
    _SendMessageW(hwnd, WM_SETTEXT, 0, ctypes.cast(buf, ctypes.c_void_p).value)


def combo_items(hwnd: int, limit: int = 60) -> list[str]:
    count = max(0, min(int(_SendMessageW(hwnd, CB_GETCOUNT, 0, 0)), limit))
    items = []
    for i in range(count):
        length = int(_SendMessageW(hwnd, CB_GETLBTEXTLEN, i, 0))
        buf = ctypes.create_unicode_buffer(max(length, 0) + 2)
        _SendMessageW(hwnd, CB_GETLBTEXT, i, ctypes.cast(buf, ctypes.c_void_p).value)
        items.append(buf.value)
    return items


def menu_items(hwnd: int, max_depth: int = 4) -> list[tuple[str, int, bool]]:
    """Read-only: flatten the window's menu bar into (path, command id, disabled)."""
    getmenu = _sig(_u32, "GetMenu", wintypes.HMENU, wintypes.HWND)
    getsub = _sig(_u32, "GetSubMenu", wintypes.HMENU, wintypes.HMENU, ctypes.c_int)
    count = _sig(_u32, "GetMenuItemCount", ctypes.c_int, wintypes.HMENU)
    getid = _sig(_u32, "GetMenuItemID", wintypes.UINT, wintypes.HMENU, ctypes.c_int)
    getstr = _sig(_u32, "GetMenuStringW", ctypes.c_int, wintypes.HMENU, wintypes.UINT, wintypes.LPWSTR, ctypes.c_int, wintypes.UINT)
    state = _sig(_u32, "GetMenuState", wintypes.UINT, wintypes.HMENU, wintypes.UINT, wintypes.UINT)
    out: list[tuple[str, int, bool]] = []

    def walk(menu, prefix: str, depth: int) -> None:
        for i in range(max(count(menu), 0)):
            buf = ctypes.create_unicode_buffer(256); getstr(menu, i, buf, 256, 0x400)
            label = buf.value.replace("&", "").strip()
            sub = getsub(menu, i)
            if not label and not sub:
                continue
            path = f"{prefix} > {label}" if prefix else label
            if sub:
                if depth < max_depth:
                    walk(sub, path, depth + 1)
            else:
                cid = int(getid(menu, i))
                if cid and cid != 0xFFFFFFFF:
                    out.append((path, cid, bool(state(menu, i, 0x400) & 0x3)))
    root = getmenu(hwnd)
    if root:
        walk(root, "", 0)
    return out


def utf16_units(value: str) -> tuple[int, ...]:
    data = value.encode("utf-16-le")
    return struct.unpack("<%dH" % (len(data) // 2), data)


def post_chars(hwnd: int, value: str) -> bool:
    """Queue characters with PostMessage(WM_CHAR) in one burst (FIFO with later posted commands)."""
    return all(post(hwnd, WM_CHAR, unit, 1) for unit in utf16_units(value))


def listbox_items(hwnd: int, limit: int = 500) -> list[str]:
    count = max(0, min(int(_SendMessageW(hwnd, 0x018B, 0, 0)), limit))  # LB_GETCOUNT
    items = []
    for i in range(count):
        length = int(_SendMessageW(hwnd, 0x018A, i, 0))  # LB_GETTEXTLEN
        buf = ctypes.create_unicode_buffer(max(length, 0) + 2)
        _SendMessageW(hwnd, 0x0189, i, ctypes.cast(buf, ctypes.c_void_p).value)  # LB_GETTEXT
        items.append(buf.value)
    return items


def type_chars(hwnd: int, value: str, timeout_ms: int = 3000) -> bool:
    """Deliver characters synchronously with WM_CHAR (UTF-16 code units). No keyboard input."""
    return all(send_timeout(hwnd, WM_CHAR, unit, 1, timeout_ms) for unit in utf16_units(value))


def shell_open_no_activate(path: str, args: str | None = None) -> int:
    return int(_ShellExecuteW(None, "open", path, args, None, SW_SHOWMINNOACTIVE) or 0)


def capture_png(hwnd: int, out_path: str) -> dict:
    """Render a window (even if covered / not foreground) with PrintWindow into a PNG file."""
    rect = wintypes.RECT(); _GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return {"ok": False, "error": "window has no size"}
    screen = _GetDC(None); dc = _CreateCompatibleDC(screen)
    bmp = _CreateCompatibleBitmap(screen, width, height); old = _SelectObject(dc, bmp)
    try:
        ok = bool(_PrintWindow(hwnd, dc, PW_RENDERFULLCONTENT))
        header = struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        hdr = ctypes.create_string_buffer(header, len(header))
        pixels = ctypes.create_string_buffer(width * height * 4)
        _GetDIBits(dc, bmp, 0, height, pixels, hdr, 0)
        write_png(out_path, width, height, pixels.raw)
        return {"ok": ok, "path": out_path, "width": width, "height": height}
    finally:
        _SelectObject(dc, old); _DeleteObject(bmp); _DeleteDC(dc); _ReleaseDC(None, screen)


def write_png(path: str, width: int, height: int, bgra: bytes) -> None:
    """Minimal dependency-free PNG writer for top-down 32-bit BGRA pixels."""
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        row = bgra[y * stride:(y + 1) * stride]
        raw.append(0)
        for x in range(0, stride, 4):
            raw += bytes((row[x + 2], row[x + 1], row[x]))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b"")
    with open(path, "wb") as stream:
        stream.write(png)


MODIFIER_KEYS = {"shift": 0x10, "ctrl": 0x11, "alt": 0x12, "lwin": 0x5B, "rwin": 0x5C}


def modifiers_down() -> list[str]:
    """Modifier keys the USER is physically holding (read-only GetAsyncKeyState; nothing is sent).
    Live E2E 2026-11-17: while the user held Alt for Alt+Tab, characters posted to MathMagic were swallowed and the
    equation came out empty, so typing waits until modifiers are released."""
    if not IS_WINDOWS:
        return []
    return [name for name, vk in MODIFIER_KEYS.items() if _GetAsyncKeyState(vk) & 0x8000]


def wait_modifiers_released(timeout: float = 5.0, poll: float = 0.05) -> dict:
    t0 = time.monotonic(); held = modifiers_down(); seen = list(held)
    while held and time.monotonic() - t0 < timeout:
        time.sleep(poll)
        held = modifiers_down()
        seen += [k for k in held if k not in seen]
    return {"waited_s": round(time.monotonic() - t0, 3), "held": seen, "released": not held}


class FocusRecorder:
    """Samples the foreground window during an operation (read-only evidence)."""

    def __init__(self, getter: Callable[[], dict] | None = None):
        self.getter = getter or foreground
        self.t0 = time.monotonic()
        self.start = self.getter()
        self.samples = [{"t": 0.0, **self.start}]

    def sample(self) -> None:
        current = self.getter()
        if current.get("hwnd") != self.samples[-1].get("hwnd"):
            self.samples.append({"t": round(time.monotonic() - self.t0, 3), **current})

    AUTOMATED_APPS = ("mathmagic", "indesign")

    def summary(self) -> dict:
        """foreground_changed: any window change. took_focus_from_user: the user's own app
        (anything but MathMagic/InDesign) lost the foreground during the operation."""
        self.sample()
        changes = [s for s in self.samples[1:]]
        start_exe = (self.start.get("exe") or "").lower()
        user_app = bool(start_exe) and not start_exe.startswith(self.AUTOMATED_APPS)
        process_changed = any((c.get("exe") or "").lower() != start_exe for c in changes)
        # Only MathMagic/InDesign coming to the front counts as taken focus; the user switching between their own
        # apps (Alt+Tab to Chrome, Claude...) during the operation is reported separately (live E2E false positive).
        automated_front = any((c.get("exe") or "").lower().startswith(self.AUTOMATED_APPS) for c in changes)
        return {"foreground_start": f"{self.start.get('exe')} | {self.start.get('title')}",
                "foreground_changes": [f"{c['t']}s {c.get('exe')} | {c.get('title')}" for c in changes],
                "foreground_changed": bool(changes),
                "foreground_process_changed": process_changed,
                "user_switched_apps": process_changed and not automated_front,
                "took_focus_from_user": user_app and automated_front}
