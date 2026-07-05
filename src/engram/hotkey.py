from __future__ import annotations

import keyboard


def register(combo, callback):
    keyboard.add_hotkey(combo, callback, suppress=False)


def unregister_all():
    keyboard.unhook_all_hotkeys()
