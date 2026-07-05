from __future__ import annotations

from pynput import keyboard as pk

_active = []


def _to_pynput(combo: str) -> str:
    # "ctrl+shift+a" -> "<ctrl>+<shift>+a"
    parts = [p.strip().lower() for p in combo.split("+")]
    return "+".join(f"<{p}>" if len(p) > 1 else p for p in parts)


def register(combo, callback):
    hk = pk.GlobalHotKeys({_to_pynput(combo): callback})
    hk.daemon = True
    hk.start()
    _active.append(hk)


def unregister_all():
    for hk in _active:
        hk.stop()
    _active.clear()
