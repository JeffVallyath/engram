"""Grab the current selection with the clipboard trick.

Known limits, documented instead of pretended away:
- clipboard restore is TEXT-ONLY — an image/file-list on the clipboard is lost
  after a capture (full Win32 format preservation is a future improvement)
- a non-elevated engram can't send Ctrl+C into an elevated window (UIPI)
- a few apps block simulated copy; both cases surface as "no text selected"
"""

from __future__ import annotations

import ctypes
import logging
import os
import time
from ctypes import wintypes

import pyperclip
from pynput.keyboard import Controller, Key

from .config import CaptureConfig
from .models import CaptureResult

log = logging.getLogger(__name__)

kbd = Controller()

CF_UNICODETEXT = 13
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
VK_MODIFIERS = (0x11, 0x10, 0x12)  # ctrl, shift, alt

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# coarse app class for engram::source_* tags — deliberately NOT the window
# title, which leaks document/chat names
APP_CLASSES = {
    "chrome.exe": "browser",
    "msedge.exe": "browser",
    "firefox.exe": "browser",
    "brave.exe": "browser",
    "opera.exe": "browser",
    "vivaldi.exe": "browser",
    "code.exe": "vscode",
    "acrord32.exe": "pdf",
    "acrobat.exe": "pdf",
    "sumatrapdf.exe": "pdf",
    "foxitpdfreader.exe": "pdf",
    "winword.exe": "word",
    "excel.exe": "excel",
    "powerpnt.exe": "powerpoint",
    "onenote.exe": "onenote",
    "notepad.exe": "notepad",
    "windowsterminal.exe": "terminal",
}


def active_window_title() -> str:
    hwnd = user32.GetForegroundWindow()
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def active_process_name() -> str:
    hwnd = user32.GetForegroundWindow()
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = wintypes.DWORD(512)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def active_app_class() -> str:
    name = active_process_name()
    if not name:
        return "unknown"
    return APP_CLASSES.get(name, os.path.splitext(name)[0])


def _has_text_on_clipboard() -> bool:
    return bool(user32.IsClipboardFormatAvailable(CF_UNICODETEXT))


def _wait_for_modifier_release(timeout=1.0):
    # if the user still holds ctrl+alt from the hotkey, our ctrl+c would
    # land as ctrl+alt+c in the target app
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in VK_MODIFIERS):
            return
        time.sleep(0.01)


def _force_release_modifiers():
    # inject key-ups for ctrl/alt/shift so windows never ends up with a
    # stuck logical modifier (which makes the user's own ctrl+c stop working)
    for key in (Key.ctrl, Key.ctrl_l, Key.ctrl_r, Key.alt, Key.alt_l, Key.alt_r,
                Key.shift, Key.shift_l, Key.shift_r):
        try:
            kbd.release(key)
        except Exception:
            pass


def _poll_clipboard(timeout_ms: int) -> str:
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        try:
            txt = pyperclip.paste()
        except pyperclip.PyperclipException:
            txt = ""
        if txt:
            return txt
        time.sleep(0.03)
    return ""


def capture_selection(cfg: CaptureConfig) -> CaptureResult | None:
    # window info first, before any popup steals focus
    title = active_window_title()
    app = active_app_class()

    had_text = _has_text_on_clipboard()
    saved = pyperclip.paste() if had_text else None
    if not had_text and user32.CountClipboardFormats():
        log.info("clipboard held non-text content; it will not survive this capture")

    pyperclip.copy("")
    _wait_for_modifier_release()
    _force_release_modifiers()
    with kbd.pressed(Key.ctrl):
        kbd.press("c")
        kbd.release("c")
    _force_release_modifiers()
    txt = _poll_clipboard(cfg.clipboard_timeout_ms)

    if saved is not None:
        pyperclip.copy(saved)

    if not txt.strip():
        return None
    return CaptureResult(text=txt, window_title=title, app_class=app, prior_clipboard_was_text=had_text)
