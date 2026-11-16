"""Focused local MathMagic UI adapter (NOT screenshot/vision automation).

This is a best-effort compatibility adapter for the vendor's external equation
editor. MathMagic does not publish a supported Windows automation API. Use in
an attended interactive session, with user-validated shortcuts.
"""
from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from pathlib import Path


class MathMagicUIError(RuntimeError):
    pass


def _process_image(pid: int) -> str:
    if os.name != 'nt':
        return ''
    k32=ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION=0x1000
    k32.OpenProcess.argtypes=[wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.OpenProcess.restype=wintypes.HANDLE
    k32.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    k32.QueryFullProcessImageNameW.restype=wintypes.BOOL
    k32.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,False,pid)
    if not handle:
        return ''
    try:
        length=wintypes.DWORD(32768)
        buff=ctypes.create_unicode_buffer(length.value)
        if not k32.QueryFullProcessImageNameW(handle,0,buff,ctypes.byref(length)):
            return ''
        return buff.value
    finally:
        k32.CloseHandle(handle)


def _clipboard_text() -> str | None:
    u=ctypes.windll.user32
    k=ctypes.windll.kernel32
    if not u.OpenClipboard(None):
        return None
    try:
        if not u.IsClipboardFormatAvailable(13):
            return None
        h=u.GetClipboardData(13)
        if not h:
            return None
        k.GlobalLock.restype=ctypes.c_void_p
        p=k.GlobalLock(h)
        if not p:
            return None
        try:
            return ctypes.wstring_at(p)
        finally:
            k.GlobalUnlock(h)
    finally:
        u.CloseClipboard()


def _set_clipboard_text(value: str) -> None:
    if '\x00' in value:
        raise MathMagicUIError('NUL not supported in clipboard')
    u=ctypes.windll.user32
    k=ctypes.windll.kernel32
    k.GlobalAlloc.argtypes=[ctypes.c_uint,ctypes.c_size_t]
    k.GlobalAlloc.restype=ctypes.c_void_p
    k.GlobalLock.argtypes=[ctypes.c_void_p]
    k.GlobalLock.restype=ctypes.c_void_p
    k.GlobalUnlock.argtypes=[ctypes.c_void_p]
    k.GlobalFree.argtypes=[ctypes.c_void_p]
    u.SetClipboardData.argtypes=[ctypes.c_uint,ctypes.c_void_p]
    u.SetClipboardData.restype=ctypes.c_void_p
    data=(value+'\x00').encode('utf-16-le')
    for _ in range(8):
        if u.OpenClipboard(None):
            break
        time.sleep(.08)
    else:
        raise MathMagicUIError('Clipboard busy')
    h=None
    try:
        if not u.EmptyClipboard():
            raise MathMagicUIError('EmptyClipboard failed')
        GMEM_MOVEABLE=2
        k.GlobalAlloc.restype=ctypes.c_void_p
        k.GlobalLock.restype=ctypes.c_void_p
        h=k.GlobalAlloc(GMEM_MOVEABLE,len(data))
        if not h:
            raise MathMagicUIError('GlobalAlloc failed')
        p=k.GlobalLock(h)
        if not p:
            raise MathMagicUIError('GlobalLock failed')
        ctypes.memmove(p,data,len(data))
        k.GlobalUnlock(h)
        if not u.SetClipboardData(13,h):
            raise MathMagicUIError('SetClipboardData failed')
        h=None  # owned by OS
    finally:
        if h:
            k.GlobalFree(h)
        u.CloseClipboard()


class MathMagicUI:
    def __init__(self, exe_path: str, conversion_keys: str = '+{ENTER}',
                 save_keys: str = '^s', close_after_save: bool = False):
        self.exe_path=str(Path(exe_path))
        self.conversion_keys=conversion_keys
        self.save_keys=save_keys
        self.close_after_save=close_after_save

    def _find_window(self):
        try:
            from pywinauto import Desktop  # type: ignore
        except ImportError as exc:
            raise MathMagicUIError('Install pywinauto: pip install pywinauto') from exc
        expected=os.path.normcase(os.path.abspath(self.exe_path))
        windows=[]
        for win in Desktop(backend='uia').windows():
            try:
                if not win.is_visible() or not win.is_enabled():
                    continue
                process_path=_process_image(win.process_id())
                if process_path and os.path.normcase(os.path.abspath(process_path)) == expected:
                    windows.append(win)
            except Exception:
                continue
        if len(windows)>1:
            raise MathMagicUIError('Multiple MathMagic windows are visible; close extras before retrying')
        return windows[0] if windows else None

    def wait_for_window(self, timeout: float=20.0):
        if os.name!='nt':
            raise MathMagicUIError('MathMagic control requires Windows')
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            window=self._find_window()
            if window:
                return window
            time.sleep(.18)
        raise MathMagicUIError('MathMagic edit window not detected: check executable path, permissions and plugin')

    def paste_convert_save(self, latex: str, replace: bool=False, timeout: float=20.0) -> dict:
        # The editor is external; automation cannot prove mathematical equivalence.
        win=self.wait_for_window(timeout)
        try:
            from pywinauto.keyboard import send_keys  # type: ignore
        except ImportError as exc:
            raise MathMagicUIError('pywinauto is not installed') from exc
        old_clipboard=_clipboard_text()
        stages=[]
        try:
            win.set_focus()
            time.sleep(.12)
            if replace:
                # Editor Ctrl+A meaning must be checked with a test formula first.
                send_keys('^a', pause=.05)
                stages.append('select_all_editor_content')
            _set_clipboard_text(latex)
            send_keys('^v',pause=.05)
            stages.append('paste_latex')
            time.sleep(.18)
            send_keys(self.conversion_keys,pause=.05)
            stages.append('send_tex_conversion_shortcut')
            time.sleep(.2)
            send_keys(self.save_keys,pause=.05)
            stages.append('save_mathmagic')
            if self.close_after_save:
                time.sleep(.15)
                send_keys('^w',pause=.05)
                stages.append('close_editor')
        finally:
            if old_clipboard is not None:
                try:
                    time.sleep(.2)
                    _set_clipboard_text(old_clipboard)
                except Exception:
                    stages.append('clipboard_restore_failed')
        return {
            'submitted': True,
            'stages': stages,
            'window_title': win.window_text(),
            'verification': 'NOT_VERIFIED',
            'note': 'Keyboard commands sent. Check MathMagic equation appearance and inline InDesign object manually.'
        }